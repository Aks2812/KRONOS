import hashlib
from pathlib import Path

import pytest

from kronos.evidence import attach_evidence, get_evidence, store_evidence


def test_store_evidence_is_content_addressed(tmp_path):
    info = store_evidence(tmp_path, b"hello world", "screenshot")
    assert info["sha256"] == hashlib.sha256(b"hello world").hexdigest()
    assert Path(info["blob_path"]).read_bytes() == b"hello world"


def test_store_evidence_idempotent_same_content(tmp_path):
    info1 = store_evidence(tmp_path, b"hello", "log")
    info2 = store_evidence(tmp_path, b"hello", "log")
    assert info1["sha256"] == info2["sha256"]


def test_get_evidence_roundtrip(tmp_path):
    info = store_evidence(tmp_path, b"payload", "pcap")
    assert get_evidence(tmp_path, info["sha256"]) == b"payload"


def test_get_evidence_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        get_evidence(tmp_path, "0" * 64)


def test_attach_evidence_creates_node_and_edge(engagement_graph, tmp_path):
    g = engagement_graph
    g.upsert_node("FINDING", "f1", {"title": "t", "severity": "high", "status": "hypothesis"})
    sha = attach_evidence(g, tmp_path, b"poc output", "poc", "finding", "f1")
    r = g.execute("MATCH (e:EVIDENCE)-[:evidences]->(f:FINDING {id:'f1'}) RETURN e.sha256")
    assert r.get_next()[0] == sha
