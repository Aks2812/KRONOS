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
    assert manifest["contract_version"] == "1.4.1"
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


def test_contract_is_v1_4_1_with_auto_brief():
    text = CONTRACT.read_text()
    assert "Version: 1.4.1" in text
    assert "Contract-Version: 1.4.1" in text
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


LABELED_SECTIONS = [
    "[STATUS]", "[WHY]", "[WHERE]", "[WHEN]", "[WHAT]", "[WHO]", "[HOW]",
    "[HOW TO DO FOR NEXT STEP BASED ON SEVERITY]",
    "[MOST RECOMMENDED ACTION]", "[OPERATOR ACTION]", "[NEXT PROMPT]",
]


def test_contract_presentation_labeled_sections():
    text = CONTRACT.read_text()
    assert "## §15 Persistent terminal presentation" in text
    for label in LABELED_SECTIONS:
        assert label in text, label
    assert "RECOMMENDED ORCHESTRATOR EFFORT" in text
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


def test_section15_labeled_sections_in_order():
    text = CONTRACT.read_text()
    s15 = text[text.index("## §15"):text.index("## §16")]
    positions = [s15.index(label) for label in LABELED_SECTIONS]
    assert positions == sorted(positions), "labels out of order"
    assert s15.index("[STATUS]") == min(positions), "[STATUS] must be first"
    assert "RECOMMENDED ORCHESTRATOR EFFORT" in s15
    for cls in ("AUTO-CONTINUE", "SAFE-TO-APPROVE", "REVIEW-REQUIRED", "HOLD", "NO-ACTION"):
        assert cls in text
    banned = "┌┐└┘├┤┬┴┼─│╔╗╚╝═║"
    assert not [c for c in banned if c in text]


def test_section15_v1_4_0_self_check():
    text = CONTRACT.read_text()
    s15 = text[text.index("## §15"):text.index("## §16")]
    assert "presentation-only" in s15
    assert "Pre-response self-check" in s15
    check = s15[s15.index("Pre-response self-check"):]
    for frag in ("[STATUS]",
                 "valid §14 Decision Class",
                 "locked baseline",
                 "UNKNOWN",
                 "three sentences and 60 words",
                 "RECOMMENDED ORCHESTRATOR EFFORT",
                 "no flat key/value report",
                 "no box-drawing character"):
        assert frag in check, frag


def test_section15_when_fields_present():
    s15 = CONTRACT.read_text()
    s15 = s15[s15.index("## §15"):s15.index("## §16")]
    for frag in ("locked baseline", "numerator", "denominator",
                 "remaining gates", "ETA assumptions", "confidence"):
        assert frag in s15, frag
    assert "UNKNOWN" in s15


def test_section15_reference_ledger_conditional_under_what():
    s15 = CONTRACT.read_text()
    s15 = s15[s15.index("## §15"):s15.index("## §16")]
    assert "Goal-Framed Reference Knowledge Transfer Ledger" in s15
    assert "nested under `[WHAT]`" in s15
    assert "materially influenced" in s15
    assert "none materially influenced this iteration" in s15


def test_section15_reference_ledger_fields_and_no_research_as_implemented():
    s15 = CONTRACT.read_text()
    s15 = s15[s15.index("## §15"):s15.index("## §16")]
    for frag in ("source", "pinned SHA", "evidence ID", "license", "Observed",
                 "Inferred", "Unknown", "G1", "G2", "G3", "clean-room evolution",
                 "disposition", "implementation status"):
        assert frag in s15, frag
    assert "never represent research as implemented" in s15


def test_section15_most_recommended_action_bounded():
    s15 = CONTRACT.read_text()
    s15 = s15[s15.index("## §15"):s15.index("## §16")]
    assert "three sentences and 60 words" in s15
    assert "RECOMMENDED ORCHESTRATOR EFFORT" in s15
    assert "opus_effort" in s15  # D-D: validated enum, not a rename


def test_section15_report_bounded_and_concise_terms():
    s15 = CONTRACT.read_text()
    s15 = s15[s15.index("## §15"):s15.index("## §16")]
    assert "bounded" in s15
    assert "detailed evidence remains in artifacts" in s15
    assert "intermediate progress updates stay concise" in s15


def test_contract_invalid_decision_class_named_forbidden():
    text = CONTRACT.read_text()
    for bad in ("RESEARCH-ONLY", "DEFERRED", "NO-OP"):
        assert f"`{bad}`" in text, bad
        assert bad not in DECISION_CLASSES
    assert "exactly the five classes" in text
    assert set(_schema()["properties"]["decision_class"]["enum"]) == DECISION_CLASSES


def test_forbidden_decision_classes_rejected_as_reports():
    for bad in ("RESEARCH-ONLY", "DEFERRED", "NO-OP"):
        r = _report("PAUSE", "blocker")
        r["decision_class"] = bad
        try:
            _validate_report(r)
        except AssertionError:
            continue
        raise AssertionError(f"{bad} validated as a report decision class")


# ---- v1.4.0 schema extension: version-discriminated strict validation ----
V140_MILESTONE_KEYS = {"locked_baseline", "numerator", "denominator", "percentage",
                       "remaining_gates", "eta_assumptions", "confidence"}
V140_LEDGER_ENTRY_KEYS = {"source", "pinned_sha", "evidence_id", "license_privacy",
                          "epistemic_status", "goal_mapping", "clean_room_evolution",
                          "disposition", "implementation_status"}


def test_schema_v140_structure():
    s = _schema()
    assert s["properties"]["contract_version"]["type"] == "string"
    assert s["properties"]["effort_justification"]["type"] == "string"
    assert s["if"]["properties"]["contract_version"]["enum"] == ["1.4.0", "1.4.1"]
    assert {"contract_version", "effort_justification"} <= set(s["then"]["required"])
    assert "milestone" in s["then"]["properties"]["when"]["required"]
    assert "reference_ledger" in s["then"]["properties"]["how"]["required"]
    m = s["properties"]["when"]["properties"]["milestone"]
    assert set(m["required"]) == V140_MILESTONE_KEYS
    assert m["additionalProperties"] is False
    rl = s["properties"]["how"]["properties"]["reference_ledger"]
    assert set(rl["required"]) == {"applicable", "entries"}
    assert rl["additionalProperties"] is False
    entry = rl["properties"]["entries"]["items"]
    assert set(entry["required"]) == V140_LEDGER_ENTRY_KEYS
    assert entry["additionalProperties"] is False
    # historical compatibility: base when/how stay permissive (legacy reports unchanged)
    assert s["properties"]["when"].get("additionalProperties", True) is not False
    assert s["properties"]["how"].get("additionalProperties", True) is not False
    # no unbounded catch-all under v1.4.0: the then-branch closes when/how to declared keys
    assert s["then"]["properties"]["when"]["additionalProperties"] is False
    assert s["then"]["properties"]["how"]["additionalProperties"] is False
    # never-invent (AC3): numerator and denominator accept the literal "UNKNOWN"
    for field in ("numerator", "denominator"):
        branches = m["properties"][field]["anyOf"]
        assert any(b.get("const") == "UNKNOWN" for b in branches), field
    # explicit not-applicable: applicable:false forces an empty ledger
    assert rl["if"]["properties"]["applicable"]["const"] is False
    assert rl["then"]["properties"]["entries"]["maxItems"] == 0
    # object-preservation: the eleven required keys and both five-class enums intact
    assert set(s["required"]) == REQUIRED_KEYS
    assert set(s["properties"]["decision_class"]["enum"]) == DECISION_CLASSES
    assert set(s["properties"]["next"]["items"]["properties"]["decision_class"]["enum"]) == DECISION_CLASSES
    # fail-closed version discrimination: contract_version is an explicit enum AND required
    assert s["properties"]["contract_version"]["type"] == "string"
    assert list(s["properties"]["contract_version"]["enum"]) == ALLOWED_CONTRACT_VERSIONS
    assert {"required": ["contract_version"]} in s["allOf"]


def _report_v140(**over):
    r = _report("PAUSE", "blocker")
    r["contract_version"] = "1.4.0"
    r["effort_justification"] = "schema change touches the validated object and compatibility boundary"
    r["when"]["milestone"] = {
        "locked_baseline": "bb00179", "numerator": 3, "denominator": 11,
        "percentage": "UNKNOWN", "remaining_gates": ["review", "gate2"],
        "eta_assumptions": "none", "confidence": "medium",
    }
    r["how"]["reference_ledger"] = {"applicable": False, "entries": []}
    r.update(over)
    return r


def _validate_v140(report):
    """Stdlib mirror of the schema's version-discriminated v1.4.0 branch."""
    _validate_report(report)  # base object still validates
    assert report.get("contract_version") in STRICT_CONTRACT_VERSIONS
    assert isinstance(report.get("effort_justification"), str) and report["effort_justification"]
    milestone = report["when"]["milestone"]
    for k in V140_MILESTONE_KEYS:
        assert k in milestone, f"milestone missing: {k}"
    assert milestone["percentage"] == "UNKNOWN" or isinstance(milestone["percentage"], (int, float))
    ledger = report["how"]["reference_ledger"]
    assert {"applicable", "entries"} <= set(ledger)
    assert isinstance(ledger["applicable"], bool) and isinstance(ledger["entries"], list)
    for entry in ledger["entries"]:
        for k in V140_LEDGER_ENTRY_KEYS:
            assert k in entry, f"ledger entry missing: {k}"
        assert entry["epistemic_status"] in ("Observed", "Inferred", "Unknown")
        assert entry["disposition"] in ("Adopt", "Adapt", "Defer", "Investigate", "Reject")
    return True


def test_v140_report_validates_positive():
    assert _validate_v140(_report_v140())


def test_v140_report_with_ledger_entry_validates():
    r = _report_v140()
    r["how"]["reference_ledger"] = {"applicable": True, "entries": [{
        "source": "cybergym", "pinned_sha": "deadbeef", "evidence_id": "EV-1",
        "license_privacy": "internal", "epistemic_status": "Observed",
        "goal_mapping": ["G1"], "clean_room_evolution": "re-derived independently",
        "disposition": "Adapt", "implementation_status": "not-implemented",
    }]}
    assert _validate_v140(r)


def test_v140_missing_milestone_fails():
    r = _report_v140()
    del r["when"]["milestone"]
    try:
        _validate_v140(r)
    except (AssertionError, KeyError):
        return
    raise AssertionError("v1.4.0 report missing milestone validated")


def test_v140_missing_effort_justification_fails():
    r = _report_v140()
    del r["effort_justification"]
    try:
        _validate_v140(r)
    except (AssertionError, KeyError):
        return
    raise AssertionError("v1.4.0 report missing effort_justification validated")


def test_v140_missing_reference_ledger_fails():
    r = _report_v140()
    del r["how"]["reference_ledger"]
    try:
        _validate_v140(r)
    except (AssertionError, KeyError):
        return
    raise AssertionError("v1.4.0 report missing reference_ledger validated")


def test_v140_invalid_decision_class_fails():
    r = _report_v140()
    r["decision_class"] = "RESEARCH-ONLY"
    try:
        _validate_v140(r)
    except AssertionError:
        return
    raise AssertionError("v1.4.0 report with invalid decision class validated")


# Fail-closed version discrimination. Evidenced from committed history: contract versions
# 1.0.0..1.3.2 all shipped (KRONOS_RND_CONTRACT.md "Version:" history), but the current
# 11-required-key / five-decision-class stop-report object shape was introduced at contract
# v1.3.0 (schema commit 6a8d1d9 / PR #50). So only 1.3.0/1.3.1/1.3.2 are base-compatible legacy
# versions; 1.0.0/1.1.0/1.2.0 predate decision_class and cannot validate against the current base.
LEGACY_CONTRACT_VERSIONS = ["1.3.0", "1.3.1", "1.3.2"]
STRICT_CONTRACT_VERSIONS = ["1.4.0", "1.4.1"]
ALLOWED_CONTRACT_VERSIONS = LEGACY_CONTRACT_VERSIONS + STRICT_CONTRACT_VERSIONS
_MISSING = object()


def _validate_discriminated(report):
    """Stdlib mirror of the schema's fail-closed version discrimination.

    contract_version MUST be present and one of ALLOWED_CONTRACT_VERSIONS; a missing,
    non-string, or unrecognized/malformed value is rejected (never silent legacy fallback).
    Exact 1.4.0 -> strict v1.4.0 branch; a legacy version -> permissive base.
    """
    v = report.get("contract_version", _MISSING)
    assert v is not _MISSING, "missing contract_version"
    assert isinstance(v, str), "non-string contract_version"
    assert v in ALLOWED_CONTRACT_VERSIONS, f"unrecognized contract_version: {v!r}"
    if v in STRICT_CONTRACT_VERSIONS:
        _validate_v140(report)
    else:
        _validate_report(report)
    return True


def test_allowed_versions_match_schema_enum():
    assert list(_schema()["properties"]["contract_version"]["enum"]) == ALLOWED_CONTRACT_VERSIONS


def test_legacy_versions_validate_against_base():
    # positive: every evidenced base-compatible legacy version validates (permissive base)
    for v in LEGACY_CONTRACT_VERSIONS:
        legacy = _report("PAUSE", "blocker")
        legacy["contract_version"] = v
        assert _validate_discriminated(legacy), v


def test_exact_1_4_0_validates_strict():
    # positive: exact 1.4.0 enters the strict branch
    assert _validate_discriminated(_report_v140())


def test_malformed_or_unknown_version_rejected():
    # negative: malformed, incomplete, unknown-future, and prefixed versions are rejected
    for bad in ("1.4.0 ", " 1.4.0", "v1.4.0", "1.4", "1.4.0.0", "9.9.9", "1.2.0", "1.0.0", ""):
        r = _report_v140()
        r["contract_version"] = bad
        try:
            _validate_discriminated(r)
        except AssertionError:
            continue
        raise AssertionError(f"rejected version validated: {bad!r}")


def test_missing_or_non_string_version_rejected():
    # negative: a missing contract_version (old unversioned report) is rejected, not legacy fallback
    missing = _report("PAUSE", "blocker")
    assert "contract_version" not in missing
    try:
        _validate_discriminated(missing)
    except AssertionError:
        pass
    else:
        raise AssertionError("missing contract_version validated")
    # negative: a non-string contract_version is rejected
    nonstr = _report_v140()
    nonstr["contract_version"] = 140
    try:
        _validate_discriminated(nonstr)
    except AssertionError:
        return
    raise AssertionError("non-string contract_version validated")


# Real-schema validation: the stdlib mirrors above re-implement schema logic; these tests
# validate the same vectors against docs/governance/stop_report.schema.json via jsonschema.
def _real_validator():
    import jsonschema
    return jsonschema.Draft202012Validator(_schema())


def _real_valid(report) -> bool:
    return _real_validator().is_valid(report)


def _ledger_report_v140():
    r = _report_v140()
    r["how"]["reference_ledger"] = {"applicable": True, "entries": [{
        "source": "cybergym", "pinned_sha": "deadbeef", "evidence_id": "EV-1",
        "license_privacy": "internal", "epistemic_status": "Observed",
        "goal_mapping": ["G1"], "clean_room_evolution": "re-derived independently",
        "disposition": "Adapt", "implementation_status": "not-implemented",
    }]}
    return r


def _positive_vectors():
    vectors = []
    for v in LEGACY_CONTRACT_VERSIONS:
        legacy = _report("PAUSE", "blocker")
        legacy["contract_version"] = v
        vectors.append((f"legacy {v}", legacy))
    vectors.append(("exact 1.4.0", _report_v140()))
    vectors.append(("exact 1.4.1", _report_v140(contract_version="1.4.1")))
    vectors.append(("1.4.0 with ledger entry", _ledger_report_v140()))
    return vectors


def _negative_vectors():
    vectors = []
    missing = _report("PAUSE", "blocker")
    assert "contract_version" not in missing
    vectors.append(("missing contract_version", missing))
    nonstr = _report_v140()
    nonstr["contract_version"] = 140
    vectors.append(("non-string contract_version", nonstr))
    for bad in ("1.4.0 ", " 1.4.0", "v1.4.0", "1.4", "1.4.0.0", "9.9.9", "1.2.0", "1.0.0", "",
                "1.4.10", "1.5.0", "1.4.1 ", " 1.4.1"):
        r = _report_v140()
        r["contract_version"] = bad
        vectors.append((f"version {bad!r}", r))
    no_milestone = _report_v140()
    del no_milestone["when"]["milestone"]
    vectors.append(("missing when.milestone", no_milestone))
    no_effort = _report_v140()
    del no_effort["effort_justification"]
    vectors.append(("missing effort_justification", no_effort))
    no_ledger = _report_v140()
    del no_ledger["how"]["reference_ledger"]
    vectors.append(("missing how.reference_ledger", no_ledger))
    bad_class = _report_v140()
    bad_class["decision_class"] = "RESEARCH-ONLY"
    vectors.append(("invalid decision_class", bad_class))
    return vectors


def test_real_schema_accepts_positive_reports():
    validator = _real_validator()
    for name, report in _positive_vectors():
        errors = list(validator.iter_errors(report))
        assert not errors, f"{name}: {[e.message for e in errors]}"


def test_real_schema_rejects_negative_reports():
    validator = _real_validator()
    for name, report in _negative_vectors():
        assert not validator.is_valid(report), f"real schema accepted negative: {name}"


def test_mirror_and_real_schema_agree():
    # drift guard: stdlib mirror verdict must equal the real-schema verdict on every vector
    for name, report in _positive_vectors() + _negative_vectors():
        try:
            mirror_ok = _validate_discriminated(report)
        except (AssertionError, KeyError):
            mirror_ok = False
        assert mirror_ok == _real_valid(report), f"mirror/real-schema drift: {name}"


_BOX_CHARS = "┌┐└┘├┤┬┴┼─│╔╗╚╝═║"
_EFFORT_LINE = "RECOMMENDED ORCHESTRATOR EFFORT:"


def _validate_terminal_report(report: str) -> None:
    """Structural check of a v1.4.0 labeled-section terminal report."""
    assert not [c for c in _BOX_CHARS if c in report], "box-drawing character"
    pos = []
    for label in LABELED_SECTIONS:
        i = report.find(label)
        assert i != -1, f"missing section: {label}"
        pos.append(i)
    assert pos == sorted(pos), "sections out of order"
    assert report.lstrip().startswith("[STATUS]"), "[STATUS] must be first"
    assert _EFFORT_LINE in report, "missing effort line"
    assert report.index(_EFFORT_LINE) > pos[-1], "effort line must follow [OPERATOR ACTION]"


def test_terminal_report_structure_validator():
    import pytest
    good = "\n".join([
        "[STATUS] PAUSE / REVIEW-REQUIRED",
        "[WHY] blocker",
        "[WHERE] branch b, head abc, no PR, main def",
        "[WHEN] seq 1; baseline bb00179 3/11; remaining review,gate2; ETA UNKNOWN; confidence medium",
        "[WHAT] thing; ledger: none materially influenced this iteration",
        "[WHO] builder; sonnet",
        "[HOW] tests EV-1; gates ok",
        "[HOW TO DO FOR NEXT STEP BASED ON SEVERITY]",
        "1 high none REVIEW-REQUIRED do it",
        "[MOST RECOMMENDED ACTION] do the thing",
        "[OPERATOR ACTION] approve",
        "[NEXT PROMPT] NONE — loop continues autonomously",
        "RECOMMENDED ORCHESTRATOR EFFORT: LOW — routine",
    ])
    _validate_terminal_report(good)

    box = good.replace("[STATUS]", "─ [STATUS]", 1)
    missing = good.replace("[OPERATOR ACTION] approve\n", "")
    no_next = good.replace("[NEXT PROMPT] NONE — loop continues autonomously\n", "")
    noeffort = good.replace("RECOMMENDED ORCHESTRATOR EFFORT: LOW — routine", "done")
    lines = good.splitlines()
    lines[1], lines[2] = lines[2], lines[1]  # swap [WHY] and [WHERE] -> out of order
    out_of_order = "\n".join(lines)
    for bad in (box, missing, no_next, noeffort, out_of_order):
        with pytest.raises(AssertionError):
            _validate_terminal_report(bad)


# ---- SPEC_BRIEF51 / contract v1.4.1: precise next-prompt reporting ----
def _s15():
    text = CONTRACT.read_text()
    return text[text.index("## §15"):text.index("## §16")]


def _next_prompt_block():
    s15 = _s15()
    start = s15.index("`[NEXT PROMPT]` —")
    end = s15.index("12. The final line")
    return s15[start:end]


def test_schema_v141_minimal_widen():
    s = _schema()
    assert s["properties"]["contract_version"]["enum"] == [
        "1.3.0", "1.3.1", "1.3.2", "1.4.0", "1.4.1"]
    assert s["if"]["properties"]["contract_version"]["enum"] == ["1.4.0", "1.4.1"]
    assert "const" not in s["if"]["properties"]["contract_version"]
    assert s["if"]["required"] == ["contract_version"]
    assert set(s["required"]) == REQUIRED_KEYS
    assert len(s["required"]) == 11
    assert set(s["properties"]["decision_class"]["enum"]) == DECISION_CLASSES
    assert set(s["properties"]["next"]["items"]["properties"]["decision_class"]["enum"]) == DECISION_CLASSES
    assert s["additionalProperties"] is False
    # no new top-level key: [NEXT PROMPT] is presentation-only
    assert set(s["properties"]) == {
        "report_type", "contract_version", "decision_class", "opus_effort",
        "effort_justification", "what", "why", "who", "when", "where", "how",
        "next", "recommendation", "operator_action"}
    assert {"contract_version", "effort_justification"} <= set(s["then"]["required"])
    assert "milestone" in s["then"]["properties"]["when"]["required"]
    assert "reference_ledger" in s["then"]["properties"]["how"]["required"]


def _strict_report(version):
    return _report_v140(contract_version=version)


def test_real_schema_validates_exact_1_4_0_and_1_4_1_strict():
    validator = _real_validator()
    for v in ("1.4.0", "1.4.1"):
        r = _strict_report(v)
        assert r["contract_version"] == v
        assert validator.is_valid(r), v
        # strict fields are enforced for both versions
        for drop in (lambda x: x.pop("effort_justification"),
                     lambda x: x["when"].pop("milestone"),
                     lambda x: x["how"].pop("reference_ledger")):
            bad = _strict_report(v)
            drop(bad)
            assert not validator.is_valid(bad), v


_MISSING_VERSION = object()


def test_real_schema_rejects_bad_contract_versions_fail_closed():
    validator = _real_validator()
    cases = [_MISSING_VERSION, "", "1.4", "1.4.10", "1.5.0", "1.4.1 ", " 1.4.1", 141, 1.41, None, ["1.4.1"]]
    for bad in cases:
        r = _strict_report("1.4.1")
        if bad is _MISSING_VERSION:
            del r["contract_version"]
        else:
            r["contract_version"] = bad
        assert not validator.is_valid(r), repr(bad)


def test_next_prompt_named_placed_and_mandatory():
    s15 = _s15()
    assert "[NEXT PROMPT]" in s15
    assert s15.index("[OPERATOR ACTION]") < s15.index("[NEXT PROMPT]") < s15.index(
        "RECOMMENDED ORCHESTRATOR EFFORT")
    block = _next_prompt_block()
    assert "mandatory on every terminal report" in block
    assert "presentation-only" in block


def test_next_prompt_one_fenced_text_block_no_alternatives_120_words():
    block = _next_prompt_block()
    assert "exactly one fenced ```text block" in block
    assert "one prompt" in block
    assert "no alternatives" in block
    assert "no commentary inside the fence" in block
    assert "bare token `NONE`" in block
    assert "no fence" in block
    assert "at most 120 words" in block


def test_next_prompt_decision_class_matrix():
    block = _next_prompt_block()
    for cls in DECISION_CLASSES:
        assert f"- `{cls}` —" in block, cls
    assert "`NONE — loop continues autonomously`" in block
    sta = block[block.index("- `SAFE-TO-APPROVE` —"):block.index("- `NO-ACTION` —")]
    assert "one fenced ```text block" in sta
    assert "`where.pr`" in sta and "full head SHA" in sta and "`where.head_sha`" in sta
    na = block[block.index("- `NO-ACTION` —"):block.index("- `REVIEW-REQUIRED` —")]
    assert "authoritative roadmap or backlog item" in na
    assert "never fabricated" in na
    assert "`NONE` with the reason" in na
    rr = block[block.index("- `REVIEW-REQUIRED` —"):block.index("- `HOLD` —")]
    assert "one fenced ```text block" in rr
    assert "every required human choice and boundary" in rr
    assert "does not make it" in rr
    assert "does not pre-authorize a merge" in rr
    hold = block[block.index("- `HOLD` —"):]
    assert "never renders an override, bypass, force" in hold
    assert "`--admin`" in hold and "`--auto`" in hold
    assert "remediation step or the safe resume condition" in hold
    assert "render failure" in hold


def test_next_prompt_boundary_constraints_and_none_fallback():
    block = _next_prompt_block()
    for frag in ("derived only from `decision_class`, `operator_action`, `recommendation`, "
                 "`where.pr`, and `where.head_sha`",
                 "never invented",
                 "MUST NOT broaden scope beyond the approved brief",
                 "§6/§8 (live-use) authority",
                 "weaken or bypass a blocker or gate",
                 "introduce a new target",
                 "raw external-reference instructions",
                 "never upgrades or overrides a decision class",
                 "renders `NONE` with the reason instead"):
        assert frag in block, frag


def test_severity_section_is_readable_bullets_not_table():
    s15 = _s15()
    line = [l for l in s15.splitlines() if "[HOW TO DO FOR NEXT STEP BASED ON SEVERITY]" in l
            and l.startswith("8.")][0]
    assert "readable bullets" in line
    assert "one bullet per `next` entry" in line
    assert "`rank · severity · decision_class · depends_on · action`" in line
    assert "never a wide pipe table" in line
    assert "never box-drawing" in line
    assert "single physical line" not in line
    assert not [c for c in _BOX_CHARS if c in CONTRACT.read_text()]


def test_next_prompt_self_check():
    s15 = _s15()
    check = s15[s15.index("Pre-response self-check"):]
    assert "`[NEXT PROMPT]` is present and complete" in check
    for frag in ("truncated", "merged with another section",
                 "malformed (missing or incorrect fence)", "incomplete"):
        assert frag in check, frag


def test_version_discrimination_prose_covers_1_4_0_and_1_4_1():
    text = CONTRACT.read_text()
    s9 = text[text.index("## §9"):text.index("## §10")]
    assert "exactly `1.4.0` or exactly `1.4.1`" in s9
    assert "never loosened" in s9
    s15 = _s15()
    assert "exactly `1.4.0` or exactly `1.4.1`" in s15
    assert "never loosened" in s15
    s14 = text[text.index("## §14"):text.index("## §15")]
    assert "`[NEXT PROMPT]`" in s14
    assert "changes neither the five classes nor their meanings" in s14
