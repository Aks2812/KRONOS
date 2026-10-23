"""SPEC_BRIEF17 §8 criteria A-E (reviewer contract). Expected values derive from the brief's prose."""

from __future__ import annotations

import socket

import pytest

from kronos.agent import (
    COMMIT_STATUS,
    LEGAL_TARGET_TYPES,
    MockReviewer,
    ReviewVerdict,
    ReviewViolation,
    validate_verdict,
)

EIGHT = {"HOST", "SERVICE", "WEB_ENDPOINT", "API_ENDPOINT", "CLOUD_RESOURCE", "MOBILE_APP", "MOBILE_COMPONENT", "SECRET"}


@pytest.mark.parametrize("t", sorted(EIGHT))
def test_A_approved_happy_path(t):  # §8 A
    assert validate_verdict(ReviewVerdict(approved=True, target_type=t, status="hypothesis")) is None


@pytest.mark.parametrize("status", ["reachable", "exploited", "reported", "discarded", "validated", ""])
def test_B_no_upgrade_rail(status):  # §8 B
    with pytest.raises(ReviewViolation):
        validate_verdict(ReviewVerdict(approved=True, target_type="HOST", status=status))


def test_B_commit_status_constant():  # §8 B
    assert COMMIT_STATUS == "hypothesis"


@pytest.mark.parametrize("t", ["IDENTITY", "PARAMETER", "ENGAGEMENT", "NOT_A_TYPE"])
def test_C_illegal_target_type(t):  # §8 C
    with pytest.raises(ReviewViolation):
        validate_verdict(ReviewVerdict(approved=True, target_type=t, status="hypothesis"))


def test_C_legal_set_is_the_eight():  # §8 C
    assert LEGAL_TARGET_TYPES == EIGHT


def test_C_non_verdict_rejected():  # §2a
    with pytest.raises(ReviewViolation):
        validate_verdict({"approved": True})  # type: ignore[arg-type]


def test_D_rejected_always_valid():  # §8 D
    assert validate_verdict(ReviewVerdict(approved=False, target_type="x", status="anything")) is None


def test_E_mock_determinism(monkeypatch):  # §8 E
    def _boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    v1 = ReviewVerdict(True, "HOST", "hypothesis")
    v2 = ReviewVerdict(False, "HOST", "hypothesis")
    m = MockReviewer([v1, v2])
    assert m.review(None) is v1  # type: ignore[arg-type]
    assert m.review(None) is v2  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        m.review(None)  # type: ignore[arg-type]
