"""Contract tests for docs/governance (stdlib only)."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "docs" / "governance"
CONTRACT = GOV / "KRONOS_RND_CONTRACT.md"
SCHEMA = GOV / "stop_report.schema.json"
MANIFEST = GOV / "contract_manifest.json"
CONTRACT_REF = "docs/governance/KRONOS_RND_CONTRACT.md"

REQUIRED_KEYS = {
    "what", "why", "who", "when", "where", "how",
    "next", "recommendation", "operator_action",
}
PINS = {
    "kronos-researcher.md": "claude-sonnet-5",
    "kronos-builder.md": "claude-sonnet-5-5",
    "kronos-reviewer.md": "claude-haiku-5-5",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_matches(path: Path, expected: str) -> bool:
    """Fail-closed predicate: True only if the on-disk sha256 equals expected."""
    return sha256_file(path) == expected


def _schema():
    return json.loads(SCHEMA.read_text())


def _frontmatter_model(path: Path) -> str:
    text = path.read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, f"no frontmatter in {path}"
    mm = re.search(r"^model:\s*(\S+)\s*$", m.group(1), re.M)
    assert mm, f"no model in {path}"
    return mm.group(1)


def test_schema_required_keys():
    assert set(_schema()["required"]) == REQUIRED_KEYS


def test_report_type_enum():
    enum = _schema()["properties"]["report_type"]["enum"]
    assert {"PAUSE", "HALT", "BLOCKED", "COMPLETE"} <= set(enum)


def test_next_item_requires_severity_depends_on_rank():
    item = _schema()["properties"]["next"]["items"]
    assert {"rank", "severity", "depends_on"} <= set(item["required"])


def test_manifest_hashes_match_disk():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["contract_version"] == "1.0.0"
    files = manifest["files"]
    listed = {Path(f["path"]).name for f in files}
    assert {CONTRACT.name, SCHEMA.name} <= listed
    for f in files:
        assert hash_matches(ROOT / f["path"], f["sha256"]), f["path"]


def test_role_model_pins():
    contract = CONTRACT.read_text()
    for name, model in PINS.items():
        assert _frontmatter_model(ROOT / ".claude" / "agents" / name) == model
        assert model in contract


def test_contract_references_present():
    paths = [
        ROOT / ".claude" / "commands" / "kronos-continue.md",
        ROOT / ".claude" / "RAILS.md",
    ] + [ROOT / ".claude" / "agents" / n for n in PINS]
    for p in paths:
        assert CONTRACT_REF in p.read_text(), str(p)


def test_continue_has_integrity_step():
    text = (ROOT / ".claude" / "commands" / "kronos-continue.md").read_text()
    assert "contract_manifest.json" in text
    assert "mismatch" in text


def test_hash_check_fails_closed_on_tamper():
    assert hash_matches(CONTRACT, sha256_file(CONTRACT))
    assert not hash_matches(CONTRACT, "0" * 64)
