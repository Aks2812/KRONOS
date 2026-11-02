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
    g.upsert_node("HOST", "host:a.acme.example.com", {"source": "t"})
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
    g.upsert_node("HOST", "host:a.acme.example.com", {"source": "x' SET n.in_scope = false //"})
    assert g.get_node("HOST", "host:a.acme.example.com")["source"] == "x' SET n.in_scope = false //"
    with pytest.raises(ValueError):
        g.upsert_node("HOST", "host:a.acme.example.com", {"source = 'x' //": "y"})
    with pytest.raises(ValueError):
        g.upsert_node("HOST:X) DETACH DELETE (n", "id", {})
    with pytest.raises(ValueError):
        g.upsert_edge("hosts) DELETE r //", "a", "HOST", "b", "SERVICE")
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

    assert set(names(f"{B31_BASE}..HEAD")) <= B31_SECTION_10, set(names(f"{B31_BASE}..HEAD")) - B31_SECTION_10
    # BRIEF30 seal: its own window ends at its merge commit, not HEAD.
    assert "src/kronos/commit.py" not in names(f"{B30_SEAL[0]}..{B30_SEAL[1]}")
    assert not nonet
