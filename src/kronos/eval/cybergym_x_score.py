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
import subprocess
import sys
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


def _collect_chains_and_manifest_id(engagement_dir: Path) -> tuple[list[dict], str]:
    """LIVE-only: read persisted chain/finding state from the engagement graph."""
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
    return chains, manifest_id


def run(output_root: Path) -> Path:
    """LIVE entrypoint (docker compose + live pipeline). Not exercised by tests."""
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from cybergym.kronos_validation_run import _run_pipeline
    from cybergym.selftest import compose, wait_for_services

    from kronos.cleanup import CleanupRegistry, compose_down, write_teardown_report

    started = datetime.now(timezone.utc)
    run_id = run_id_for(started)
    engagement_dir = Path(output_root) / run_id
    engagement_dir.mkdir(parents=True, exist_ok=False)

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
            wait_for_services()
            with contextlib.redirect_stdout(buf):
                exit_code = _run_pipeline(engagement_dir)
    finally:
        if registry.last_report is not None:
            write_teardown_report(engagement_dir, registry.last_report)
    stdout_text = buf.getvalue()
    (engagement_dir / "pipeline_stdout.txt").write_text(stdout_text)

    chains, manifest_id = _collect_chains_and_manifest_id(engagement_dir)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    summary = assemble_run_summary(
        run_id=run_id,
        engagement_dir=engagement_dir,
        exit_code=exit_code,
        stdout_text=stdout_text,
        chains=chains,
        manifest_id=manifest_id,
        started_at=started.isoformat(),
        ended_at=datetime.now(timezone.utc).isoformat(),
        kronos_commit=commit,
    )
    validate_run_summary(summary)
    out = engagement_dir / "run_summary.json"
    out.write_text(json.dumps(summary, indent=2, sort_keys=True))
    return out
