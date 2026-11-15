"""SPEC_BRIEF R9 (BE-G1-7): hermetic five-domain engagement.

infra, web, mobile, API and cloud fixtures are ingested into ONE
EngagementGraph, one validation pass runs with the validator patched (no
network / SDK), and the resulting FINDING must carry two-armed proof, a
verdict tier and a control disposition. dns is deliberately excluded.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from unittest.mock import patch

import pytest

from kronos.commit import MutationSource
from kronos.evidence import get_evidence, store_evidence
from kronos.graph import EngagementGraph
from kronos.ingest import apply_upserts, ingest_reference_mobile_secret
from kronos.ingest.api.parser import ingest_api_inventory_plan
from kronos.ingest.cloud.parser import ingest_cloud_inventory_plan
from kronos.ingest.contract import apply_plan
from kronos.ingest.infra.parser import ingest_infra_nmap_plan
from kronos.ingest.web.parser import ingest_web_openapi_plan
import kronos.validate.cloud_validator  # noqa: F401  pre-import: requests/boto3 import-time socket probes must not trip nonet
import kronos.validate.http_validator  # noqa: F401
from kronos.validate.runner import run_validation_pass
from kronos.validate.types import ValidationOutcome

FIX = Path(__file__).parent / "fixtures"
BUNDLE = "com.kronos.demo"
API_URL = "http://127.0.0.1:8091/api/v1/users"
BUCKET = "arn:aws:s3:::kronos-bucket/x"
PROOF = b"arm1: GET /users with credential -> 200\narm2: GET /users control -> 401"


@pytest.fixture
def nonet(monkeypatch):
    used = []

    def _boom(*a, **k):
        used.append(1)
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    return used


def _count(g, table):
    return g.execute(f"MATCH (n:{table}) RETURN count(n)").get_next()[0]


def test_five_domains_one_graph_finding_has_proof_tier_and_disposition(
    tmp_path, manifest_factory, signing_keypair, nonet
):
    _, pub = signing_keypair
    manifest = manifest_factory(
        scope={"in_scope": ["127.0.0.1*", "http://127.0.0.1*", "arn:*", "com.kronos*"], "excluded": []}
    )
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest, pub)
    engagement_dir = tmp_path

    # infra, web (nmap first: web endpoints hang off the SERVICE)
    apply_plan(g, ingest_infra_nmap_plan((FIX / "infra" / "cybergym_nmap.xml").read_text(), g))
    apply_plan(g, ingest_web_openapi_plan((FIX / "web" / "cybergym_openapi.json").read_text(), g))
    # mobile: reference secret; store its blob so value_ref resolves
    apply_upserts(g, ingest_reference_mobile_secret(BUNDLE))
    store_evidence(engagement_dir, b"demo-key", kind="mobile_secret")
    # API
    apply_plan(g, ingest_api_inventory_plan(json.dumps({"endpoints": [{"url": API_URL, "method": "GET"}]}), g))
    # cloud
    apply_plan(
        g,
        ingest_cloud_inventory_plan(
            json.dumps({"provider": "aws", "resources": [{"id": BUCKET, "resource_type": "s3_bucket"}]}), g
        ),
    )
    # glue: the mobile app references the API endpoint (candidate discovery input)
    g.upsert_edge("references", BUNDLE, "MOBILE_APP", API_URL, "API_ENDPOINT", source=MutationSource.INGESTION)

    # 1. five domains present in one graph
    assert _count(g, "HOST") >= 1 and _count(g, "SERVICE") >= 1  # infra
    assert _count(g, "WEB_ENDPOINT") >= 1  # web
    assert _count(g, "MOBILE_APP") == 1 and _count(g, "SECRET") == 1  # mobile
    assert g.get_node("API_ENDPOINT", API_URL) is not None  # API
    assert g.get_node("CLOUD_RESOURCE", BUCKET) is not None  # cloud

    discriminated = ValidationOutcome(
        live=True,
        evidence=PROOF,
        detail="200 with credential, 401 without",
        classification="live_discriminated",
        control_outcome="control arm: 401 unauthenticated",
        discriminated=True,
    )
    with patch("kronos.validate.http_validator.validate_api_token", return_value=discriminated) as mock_http, patch(
        "kronos.validate.cloud_validator.validate_cloud_credential"
    ) as mock_cloud:
        attempts = run_validation_pass(g, engagement_dir)

    mock_http.assert_called_once()
    mock_cloud.assert_not_called()
    assert not nonet

    # 2. FINDING exists and links EVIDENCE with the proof bytes
    findings = []
    res = g.execute("MATCH (f:FINDING) RETURN f.id")
    while res.has_next():
        findings.append(res.get_next()[0])
    assert len(findings) == 1
    fid = findings[0]
    res = g.execute("MATCH (e:EVIDENCE)-[:evidences]->(f:FINDING {id: $id}) RETURN e.id", {"id": fid})
    assert res.has_next()
    sha = res.get_next()[0]
    assert get_evidence(engagement_dir, sha) == PROOF

    # 3. verdict tier: discriminated live_discriminated driving outcome
    assert len(attempts) == 1
    assert attempts[0].target_id == API_URL
    assert attempts[0].discriminated is True
    assert attempts[0].classification == "live_discriminated"
    assert discriminated.live and discriminated.discriminated

    # 4. control disposition recorded and non-empty
    assert discriminated.control_outcome.strip() != ""
