"""SPEC_BRIEF36 AC1-AC3: severity enum chokepoint in create_or_update_node (all `nonet`)."""

from __future__ import annotations

import socket

import pytest

from kronos.commit import SEVERITY_LEVELS, MutationSource
from kronos.graph import EngagementGraph

FID = "finding:sev-1"


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


def _count(g, t):
    return g.execute(f"MATCH (n:{t}) RETURN count(n)").get_next()[0]


def test_ac1_illegal_severity_raises_and_writes_nothing(g, nonet):
    with pytest.raises(ValueError, match="severity 'urgent' not in"):
        g.upsert_node(
            "FINDING", FID, {"source": "t", "title": "x", "severity": "urgent"},
            source=MutationSource.INGESTION,
        )
    assert _count(g, "FINDING") == 0
    assert not nonet


@pytest.mark.parametrize("level", sorted(SEVERITY_LEVELS))
def test_ac2_legal_levels_accepted(g, level, nonet):
    assert SEVERITY_LEVELS == {"info", "low", "medium", "high", "critical"}
    g.upsert_node(
        "FINDING", FID, {"source": "t", "title": "x", "severity": level},
        source=MutationSource.INGESTION,
    )
    assert g.get_node("FINDING", FID)["severity"] == level
    assert not nonet


def test_ac3_info_ok_and_non_severity_type_unaffected(g, nonet):
    g.upsert_node(
        "FINDING", FID, {"source": "t", "title": "x", "severity": "info"},
        source=MutationSource.INGESTION,
    )
    assert g.get_node("FINDING", FID)["severity"] == "info"
    g.upsert_node("HOST", "host:a.acme.example.com", {"source": "t"}, source=MutationSource.INGESTION)
    assert _count(g, "HOST") == 1
    assert not nonet
