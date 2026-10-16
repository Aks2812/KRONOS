"""Mobile static ingestion orchestrator (SPEC_BRIEF2 "WHAT THIS BUILDS").

`ingest_mobile_static` is the only public entry point. It targets the FIXED
ingestion contract from Brief #1 exactly: it returns a
`list[NodeUpsert | EdgeUpsert]` for `apply_upserts()` to write — it never
writes to the graph itself, and it never advances a SECRET past
`status="extracted"` (validation is a later brief).

Security lens (SPEC_BRIEF2): the APK and every tool's output (apktool,
jadx, MobSF) are untrusted input. This function must not crash on hostile
content, and — the most important property — it must never let extracted
data become an arbitrary prop on a node. Every NodeUpsert built here has its
`props` dict constructed from named, known-safe fields only; nothing here
ever does `props.update(some_extracted_dict)` or otherwise spreads
attacker-influenced keys into props. That's what keeps this module from
becoming a new path around Brief #1's upsert allowlist (see
test_hostile_input_graph_injection_blocked in test_mobile_ingest.py).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any

from kronos.evidence import store_evidence
from kronos.events import emit
from kronos.ingest import EdgeUpsert, NodeUpsert
from kronos.ingest.contract import DeclinedItem, IngestPlan, SourceDescriptor, build_report
from kronos.ingest.mobile import light_extractors
from kronos.ingest.mobile.manifest_parser import ManifestParseError, parse_manifest
from kronos.ingest.mobile.mobsf_client import MobSFClient

if TYPE_CHECKING:  # pragma: no cover
    from kronos.graph import EngagementGraph

_APKTOOL_TIMEOUT = 120
_JADX_TIMEOUT = 120

# SPEC_BRIEF9 §3: a stable identity for this source. `name` is written
# into each planned node's `source` column EXACTLY as it already was
# ("static", unchanged since Brief #2) — proof requirement §8.3/acceptance
# #3 is that conforming to the contract must not change a single planned
# node's id or props, so the version is reported alongside the plan
# (`IngestReport.source.version`, and the `ingest_started`/`ingest_finished`
# events) rather than folded into the `source` string itself.
MOBILE_STATIC_SOURCE = SourceDescriptor(name="static", version="1")


def _run_apktool_decode(apk_path: Path, out_dir: Path) -> None:
    subprocess.run(
        ["apktool", "d", "-f", str(apk_path), "-o", str(out_dir)],
        check=True, capture_output=True, timeout=_APKTOOL_TIMEOUT,
    )


def _run_jadx_decompile(apk_path: Path, out_dir: Path) -> None:
    # Best-effort: a dex-less or otherwise undecompilable APK is a normal
    # outcome (this brief's own test fixture has no classes.dex), not a
    # fatal error for the whole ingestion run.
    try:
        subprocess.run(
            ["jadx", str(apk_path), "-d", str(out_dir)],
            check=True, capture_output=True, timeout=_JADX_TIMEOUT,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pass


def _collect_string_resources(decoded_dir: Path) -> dict[str, str]:
    """Reads every <string name="...">value</string> under res/values*/ —
    not just strings.xml — since apktool can split resources across several
    values XML files. Malformed individual files are skipped, not fatal."""
    resources: dict[str, str] = {}
    values_dirs = list(decoded_dir.glob("res/values*"))
    for values_dir in values_dirs:
        for xml_path in values_dir.glob("*.xml"):
            try:
                root = ET.parse(xml_path).getroot()
            except ET.ParseError:
                continue
            for el in root.findall("string"):
                name = el.attrib.get("name")
                if name and el.text:
                    resources[name] = el.text
    return resources


def _collect_decompiled_text(jadx_out_dir: Path) -> str:
    """Best-effort concatenation of decompiled source for the light
    extractors' endpoint/secret regex pass. Bounded total size so a huge or
    adversarially bloated decompile output can't make this unbounded."""
    max_total = 2_000_000
    chunks: list[str] = []
    total = 0
    if not jadx_out_dir.exists():
        return ""
    for java_path in jadx_out_dir.rglob("*.java"):
        try:
            text = java_path.read_text(errors="replace")
        except OSError:
            continue
        chunks.append(text)
        total += len(text)
        if total >= max_total:
            break
    return "\n".join(chunks)


def _secret_node_id(value: str) -> str:
    return f"secret:{hashlib.sha256(value.encode()).hexdigest()[:16]}"


def _ingest_mobile_static_core(
    apk_path: str | Path,
    engagement: "EngagementGraph",
    mobsf_client: MobSFClient | None = None,
) -> tuple[list[NodeUpsert | EdgeUpsert], list[DeclinedItem]]:
    """The real extraction logic — UNCHANGED from Brief #2 except for the
    declined-tracking and event-emission plumbing threaded through
    (SPEC_BRIEF9 §3: "adapt, don't rewrite"). Both public entry points
    below (`ingest_mobile_static`, the legacy bare-list contract still
    depended on by `ingest()`/`cybergym/kronos_validation_run.py`, and
    `ingest_mobile_static_plan`, the new `IngestionSource`-conforming
    wrapper) call this exact same function — there is exactly one
    extraction code path, never two to keep in sync."""
    apk_path = Path(apk_path)
    engagement_dir = engagement.db_path.parent
    upserts: list[NodeUpsert | EdgeUpsert] = []
    declined: list[DeclinedItem] = []

    emit(engagement_dir, "ingest_started", source_name=MOBILE_STATIC_SOURCE.name, source_version=MOBILE_STATIC_SOURCE.version)

    with TemporaryDirectory(prefix="kronos-mobile-") as tmp:
        tmp_path = Path(tmp)
        decoded_dir = tmp_path / "decoded"
        jadx_dir = tmp_path / "jadx"

        _run_apktool_decode(apk_path, decoded_dir)

        manifest_text = (decoded_dir / "AndroidManifest.xml").read_text(errors="replace")
        try:
            manifest = parse_manifest(manifest_text)
        except ManifestParseError:
            # A manifest we can't parse means we can't safely identify the
            # app at all — nothing to ingest, but this must not crash the
            # whole run (hostile/malformed input is expected to occur).
            # Declining is a first-class, recorded outcome (SPEC_BRIEF9
            # §3), not a silent drop.
            declined_item = DeclinedItem(
                reason="unparseable_manifest", detail="AndroidManifest.xml failed to parse"
            )
            declined.append(declined_item)
            emit(engagement_dir, "ingest_declined", reason=declined_item.reason, detail=declined_item.detail)
            emit(
                engagement_dir,
                "ingest_finished",
                source_name=MOBILE_STATIC_SOURCE.name,
                node_count=0,
                edge_count=0,
                declined_count=len(declined),
            )
            return upserts, declined

        bundle_id = manifest.bundle_id
        upserts.append(
            NodeUpsert("MOBILE_APP", bundle_id, {"bundle_id": bundle_id, "platform": manifest.platform, "source": "static"})
        )

        for component in manifest.components:
            component_id = f"{bundle_id}/{component.name}"
            upserts.append(
                NodeUpsert(
                    "MOBILE_COMPONENT",
                    component_id,
                    {
                        "component_type": component.component_type,
                        "name": component.name,
                        "exported": component.exported,
                        "source": "static",
                    },
                )
            )
            upserts.append(EdgeUpsert("contains", bundle_id, component_id))

        _run_jadx_decompile(apk_path, jadx_dir)
        resources = _collect_string_resources(decoded_dir)
        decompiled_text = _collect_decompiled_text(jadx_dir)

        found_secrets = light_extractors.extract_secrets_from_resources(resources)
        found_endpoints = light_extractors.extract_endpoints_from_resources(resources)
        # Decompiled source gets the endpoint scan too (URLs often live in
        # code, not just resources); secret-by-resource-name doesn't apply
        # to raw source text the same way, so it's endpoint-only here.
        if decompiled_text:
            found_endpoints.extend(
                light_extractors.extract_endpoints_from_resources({"__decompiled__": decompiled_text})
            )

        if mobsf_client is not None and mobsf_client.is_reachable():
            try:
                file_hash = mobsf_client.upload(apk_path)
                mobsf_client.scan(file_hash)
                report = mobsf_client.report_json(file_hash)
                from kronos.ingest.mobile.mobsf_client import (
                    extract_endpoints_from_report,
                    extract_secrets_from_report,
                )

                for entry in extract_secrets_from_report(report):
                    value = entry.get("value", "")
                    if value:
                        found_secrets.append(
                            light_extractors.FoundSecret(
                                resource_name="mobsf", raw_value=value, decoded_value=value, obfuscation="none"
                            )
                        )
                for entry in extract_endpoints_from_report(report):
                    value = entry.get("value", "")
                    if value:
                        found_endpoints.append(light_extractors.FoundEndpoint(resource_name="mobsf", url=value))
            except Exception:
                # MobSF is reachable but errored mid-scan (bad response,
                # timeout past is_reachable's quick check, etc.) — degrade
                # to the light-extractor findings already collected rather
                # than losing the whole ingestion run.
                pass

        seen_secret_values: set[str] = set()
        for found in found_secrets:
            if found.decoded_value in seen_secret_values:
                continue
            seen_secret_values.add(found.decoded_value)

            blob = found.decoded_value.encode()
            evidence_info = store_evidence(engagement_dir, blob, kind="mobile_secret")
            secret_id = _secret_node_id(found.decoded_value)

            upserts.append(
                NodeUpsert(
                    "SECRET",
                    secret_id,
                    {
                        "value_ref": "sha256:" + evidence_info["sha256"],
                        "kind": "api_key" if found.obfuscation == "none" else "api_key_obfuscated",
                        "status": "extracted",
                        "source": "static",
                    },
                    scope_key=bundle_id,
                )
            )
            upserts.append(EdgeUpsert("leaks", bundle_id, secret_id))
            upserts.append(
                NodeUpsert(
                    "EVIDENCE",
                    evidence_info["sha256"],
                    {
                        "sha256": evidence_info["sha256"],
                        "blob_path": evidence_info["blob_path"],
                        "kind": "mobile_secret",
                        "created_at": evidence_info["created_at"],
                    },
                )
            )
            upserts.append(EdgeUpsert("evidences", evidence_info["sha256"], secret_id))

        seen_urls: set[str] = set()
        for found in found_endpoints:
            if found.url in seen_urls:
                continue
            seen_urls.add(found.url)
            upserts.append(NodeUpsert("API_ENDPOINT", found.url, {"source": "static"}))
            upserts.append(EdgeUpsert("references", bundle_id, found.url))

    emit(
        engagement_dir,
        "ingest_finished",
        source_name=MOBILE_STATIC_SOURCE.name,
        node_count=sum(1 for u in upserts if isinstance(u, NodeUpsert)),
        edge_count=sum(1 for u in upserts if isinstance(u, EdgeUpsert)),
        declined_count=len(declined),
    )
    return upserts, declined


def ingest_mobile_static(
    apk_path: str | Path,
    engagement: "EngagementGraph",
    mobsf_client: MobSFClient | None = None,
) -> list[NodeUpsert | EdgeUpsert]:
    """Legacy bare-list entry point (Brief #2's original contract),
    unchanged in signature and return shape — `ingest()`'s dispatcher and
    `cybergym/kronos_validation_run.py` (out of this brief's allowlist)
    both depend on getting exactly `list[NodeUpsert | EdgeUpsert]` back,
    not an `IngestPlan`. See `ingest_mobile_static_plan` below for the
    SPEC_BRIEF9 `IngestionSource`-conforming entry point; both call the
    identical extraction core, so this is an adaptation (two thin faces
    on one implementation), not two parsers to keep in sync."""
    upserts, _declined = _ingest_mobile_static_core(apk_path, engagement, mobsf_client)
    return upserts


def ingest_mobile_static_plan(
    apk_path: str | Path,
    engagement: "EngagementGraph",
    mobsf_client: MobSFClient | None = None,
) -> IngestPlan:
    """SPEC_BRIEF9 §3's `IngestionSource`-conforming entry point: same
    extraction core as `ingest_mobile_static`, wrapped into the formal
    `IngestPlan` (upserts + `IngestReport`) shape. Holds no graph handle
    beyond the single call — `engagement` is read only for its
    `db_path.parent` (where evidence blobs/events live), never stored,
    and nothing here ever calls `upsert_node`/`upsert_edge` directly
    (that's `apply_plan`'s job alone, see `ingest/contract.py`)."""
    upserts, declined = _ingest_mobile_static_core(apk_path, engagement, mobsf_client)
    report = build_report(MOBILE_STATIC_SOURCE, upserts, declined)
    return IngestPlan(upserts=tuple(upserts), report=report)
