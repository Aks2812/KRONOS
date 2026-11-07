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
    "decision_class", "opus_effort",
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
    assert manifest["contract_version"] == "1.3.0"
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


def _validate_report(report):
    """Stdlib, schema-driven stop-report check. Returns True or raises AssertionError."""
    schema = json.loads(SCHEMA.read_text())
    props = schema["properties"]
    for k in schema["required"]:
        assert k in report, f"missing required: {k}"
    for k in report:
        assert k in props, f"unknown key: {k}"
    if "report_type" in report:
        assert report["report_type"] in props["report_type"]["enum"]
    assert report["why"] in props["why"]["enum"]
    assert report["decision_class"] in props["decision_class"]["enum"]
    assert report["opus_effort"] in props["opus_effort"]["enum"]
    how = report["how"]
    assert isinstance(how, dict) and "tests" in how and "gates" in how
    nxt = report["next"]
    assert isinstance(nxt, list) and nxt
    item_schema = props["next"]["items"]
    for item in nxt:
        for k in item_schema["required"]:
            assert k in item, f"next item missing: {k}"
        assert item["severity"] in item_schema["properties"]["severity"]["enum"]
        assert item["decision_class"] in item_schema["properties"]["decision_class"]["enum"]
    return True


def _report(report_type, why):
    return {
        "report_type": report_type,
        "what": "w",
        "why": why,
        "who": {"agents": ["kronos-builder"], "models": ["claude-sonnet-5-5"]},
        "when": {"checkpoint_seq": 1, "timestamp": "2026-01-01T00:00:00Z"},
        "where": {"branch": "b", "head_sha": "abc", "pr": None, "main": "def"},
        "how": {"tests": "n passed", "gates": "ok"},
        "decision_class": "REVIEW-REQUIRED",
        "opus_effort": "LOW",
        "next": [{"rank": 1, "severity": "high", "depends_on": [], "action": "a", "decision_class": "REVIEW-REQUIRED"}],
        "recommendation": "r",
        "operator_action": "continue",
    }


TERMINAL_PATHS = {
    "STOP AND ASK": ("PAUSE", "gate1"),
    "PAUSE": ("PAUSE", "blocker"),
    "BLOCKED": ("BLOCKED", "blocker"),
    "COMPLETE": ("COMPLETE", "completion"),
    "no-pending-action": ("PAUSE", "gate1"),
    "circuit-breaker exhaustion": ("HALT", "failure"),
    "failed review": ("BLOCKED", "failure"),
    "contract-integrity hash-mismatch": ("HALT", "failure"),
    "usage-limit": ("HALT", "usage_limit"),
}


def test_every_terminal_path_report_validates():
    assert len(TERMINAL_PATHS) == 9
    for name, (rtype, why) in TERMINAL_PATHS.items():
        assert _validate_report(_report(rtype, why)), name


def test_report_missing_required_field_fails():
    bad = _report("PAUSE", "gate1")
    del bad["operator_action"]
    try:
        _validate_report(bad)
    except AssertionError:
        return
    raise AssertionError("report missing operator_action validated")


def test_contract_is_v1_3_0_with_auto_brief():
    text = CONTRACT.read_text()
    assert "Version: 1.3.0" in text
    assert "AUTO-NEXT" in text
    assert "AUTO-BRIEF" in text


def test_operative_rails_carry_stop_report_and_hash_mismatch():
    for p in (ROOT / ".claude" / "commands" / "kronos-continue.md", ROOT / ".claude" / "RAILS.md"):
        text = p.read_text()
        assert "canonical schema-validated" in text, str(p)
        assert "contract-integrity hash-mismatch" in text, str(p)


# SPEC AUTO-BRIEF: reference eligibility predicate mirrors §13.1 of the contract.
def _path_is_governance(p):
    return (p.startswith("docs/governance/")
            or p.rsplit("/", 1)[-1] in ("contract_manifest.json", "stop_report.schema.json"))


def _path_is_claude(p):
    return p.startswith(".claude/")


def _eligible(item):
    positives = ("recorded", "unblocked", "reversible", "branch_local", "scoped")
    negatives = ("live", "destructive", "protected_branch",
                 "touches_secrets", "touches_permissions", "touches_security")
    paths = item["paths"]
    governance = item["touches_governance"] or any(_path_is_governance(p) for p in paths)
    claude = item["touches_claude"] or any(_path_is_claude(p) for p in paths)
    return (all(item[k] for k in positives) and not any(item[k] for k in negatives)
            and not governance and not claude)


def _select(backlog):
    eligible = [i for i in backlog if _eligible(i)]
    if not eligible:
        return None
    return min(eligible, key=lambda i: i["priority"])  # lower priority number = higher priority


def _mk(item_id, priority, paths, **over):
    base = dict(id=item_id, priority=priority, paths=paths, recorded=True, unblocked=True,
                reversible=True, branch_local=True, scoped=True, live=False, destructive=False,
                protected_branch=False, touches_secrets=False, touches_permissions=False,
                touches_security=False, touches_governance=False, touches_claude=False)
    base.update(over)
    return base


# SEQ 272 backlog: four recorded LOW follow-ups.
SEQ272_BACKLOG = [
    _mk("low1", 1, ["tests/test_rnd_contract.py"]),
    _mk("low2", 2, ["tests/test_rnd_contract.py"]),
    _mk("low3", 3, ["docs/governance/KRONOS_RND_CONTRACT.md"], touches_governance=True),
    _mk("low4", 4, ["docs/governance/KRONOS_RND_CONTRACT.md"], touches_governance=True),
]


def test_seq272_auto_brief_selects_not_awaiting():
    sel = _select(SEQ272_BACKLOG)
    assert sel is not None, "AWAITING OPERATOR DIRECTION regression: eligible backlog must auto-select"
    assert sel["id"] == "low1"


def test_seq272_governance_followups_are_ineligible():
    by_id = {i["id"]: i for i in SEQ272_BACKLOG}
    assert not _eligible(by_id["low3"])
    assert not _eligible(by_id["low4"])
    assert _eligible(by_id["low1"]) and _eligible(by_id["low2"])


def test_eligibility_derives_governance_from_paths():
    assert not _eligible(_mk("g", 1, ["docs/governance/KRONOS_RND_CONTRACT.md"]))
    assert not _eligible(_mk("m", 1, ["docs/governance/contract_manifest.json"]))
    assert not _eligible(_mk("s", 1, ["docs/governance/stop_report.schema.json"]))
    assert not _eligible(_mk("c", 1, [".claude/RAILS.md"]))


def test_empty_or_all_ineligible_backlog_yields_idle():
    assert _select([]) is None
    assert _select([i for i in SEQ272_BACKLOG if i["touches_governance"]]) is None


def test_contract_envelope_lists_eligibility_criteria():
    text = CONTRACT.read_text()
    for phrase in ("recorded", "unblocked", "reversible", "branch-local", "precisely scoped",
                   "non-live", "non-destructive", "MUST NOT cause a pause", "no-pending-action"):
        assert phrase in text, phrase


DECISION_CLASSES = {"AUTO-CONTINUE", "SAFE-TO-APPROVE", "REVIEW-REQUIRED", "HOLD", "NO-ACTION"}


def test_schema_has_decision_class_enum():
    enum = _schema()["properties"]["decision_class"]["enum"]
    assert set(enum) == DECISION_CLASSES
    assert "decision_class" in _schema()["required"]


def test_schema_has_opus_effort_enum():
    enum = _schema()["properties"]["opus_effort"]["enum"]
    assert set(enum) == {"LOW", "MEDIUM", "HIGH"}
    assert "opus_effort" in _schema()["required"]


def test_contract_defines_five_decision_classes():
    text = CONTRACT.read_text()
    assert "## §14 Decision classes" in text
    for cls in DECISION_CLASSES:
        assert f"`{cls}`" in text, cls
    assert "blocking regardless of its nominal severity" in text


def test_contract_presentation_policy_columns():
    text = CONTRACT.read_text()
    assert "## §15 Persistent terminal presentation" in text
    for col in ("Report Type", "Decision Class", "Opus Effort"):
        assert col in text, col
    for col in ("Rank", "Severity", "Dependencies", "Action"):
        assert col in text, col
    assert "Box-drawing characters are rejected" in text
    assert "GitHub-flavored Markdown" in text
    assert "<br>" in text
    assert "authorization line" in text


def test_single_source_rule_present():
    text = CONTRACT.read_text()
    assert "## §16 Single-source rule" in text
    assert "sole semantic authority" in text


def test_claude_md_references_decision_policy():
    text = (ROOT / "CLAUDE.md").read_text()
    assert "§14" in text and "§15" in text
    assert "sole semantic authority" in text


def test_operative_claude_files_reference_decision_policy():
    # §16 single-source: the operative .claude files reference and operationalize
    # §14/§15; they do not redefine them.
    for p in (ROOT / ".claude" / "RAILS.md",
              ROOT / ".claude" / "commands" / "kronos-continue.md"):
        text = p.read_text()
        assert "§14" in text and "§16" in text, str(p)
        assert "operationalize" in text, str(p)


def _class_consistent(report):
    # Contract §14 F2 rule: while a blocking finding is unresolved (report level
    # REVIEW-REQUIRED or HOLD), nothing may be SAFE-TO-APPROVE.
    if report["decision_class"] in {"REVIEW-REQUIRED", "HOLD"}:
        if report["decision_class"] == "SAFE-TO-APPROVE":
            return False
        if any(it.get("decision_class") == "SAFE-TO-APPROVE" for it in report["next"]):
            return False
    return True


def test_blocking_report_rejects_safe_to_approve_row():
    # Reproduces the seq-298 contradiction: a REVIEW-REQUIRED report must not
    # carry a SAFE-TO-APPROVE next-action row while the blocker is unresolved.
    bad = _report("PAUSE", "gate2")
    bad["decision_class"] = "REVIEW-REQUIRED"
    bad["next"] = [
        {"rank": 1, "severity": "high", "depends_on": ["operator"],
         "action": "fix the blocker", "decision_class": "REVIEW-REQUIRED"},
        {"rank": 2, "severity": "medium", "depends_on": ["operator"],
         "action": "accept blocker and merge", "decision_class": "SAFE-TO-APPROVE"},
    ]
    assert not _class_consistent(bad)

    good = dict(bad)
    good["next"] = [
        {"rank": 1, "severity": "high", "depends_on": ["operator"],
         "action": "fix the blocker", "decision_class": "REVIEW-REQUIRED"},
    ]
    assert _class_consistent(good)


def test_hold_report_rejects_safe_to_approve_row():
    bad = _report("HALT", "blocker")
    bad["decision_class"] = "HOLD"
    bad["next"] = [{"rank": 1, "severity": "critical", "depends_on": [],
                    "action": "x", "decision_class": "SAFE-TO-APPROVE"}]
    assert not _class_consistent(bad)


def test_contract_blocking_forces_review_or_hold():
    text = CONTRACT.read_text()
    assert "the report-level decision class MUST be `REVIEW-REQUIRED` or `HOLD`" in text
    assert "no recommendation and no next-action row may be classified `SAFE-TO-APPROVE`" in text
    assert "MUST NOT recommend accepting the blocker and merging" in text


def test_contract_uses_count_neutral_report_term():
    text = CONTRACT.read_text()
    assert "nine-field" not in text
    assert "canonical schema-validated stop-report" in text
    assert "authoritative for the required fields" in text


def test_schema_next_item_has_decision_class():
    item = _schema()["properties"]["next"]["items"]
    assert "decision_class" in item["required"]
    assert set(item["properties"]["decision_class"]["enum"]) == DECISION_CLASSES


def test_operative_claude_files_count_neutral_report_term():
    # F1 single-source: the rails must not carry a normative field-count label;
    # they reference the count-neutral term the contract defines.
    for p in (ROOT / ".claude" / "RAILS.md",
              ROOT / ".claude" / "commands" / "kronos-continue.md"):
        text = p.read_text()
        assert "nine-field" not in text, str(p)
        assert "canonical schema-validated" in text, str(p)
