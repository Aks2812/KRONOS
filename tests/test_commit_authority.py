"""SPEC_BRIEF31 sole-writer / commit-authority conformance tests (all `nonet`)."""

from __future__ import annotations

import inspect
import re
import socket
import subprocess
from pathlib import Path

import kuzu
import pytest

import kronos.commit as commit_mod
import kronos.graph as graph_mod
from kronos.commit import GraphMutationAuthority, MutationSource
from kronos.graph import EngagementGraph

ROOT = Path(__file__).parent.parent
B31_BASE = "a229b0d"
B33_BASE = "cf9293b"
B34_BASE = "7f5f46c"
B35_BASE = "a0395c5"
B36_BASE = "329194c"
RAILS_BASE = "445dbfc"
B30_SEAL = ("93fb05e", "a229b0d")  # BRIEF30 window, pre-sealed (AC7)
B31_SECTION_10 = {
    "tests/test_stop.py",
    "SPEC_BRIEF31.md",
    "src/kronos/commit.py",
    "src/kronos/graph.py",
    "src/kronos/lifecycle.py",
    "src/kronos/reconcile/merge.py",
    "tests/test_commit_authority.py",
    "tests/test_scope_guard.py",
}
B32_SECTION_10 = B31_SECTION_10 | {
    "src/kronos/evidence.py",
    "src/kronos/agent/dispatcher.py",
    "src/kronos/validate/invalidation.py",
    "src/kronos/validate/web_validator.py",
    "src/kronos/validate/infra_validator.py",
    "src/kronos/validate/runner.py",
    "src/kronos/ingest/__init__.py",
    "src/kronos/README_graph.md",
    "src/kronos/README_lifecycle.md",
    "SPEC_BRIEF32.md",
} | {
    f"tests/{n}.py"
    for n in (
        "test_commit_authority test_agent_commit test_lifecycle test_agent_live_executor "
        "test_validate_runner test_agent_dispatcher test_schema_graph test_invalidation "
        "test_ingest_contract test_negative_controls test_budget test_agent_executor test_ingest "
        "test_evidence test_reconcile test_mobile_ingest test_invariants test_web_ingest "
        "test_query test_validate_candidates"
    ).split()
}
B33_SECTION_10 = B32_SECTION_10 | {
    "src/kronos/agent/live_executor.py",
    "tests/test_web_validator.py",
    "tests/test_infra_validator.py",
    "SPEC_BRIEF33.md",
}
B34_SECTION_10 = B33_SECTION_10 | {"SPEC_BRIEF34.md"}
B35_SECTION_10 = B34_SECTION_10 | {"SPEC_BRIEF35.md", "tests/test_finding_evidence_gate.py"}
B36_SECTION_10 = B35_SECTION_10 | {"SPEC_BRIEF36.md", "src/kronos/commit.py", "tests/test_commit_severity.py"}
RAILS_SECTION_10 = B36_SECTION_10 | {
    ".claude/RAILS.md",
    ".claude/agents/kronos-builder.md",
    ".claude/agents/kronos-researcher.md",
    ".claude/agents/kronos-reviewer.md",
    ".claude/commands/kronos-continue.md",
    ".claude/hooks/brief-scope.sh",
    ".claude/settings.json",
    ".gitignore",
    "scripts/check_rails_drift.sh",
    "tests/test_brief_scope_hook.py",
    "tests/test_commit_authority.py",
}
WRITE_VERB = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DROP|ALTER|COPY|REMOVE|DETACH)\b", re.I)


@pytest.fixture
def nonet(monkeypatch):
    used = []

    def _boom(*a, **k):
        used.append(1)
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    return used


@pytest.fixture
def g(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    return EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_factory(), pub)


def _count(g, t="HOST"):
    return g.execute(f"MATCH (n:{t}) RETURN count(n)").get_next()[0]


# 1 / 8 (AC1, AC8)
def test_public_read_api_cannot_write(g, nonet):
    with pytest.raises(RuntimeError):
        g.execute("CREATE (:HOST {id: 'host:x.acme.example.com'})")
    assert _count(g) == 0
    assert not nonet


def test_read_api_write_fails_at_driver(g, nonet):
    with pytest.raises(RuntimeError, match="read-only"):
        g.execute("CREATE (:HOST {id: 'h'})")
    assert not nonet


# 3 adversarial (AC1/AC3)
@pytest.mark.parametrize(
    "q",
    [
        "/* MATCH */ CREATE (:HOST {id: 'a'})",
        "// comment\nCREATE (:HOST {id: 'a'})",
        "MATCH (n:HOST) /* RETURN n */ SET n.source = 'x'",
        "MATCH (n:HOST) // RETURN\nSET n.source = 'x'",
        "MATCH (n:HOST) SET n.source = 'x' RETURN n",
        "MERGE (n:HOST {id: 'a'})",
        "MATCH (n:HOST) DELETE n",
        "MATCH (n:HOST) DETACH DELETE n",
        "match (n:HOST) return n; CREATE (:HOST {id: 'a'})",
        "MATCH (n:HOST) RETURN n UNION ALL CREATE (:HOST {id: 'a'})",
    ],
)
def test_disguised_writes_via_read_api_raise(g, q, nonet):
    g.upsert_node("HOST", "host:a.acme.example.com", {"source": "t"}, source=MutationSource.INGESTION)
    with pytest.raises(Exception):
        g.execute(q)
    assert _count(g) == 1
    assert g.get_node("HOST", "host:a.acme.example.com")["source"] == "t"
    assert not nonet


def test_authority_has_no_raw_exec_and_conn_private(g, nonet):
    public = [n for n in dir(GraphMutationAuthority) if not n.startswith("_")]
    assert set(public) == {
        "create_or_update_node", "upsert_edge", "set_secret_lifecycle",
        "set_finding_lifecycle", "tombstone", "delete_loser_edges",
    }
    for name in public:
        for p in inspect.signature(getattr(GraphMutationAuthority, name)).parameters:
            assert p not in {"query", "cypher", "sql", "statement", "raw"}
    inst = g._authority
    assert not hasattr(inst, "conn") and not hasattr(inst, "execute")
    assert not hasattr(g, "conn") and not hasattr(g, "db")
    with pytest.raises(ValueError):  # source identity mandatory and typed
        inst.create_or_update_node("HOST", "host:b.acme.example.com", {}, None, "ingestion")
    assert not nonet


def test_authority_cypher_injection_in_value_and_names_is_inert(g, nonet):
    g.upsert_node("HOST", "host:a.acme.example.com", {"source": "x' SET n.in_scope = false //"}, source=MutationSource.INGESTION)
    assert g.get_node("HOST", "host:a.acme.example.com")["source"] == "x' SET n.in_scope = false //"
    with pytest.raises(ValueError):
        g.upsert_node("HOST", "host:a.acme.example.com", {"source = 'x' //": "y"}, source=MutationSource.INGESTION)
    with pytest.raises(ValueError):
        g.upsert_node("HOST:X) DETACH DELETE (n", "id", {}, source=MutationSource.INGESTION)
    with pytest.raises(ValueError):
        g.upsert_edge("hosts) DELETE r //", "a", "HOST", "b", "SERVICE", source=MutationSource.INGESTION)
    assert not nonet


# 4 (AC3)
def test_authority_rejects_unknown_field(g, nonet):
    for bad in ("in_scope", "confidence", "scope_note", "merged_into", "id", "nonexistent_col"):
        with pytest.raises(ValueError):
            g._authority.create_or_update_node(
                "HOST", "host:a.acme.example.com", {bad: 1}, None, MutationSource.INGESTION
            )
    with pytest.raises(ValueError):
        g._authority.upsert_edge("hosts", "a", "HOST", "b", "SERVICE", {"evil": 1}, MutationSource.INGESTION)
    assert not nonet


# 2 (AC2)
def test_no_raw_execute_write_in_src(nonet):
    offenders = []
    for path in (ROOT / "src/kronos").rglob("*.py"):
        text = path.read_text()
        for m in re.finditer(r"\b(?:graph|engagement|self|conn|_conn)\.execute\(", text):
            # statement text: from the call to the matching close paren (bounded window)
            window = text[m.end(): m.end() + 600]
            depth, end = 1, 0
            for i, ch in enumerate(window):
                depth += ch == "("
                depth -= ch == ")"
                if depth == 0:
                    end = i
                    break
            stmt = window[:end]
            if path.name == "commit.py":
                continue  # the sanctioned authority (and its CHECKPOINT)
            if WRITE_VERB.search(re.sub(r"\{[^}]*\}", "", " ".join(re.findall(r'"([^"]*)"', stmt)))):
                offenders.append(f"{path.relative_to(ROOT)}:{text[:m.start()].count(chr(10)) + 1}")
    assert offenders == []
    assert not nonet


def test_write_cypher_only_in_commit_module(nonet):
    # conn.execute is reachable only in commit.py and graph.py (read handle) / schema.py (DDL).
    for path in (ROOT / "src/kronos").rglob("*.py"):
        if path.name in {"commit.py", "graph.py", "schema.py"}:
            continue
        assert not re.search(r"\b_?conn\.execute\(", path.read_text()), path
    assert not nonet


# 5 (AC8)
def test_fresh_read_batch_sees_latest_commit(g, nonet):
    assert _count(g) == 0
    g._authority.create_or_update_node(
        "HOST", "host:a.acme.example.com", {"source": "t"}, None, MutationSource.INGESTION
    )
    assert _count(g) == 1
    g._authority.create_or_update_node(
        "HOST", "host:b.acme.example.com", {"source": "t"}, None, MutationSource.INGESTION
    )
    assert _count(g) == 2
    assert not nonet


# 6 (AC9)
def test_read_handle_closes_on_success_and_exception(g, monkeypatch, nonet):
    opened = []
    real_db = kuzu.Database

    class Spy(real_db):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            opened.append(self)
            self.closed = False

        def close(self):
            self.closed = True
            super().close()

    monkeypatch.setattr(graph_mod.kuzu, "Database", Spy)
    g.execute("MATCH (n:HOST) RETURN count(n)")
    with pytest.raises(RuntimeError):
        g.execute("CREATE (:HOST {id: 'x'})")
    with pytest.raises(Exception):
        g.execute("THIS IS NOT CYPHER")
    assert len(opened) == 3
    assert all(d.closed for d in opened)
    # none cached: the graph holds no read-only handle
    assert not any(isinstance(v, real_db) and v not in (g._db,) for v in vars(g).values())
    assert not nonet


# 7 (AC6)
def test_executor_performs_no_graph_write(nonet):
    src = (ROOT / "src/kronos/agent/executor.py").read_text()
    assert "graph" not in src.lower().replace("engagementgraph", "")
    assert not re.search(r"upsert_|_authority|GraphMutationAuthority|\.execute\(\s*[\"']", src)
    assert not nonet


# 8 (AC7)
def test_B31_Q_scope_audit(nonet):
    def names(rng):
        return subprocess.run(
            ["git", "diff", "--name-only", rng], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()

    # BRIEF31/32 window sealed to its merge SHA (B33 AC6), not HEAD.
    assert set(names(f"{B31_BASE}..{B33_BASE}")) <= B32_SECTION_10, set(names(f"{B31_BASE}..{B33_BASE}")) - B32_SECTION_10
    assert set(names(f"{B33_BASE}..{B34_BASE}")) <= B33_SECTION_10, set(names(f"{B33_BASE}..{B34_BASE}")) - B33_SECTION_10
    assert set(names(f"{B34_BASE}..{B35_BASE}")) <= B34_SECTION_10, set(names(f"{B34_BASE}..{B35_BASE}")) - B34_SECTION_10
    assert set(names(f"{B35_BASE}..{B36_BASE}")) <= B35_SECTION_10, set(names(f"{B35_BASE}..{B36_BASE}")) - B35_SECTION_10
    assert set(names(f"{B36_BASE}..{RAILS_BASE}")) <= B36_SECTION_10, set(names(f"{B36_BASE}..{RAILS_BASE}")) - B36_SECTION_10
    assert set(names(f"{RAILS_BASE}..HEAD")) <= RAILS_SECTION_10, set(names(f"{RAILS_BASE}..HEAD")) - RAILS_SECTION_10
    # BRIEF30 seal: its own window ends at its merge commit, not HEAD.
    assert "src/kronos/commit.py" not in names(f"{B30_SEAL[0]}..{B30_SEAL[1]}")
    assert not nonet


# ---- SPEC_BRIEF32: required source identity on write facades ----
def _spy(g, monkeypatch):
    seen = []
    for name in ("create_or_update_node", "upsert_edge"):
        orig = getattr(g._authority, name)

        def wrap(*a, _o=orig, **k):
            seen.append(a[-1] if a and isinstance(a[-1], MutationSource) else k.get("source"))
            return _o(*a, **k)

        monkeypatch.setattr(g._authority, name, wrap)
    return seen


# B32 AC1: omission raises on all three signatures (section 3 item 1)
def test_B32_source_required_keyword_only(g, tmp_path, nonet):
    from kronos.evidence import attach_evidence

    for fn in (g.upsert_node, g.upsert_edge, attach_evidence):
        p = inspect.signature(fn).parameters["source"]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        g.upsert_node("HOST", "h1", {})
    with pytest.raises(TypeError):
        g.upsert_edge("hosts", "a", "HOST", "b", "SERVICE")
    with pytest.raises(TypeError):
        attach_evidence(g, tmp_path, b"x", "k", "finding", "f")
    assert not nonet


# B32 AC2: BOOTSTRAP exists (section 3 item 2)
def test_B32_bootstrap_member_value():
    assert MutationSource.BOOTSTRAP.value == "bootstrap"


# B32 AC2/AC3: init_engagement -> BOOTSTRAP (section 3 item 2)
def test_B32_init_engagement_attributes_bootstrap(tmp_path, manifest_factory, signing_keypair, monkeypatch, nonet):
    _, pub = signing_keypair
    seen = []
    orig = commit_mod.GraphMutationAuthority.create_or_update_node

    def wrap(self, *a, **k):
        seen.append((a[0], a[-1]))
        return orig(self, *a, **k)

    monkeypatch.setattr(commit_mod.GraphMutationAuthority, "create_or_update_node", wrap)
    EngagementGraph.init_engagement(tmp_path / "b.kz", manifest_factory(), pub)
    assert seen == [("ENGAGEMENT", MutationSource.BOOTSTRAP)]
    assert not nonet


# B32 AC3/AC4: live per-path attribution (section 3 item 3); each cell cites its path
def test_B32_per_path_attribution_live(g, tmp_path, monkeypatch, nonet):
    from kronos.agent.dispatcher import _commit as dispatcher_commit
    from kronos.validate.invalidation import record_secret_finding
    from kronos.reconcile.merge import _carry_over_edges

    seen = _spy(g, monkeypatch)
    g.upsert_node("SECRET", "s1", {}, source=MutationSource.INGESTION)
    g.upsert_node("HOST", "h1", {}, source=MutationSource.INGESTION)
    seen.clear()

    class _I:  # dispatcher _commit reads kind/target_id/rationale (agent/dispatcher.py)
        kind, target_id, rationale = "k", "s1", "r"

    class _V:
        target_type = "SECRET"

    dispatcher_commit(g, _I, _V)
    assert seen and set(seen) == {MutationSource.DISPATCHER}  # dispatcher -> DISPATCHER

    seen.clear()

    class _C:
        id, type = "h1", "HOST"

    record_secret_finding(g, "s1", _C)
    assert seen and set(seen) == {MutationSource.VALIDATION}  # validate/invalidation -> VALIDATION

    seen.clear()
    g.upsert_node("SECRET", "s2", {}, source=MutationSource.INGESTION)
    g.upsert_edge("authenticates_to", "s2", "SECRET", "h1", "HOST", source=MutationSource.INGESTION)
    seen.clear()
    _carry_over_edges(g, "SECRET", "s2", "s1")
    assert seen and set(seen) == {MutationSource.RECONCILIATION}  # reconcile carry-over -> RECONCILIATION
    assert not nonet


# B32 AC3 (reviewer F-1): LIVE capture of the source the authority really receives
# from the REAL production ingest path (ingest/__init__.py apply_upserts) - nothing
# test-supplied; section 3 item 3.
def test_B32_ingest_path_live_emits_INGESTION(g, monkeypatch, nonet):
    from kronos.ingest import EdgeUpsert, NodeUpsert, apply_upserts

    seen = _spy(g, monkeypatch)
    apply_upserts(
        g,
        [
            NodeUpsert("HOST", "host:i.acme.example.com", {"source": "t"}),
            NodeUpsert("SERVICE", "svc:i", {"source": "t"}),
            EdgeUpsert("hosts", "host:i.acme.example.com", "svc:i"),
        ],
    )
    assert len(seen) == 3 and set(seen) == {MutationSource.INGESTION}
    assert not nonet


# B32 AC3 (reviewer F-1): LIVE VALIDATION from the real web / infra validator record paths
def test_B32_validator_paths_live_emit_VALIDATION(g, monkeypatch, nonet):
    from kronos.validate.infra_validator import record_infra_finding
    from kronos.validate.web_validator import record_web_finding

    g.upsert_node("WEB_ENDPOINT", "web:v", {"source": "t"}, source=MutationSource.INGESTION)
    g.upsert_node("SERVICE", "svc:v", {"source": "t"}, source=MutationSource.INGESTION)
    seen = _spy(g, monkeypatch)
    record_web_finding(g, "web:v", None)
    assert len(seen) == 2 and set(seen) == {MutationSource.VALIDATION}  # web_validator
    seen.clear()
    record_infra_finding(g, "svc:v", None)
    assert len(seen) == 2 and set(seen) == {MutationSource.VALIDATION}  # infra_validator
    assert not nonet


def _src(path):
    return (ROOT / path).read_text()


@pytest.mark.parametrize(
    "path,member",
    [
        ("src/kronos/agent/dispatcher.py", "DISPATCHER"),  # section 3 item 3 / item 4
        ("src/kronos/validate/invalidation.py", "VALIDATION"),  # section 3 item 3 / item 4
        ("src/kronos/validate/web_validator.py", "VALIDATION"),  # section 3 item 3
        ("src/kronos/validate/infra_validator.py", "VALIDATION"),  # section 3 item 3
        ("src/kronos/validate/runner.py", "VALIDATION"),  # section 3 item 3 / item 4
        ("src/kronos/ingest/__init__.py", "INGESTION"),  # section 3 item 3
        ("src/kronos/reconcile/merge.py", "RECONCILIATION"),  # section 3 item 3 (_carry_over_edges)
        ("src/kronos/graph.py", "BOOTSTRAP"),  # section 3 item 3 (init_engagement)
    ],
)
def test_B32_path_passes_its_enum(path, member, nonet):
    # AC3 + AC4: DISPATCHER / VALIDATION are live (passed by production paths)
    assert f"source=MutationSource.{member}" in _src(path)


def test_B32_no_unattributed_call_sites(nonet):
    # every facade / attach_evidence call in production passes source=
    for path in (
        "agent/dispatcher.py", "validate/invalidation.py", "validate/web_validator.py",
        "validate/infra_validator.py", "validate/runner.py", "ingest/__init__.py",
        "reconcile/merge.py", "evidence.py",
    ):
        text = _src(f"src/kronos/{path}")
        for m in re.finditer(r"(?<!def )\b(upsert_node|upsert_edge|attach_evidence)\(\s*[^)\s]", text):
            depth, i = 1, m.end() - 1
            while depth:
                depth += {"(": 1, ")": -1}.get(text[i], 0)
                i += 1
            assert "source=" in text[m.end():i], (path, m.group(1))


# B32 AC5: facade bodies carry no literal INGESTION
def test_B32_facade_bodies_no_literal_ingestion(nonet):
    for fn in (EngagementGraph.upsert_node, EngagementGraph.upsert_edge):
        assert "MutationSource.INGESTION" not in inspect.getsource(fn)


# B32 AC6: F1 docs no longer claim execute() is write-capable
def test_B32_docs_execute_read_only(nonet):
    g_doc = " ".join(_src("src/kronos/README_graph.md").split())
    l_doc = " ".join(_src("src/kronos/README_lifecycle.md").split())
    assert "use internally to write" not in g_doc
    assert "real, unrestricted Cypher" not in l_doc
    assert "write `status`/ `confidence`/`scope_note` directly" not in l_doc
    assert "read-only" in g_doc and "read-only" in l_doc


# B32 F3: orphan constant removed from merge.py
def test_B32_orphan_status_bearing_removed(nonet):
    assert "_STATUS_BEARING_TYPES" not in _src("src/kronos/reconcile/merge.py")
