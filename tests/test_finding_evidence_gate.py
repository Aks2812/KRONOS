"""SPEC_BRIEF35 AC1/AC2: structural lock on the G3 evidence gate.

Invariant (SPEC_BRIEF35 §4): any function that calls
advance_finding_status(..., "reachable"|"exploited") must, in the SAME
function, also call attach_evidence(..., target_type="finding").
Static analysis only: no graph, no network.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "kronos"
GATED_STATUSES = {"reachable", "exploited"}


def _call_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _is_gated_advance(call: ast.Call) -> bool:
    if _call_name(call) != "advance_finding_status":
        return False
    args = list(call.args) + [k.value for k in call.keywords]
    return any(isinstance(a, ast.Constant) and a.value in GATED_STATUSES for a in args)


def _is_finding_attach(call: ast.Call) -> bool:
    if _call_name(call) != "attach_evidence":
        return False
    for k in call.keywords:
        if k.arg == "target_type":
            return isinstance(k.value, ast.Constant) and k.value.value == "finding"
    return any(isinstance(a, ast.Constant) and a.value == "finding" for a in call.args)


def scan_source(source: str, label: str) -> tuple[set, set]:
    """Return (producers, violations) as sets of (label, function_name)."""
    producers: set = set()
    violations: set = set()
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        if any(_is_gated_advance(c) for c in calls):
            producers.add((label, fn.name))
            if not any(_is_finding_attach(c) for c in calls):
                violations.add((label, fn.name))
    return producers, violations


def scan_tree() -> tuple[set, set]:
    producers: set = set()
    violations: set = set()
    for path in sorted(SRC.rglob("*.py")):
        p, v = scan_source(path.read_text(), path.relative_to(SRC).as_posix())
        producers |= p
        violations |= v
    return producers, violations


# Pinned producers, each with a prose citation (SPEC_BRIEF35 §2). A NEW producer
# must be consciously added here.
EXPECTED_PRODUCER_EVIDENCE = {
    ("agent/dispatcher.py", "_step"): "advance dispatcher.py:173 gated by outcome.evidence not None; attach_evidence dispatcher.py:164-172",
    ("validate/web_validator.py", "record_web_finding"): "advance web_validator.py:75; attach_evidence web_validator.py:64-72 under outcome.live and outcome.evidence",
    ("validate/infra_validator.py", "record_infra_finding"): "advance infra_validator.py:74 after attach_evidence in same function",
    ("validate/invalidation.py", "record_secret_finding"): "advance invalidation.py:48 under evidence is not None; attach_evidence invalidation.py:36-44",
}


def test_AC1_invariant_holds_and_producer_set_pinned():
    producers, violations = scan_tree()
    assert violations == set(), violations
    assert all(EXPECTED_PRODUCER_EVIDENCE.values())
    assert producers == set(EXPECTED_PRODUCER_EVIDENCE), producers ^ set(EXPECTED_PRODUCER_EVIDENCE)


def test_AC2_checker_flags_synthetic_unguarded_advance():
    bad = (
        "def sneaky(x, y):\n"
        "    advance_finding_status(x, y, 'reachable')\n"
    )
    producers, violations = scan_source(bad, "synthetic.py")
    assert violations == {("synthetic.py", "sneaky")}
    assert producers == violations

    # attach with wrong target_type does not satisfy the gate
    wrong = (
        "def wrong(x, y):\n"
        "    attach_evidence(x, 'd', b'', kind='k', target_type='secret', target_id=y)\n"
        "    advance_finding_status(x, y, 'exploited')\n"
    )
    assert scan_source(wrong, "s.py")[1] == {("s.py", "wrong")}

    good = (
        "def ok(x, y):\n"
        "    attach_evidence(x, 'd', b'', kind='k', target_type='finding', target_id=y)\n"
        "    advance_finding_status(x, y, 'reachable')\n"
    )
    assert scan_source(good, "s.py")[1] == set()


def test_requires_revalidation_not_flagged():
    src = "def back(x, y):\n    advance_finding_status(x, y, 'requires_revalidation')\n"
    assert scan_source(src, "s.py") == (set(), set())
