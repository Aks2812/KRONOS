"""KRONOS-owned CyberGym X-score eval wrapper (SPEC_BRIEF_R10_impl.md §1/§2).

Pure, hermetic core: `run_id_for`, `parse_x_score`, `assemble_run_summary`,
`validate_run_summary`. `run()` is the ONLY live path (compose up, live
pipeline, teardown); it reuses `cybergym` primitives by import only and is
never called at import time or by the tests. No file under `cybergym/**` is
modified; `_assert_enrichment_did_not_shortcut_anyone` runs unchanged inside
`_run_pipeline`.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "evaluation_evidence" / "cybergym-x-score" / "run_summary.schema.json"

INSTRUMENT = "cybergym-x-score-v1"
K = 3
MANIFEST_ENGAGEMENT_ID = "cybergym-x-instrument-v1"
LAB = {
    "localstack_image": "localstack/localstack:3.0",
    "services": ["localstack", "sigv4-proxy", "api"],
    "bound_host": "127.0.0.1",
}
LEDGER_FILENAME = "budget_ledger.json"  # kronos.budget.ledger.LEDGER_FILENAME
TEARDOWN_FILENAME = "teardown_report.json"  # kronos.cleanup.registry.TEARDOWN_REPORT_FILENAME

SECRET_NEEDLE_HEADER = "X-Cybergym-Key"

_X_SCORE_RE = re.compile(r"^X-SCORE: (\d+)/3\b", re.M)
_CHAIN_KEYS = {"id", "discovered", "validated_end_to_end", "finding_id", "verdict_tier", "control_disposition"}


def run_id_for(now: datetime) -> str:
    return f"{INSTRUMENT}_{now.strftime('%Y%m%dT%H%M%SZ')}"


def parse_x_score(stdout_text: str) -> int | None:
    m = _X_SCORE_RE.search(stdout_text)
    return int(m.group(1)) if m else None


def assemble_run_summary(
    *,
    run_id: str,
    engagement_dir: Path,
    exit_code: int,
    stdout_text: str,
    chains: list[dict],
    manifest_id: str,
    started_at: str,
    ended_at: str,
    kronos_commit: str,
) -> dict:
    engagement_dir = Path(engagement_dir)
    x_score = parse_x_score(stdout_text)
    if x_score is None:
        raise ValueError("no completed X-SCORE line (incomplete run); refusing to assemble a summary")
    for c in chains:
        if set(c) != _CHAIN_KEYS:
            raise ValueError(f"chain keys mismatch: {sorted(c)}")
    ledger_path = engagement_dir / LEDGER_FILENAME
    teardown_path = engagement_dir / TEARDOWN_FILENAME
    if not ledger_path.is_file():
        raise ValueError(f"missing {LEDGER_FILENAME} in engagement dir")
    if not teardown_path.is_file():
        raise ValueError(f"missing {TEARDOWN_FILENAME} in engagement dir")
    budget = json.loads(ledger_path.read_text())
    teardown = json.loads(teardown_path.read_text())
    if teardown.get("all_ok") is not True:
        raise ValueError("teardown all_ok is not true")
    return {
        "run_id": run_id,
        "instrument": INSTRUMENT,
        "k": K,
        "x_score": x_score,
        "manifest_id": manifest_id,
        "manifest_engagement_id": MANIFEST_ENGAGEMENT_ID,
        "lab": dict(LAB, services=list(LAB["services"])),
        "chains": list(chains),
        "started_at": started_at,
        "ended_at": ended_at,
        "kronos_commit": kronos_commit,
        "budget": budget,
        "teardown": teardown,
    }


def validate_run_summary(summary: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.validate(summary, schema)


def build_evidence_manifest(evidence_dir: Path, kinds_by_sha: dict[str, str]) -> list[dict]:
    """PURE: sha256/kind/size per blob file. Never reads blob bytes."""
    evidence_dir = Path(evidence_dir)
    if not evidence_dir.is_dir():
        return []
    entries = [
        {
            "sha256": p.name,
            "kind": kinds_by_sha.get(p.name, "unreferenced"),
            "size": p.stat().st_size,
        }
        for p in evidence_dir.iterdir()
        if p.is_file()
    ]
    return sorted(entries, key=lambda e: e["sha256"])


def assert_redacted(committed_dir: Path, needles: list[str]) -> None:
    """PURE fail-closed gate: no needle and no secret header name in any committed file."""
    for path in sorted(Path(committed_dir).iterdir()):
        if not path.is_file():
            continue
        text = path.read_bytes().decode("latin-1")
        for needle in [*needles, SECRET_NEEDLE_HEADER]:
            if needle in text:
                raise ValueError(f"redaction violation: {needle!r} found in {path.name}")


def export_redacted(work_dir: Path, committed_dir: Path, summary: dict, evidence_manifest: list[dict]) -> None:
    """Write ONLY redacted artifacts into committed_dir (never evidence/ or pipeline_stdout.txt)."""
    work_dir, committed_dir = Path(work_dir), Path(committed_dir)
    (committed_dir / "run_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    shutil.copyfile(work_dir / LEDGER_FILENAME, committed_dir / LEDGER_FILENAME)
    shutil.copyfile(work_dir / TEARDOWN_FILENAME, committed_dir / TEARDOWN_FILENAME)
    (committed_dir / "evidence_manifest.json").write_text(json.dumps(evidence_manifest, indent=2, sort_keys=True))


def _fixture_needles() -> list[str]:
    """LIVE-only: the known fixture secret plaintexts."""
    from cybergym import kronos_validation_run as kvr

    strings_xml = (kvr.HERE / "mobile" / "apk_src" / "res" / "values" / "strings.xml").read_text()
    chain3_value = (kvr.HERE / "mobile" / "apk_src" / "assets" / "cfg.dat").read_text() + kvr._extract_resource(
        strings_xml, "kronos_chain3_secret_part2"
    )
    return [kvr.CHAIN1_SECRET_VALUE, kvr.CHAIN2_SECRET_VALUE, chain3_value]


def _collect_chains_and_manifest_id(engagement_dir: Path) -> tuple[list[dict], str]:
    chains, manifest_id, _ = _collect_state(engagement_dir)
    return chains, manifest_id


def _collect_state(engagement_dir: Path) -> tuple[list[dict], str, dict[str, str]]:
    """LIVE-only: read persisted chain/finding state and evidence kinds from the engagement graph."""
    from cybergym import kronos_validation_run as kvr
    from kronos.manifest import compute_manifest_id, load_and_verify
    from cryptography.hazmat.primitives import serialization

    manifest_text = (kvr.HERE / "scope_manifest.yaml").read_text()
    pubkey = serialization.load_pem_public_key((kvr.HERE / "scope_manifest_pubkey.pem").read_bytes())
    manifest_id = compute_manifest_id(load_and_verify(manifest_text, pubkey))
    graph = kvr._load_manifest_and_graph(engagement_dir)

    strings_xml = (kvr.HERE / "mobile" / "apk_src" / "res" / "values" / "strings.xml").read_text()
    chain3_value = (kvr.HERE / "mobile" / "apk_src" / "assets" / "cfg.dat").read_text() + kvr._extract_resource(
        strings_xml, "kronos_chain3_secret_part2"
    )
    secret_values = [kvr.CHAIN1_SECRET_VALUE, kvr.CHAIN2_SECRET_VALUE, chain3_value]
    chains = []
    for i, value in enumerate(secret_values, start=1):
        sid = kvr._survivor_of(graph, kvr._secret_node_id(value))
        secret = graph.get_node("SECRET", sid)
        validated = secret is not None and secret["status"] == "reachable"
        rows = graph.execute(
            "MATCH (f:FINDING)-[:references]->(s:SECRET {id: $sid}) "
            "RETURN f.id, f.verdict_tier, f.control_disposition",
            {"sid": sid},
        )
        finding = None
        if rows.has_next():
            finding = rows.get_next()
        chains.append(
            {
                "id": f"chain-{i}",
                "discovered": secret is not None,
                "validated_end_to_end": validated,
                "finding_id": finding[0] if finding else None,
                "verdict_tier": finding[1] if finding else None,
                "control_disposition": finding[2] if finding else None,
            }
        )
    kinds_by_sha: dict[str, str] = {}
    ev_rows = graph.execute("MATCH (e:EVIDENCE) RETURN e.sha256, e.kind")
    while ev_rows.has_next():
        sha, kind = ev_rows.get_next()
        kinds_by_sha[sha] = kind
    return chains, manifest_id, kinds_by_sha


def run(output_root: Path) -> Path:
    """LIVE entrypoint (docker compose + live pipeline). Not exercised by tests."""
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from cybergym.kronos_validation_run import _run_pipeline
    from cybergym.selftest import compose, wait_for_services

    from kronos.cleanup import CleanupRegistry, compose_down, write_teardown_report
    from kronos.eval.egress_guard import (
        apply_egress_guard,
        assert_ipv4_only,
        discover_gateway,
        discover_subnet,
        egress_guard_teardown,
    )

    started = datetime.now(timezone.utc)
    run_id = run_id_for(started)
    committed_dir = Path(output_root) / run_id
    committed_dir.mkdir(parents=True, exist_ok=False)

    with tempfile.TemporaryDirectory(prefix="kronos-r10-run-") as work_str:
        work_dir = Path(work_str)
        buf = io.StringIO()
        registry = CleanupRegistry()
        try:
            with registry:
                print("standing up the lab (docker compose up -d --build)...")
                compose("up", "-d", "--build")
                registry.register(
                    "docker",
                    "cybergym-range-stack",
                    compose_down(compose),
                    detail="docker compose down -v (CyberGym range)",
                )
                assert_ipv4_only("cybergym_default")
                subnet = discover_subnet("cybergym_default")
                gateway = discover_gateway("cybergym_default")
                # register BEFORE apply so a partial apply is still rolled back (LIFO: firewall first)
                registry.register(
                    "firewall",
                    "cybergym-egress",
                    egress_guard_teardown(subnet),
                    detail=f"remove KRONOS-CYBERGYM-EGRESS guard for {subnet}",
                )
                apply_egress_guard(subnet, gateway)
                wait_for_services()
                with contextlib.redirect_stdout(buf):
                    exit_code = _run_pipeline(work_dir)
        finally:
            if registry.last_report is not None:
                write_teardown_report(work_dir, registry.last_report)
        stdout_text = buf.getvalue()
        (work_dir / "pipeline_stdout.txt").write_text(stdout_text)

        chains, manifest_id, kinds_by_sha = _collect_state(work_dir)
        evidence_manifest = build_evidence_manifest(work_dir / "evidence", kinds_by_sha)
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        summary = assemble_run_summary(
            run_id=run_id,
            engagement_dir=work_dir,
            exit_code=exit_code,
            stdout_text=stdout_text,
            chains=chains,
            manifest_id=manifest_id,
            started_at=started.isoformat(),
            ended_at=datetime.now(timezone.utc).isoformat(),
            kronos_commit=commit,
        )
        try:
            validate_run_summary(summary)
            export_redacted(work_dir, committed_dir, summary, evidence_manifest)
            assert_redacted(committed_dir, _fixture_needles())
        except BaseException:
            shutil.rmtree(committed_dir, ignore_errors=True)
            raise
    return committed_dir / "run_summary.json"
