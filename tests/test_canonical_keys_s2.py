"""SPEC_BRIEF9 §8 test 4/5: the three new canonical-key functions —
positives, negatives, the normalization cases named in §4, and
compound-key `None` propagation.
"""

from __future__ import annotations

from kronos.reconcile.canonical import (
    canonical_key_for_parameter,
    canonical_key_for_service,
    canonical_key_for_web_endpoint,
)

# --- canonical_key_for_web_endpoint (§4.1) ---------------------------------


def test_web_endpoint_same_url_different_case_scheme_host_merges():
    a = canonical_key_for_web_endpoint("get", "HTTPS://Example.COM/blog/post-1")
    b = canonical_key_for_web_endpoint("GET", "https://example.com/blog/post-1")
    assert a == b


def test_web_endpoint_default_port_dropped():
    a = canonical_key_for_web_endpoint("GET", "https://example.com:443/blog/post-1")
    b = canonical_key_for_web_endpoint("GET", "https://example.com/blog/post-1")
    assert a == b
    c = canonical_key_for_web_endpoint("GET", "http://example.com:80/blog/post-1")
    d = canonical_key_for_web_endpoint("GET", "http://example.com/blog/post-1")
    assert c == d


def test_web_endpoint_non_default_port_kept():
    a = canonical_key_for_web_endpoint("GET", "https://example.com:8443/blog/post-1")
    b = canonical_key_for_web_endpoint("GET", "https://example.com/blog/post-1")
    assert a != b
    assert ":8443" in a


def test_web_endpoint_trailing_slash_stripped():
    a = canonical_key_for_web_endpoint("GET", "https://example.com/blog/post-1/")
    b = canonical_key_for_web_endpoint("GET", "https://example.com/blog/post-1")
    assert a == b


def test_web_endpoint_root_path_stays_root():
    a = canonical_key_for_web_endpoint("GET", "https://example.com/")
    b = canonical_key_for_web_endpoint("GET", "https://example.com")
    assert a == b
    assert a.endswith("/")


def test_web_endpoint_query_string_and_fragment_dropped():
    a = canonical_key_for_web_endpoint("GET", "https://example.com/blog/post-1?utm=x#top")
    b = canonical_key_for_web_endpoint("GET", "https://example.com/blog/post-1")
    assert a == b


def test_web_endpoint_never_collapses_distinct_pages():
    """SPEC_BRIEF9 §4.1: deliberately NO path templating — `/blog/post-1`
    and `/blog/post-2` are different pages, not two ids under one
    route, and must never collapse the way API_ENDPOINT's `/users/123`
    and `/users/456` do."""
    a = canonical_key_for_web_endpoint("GET", "https://example.com/blog/post-1")
    b = canonical_key_for_web_endpoint("GET", "https://example.com/blog/post-2")
    assert a != b


def test_web_endpoint_missing_scheme_or_host_is_none():
    assert canonical_key_for_web_endpoint("GET", "/just/a/path") is None
    assert canonical_key_for_web_endpoint("", "https://example.com/x") is None
    assert canonical_key_for_web_endpoint("GET", "") is None


# --- canonical_key_for_parameter (§4.2) ------------------------------------


def test_parameter_worked_example():
    key = canonical_key_for_parameter("id", "query", "web:GET:https://example.com/users")
    assert key == "param:web:GET:https://example.com/users:id:query"


def test_parameter_same_name_different_parent_never_collapses():
    a = canonical_key_for_parameter("id", "query", "parent:A")
    b = canonical_key_for_parameter("id", "query", "parent:B")
    assert a != b


def test_parameter_type_lowercased():
    a = canonical_key_for_parameter("id", "QUERY", "parent:A")
    b = canonical_key_for_parameter("id", "query", "parent:A")
    assert a == b


def test_parameter_none_parent_key_propagates_none():
    assert canonical_key_for_parameter("id", "query", None) is None


def test_parameter_missing_name_or_type_is_none():
    assert canonical_key_for_parameter("", "query", "parent:A") is None
    assert canonical_key_for_parameter("id", "", "parent:A") is None
    assert canonical_key_for_parameter(None, "query", "parent:A") is None


# --- canonical_key_for_service (§4.3) --------------------------------------


def test_service_worked_example():
    key = canonical_key_for_service("api.acme.example.com", 443, "tcp")
    assert key == "service:api.acme.example.com:443:tcp"


def test_service_same_port_different_host_never_collapses():
    a = canonical_key_for_service("host:A", 443, "tcp")
    b = canonical_key_for_service("host:B", 443, "tcp")
    assert a != b


def test_service_protocol_lowercased():
    a = canonical_key_for_service("host:A", 443, "TCP")
    b = canonical_key_for_service("host:A", 443, "tcp")
    assert a == b


def test_service_none_host_key_propagates_none():
    assert canonical_key_for_service(None, 443, "tcp") is None


def test_service_non_positive_or_missing_port_is_none():
    assert canonical_key_for_service("host:A", 0, "tcp") is None
    assert canonical_key_for_service("host:A", -1, "tcp") is None
    assert canonical_key_for_service("host:A", None, "tcp") is None


def test_service_missing_protocol_is_none():
    assert canonical_key_for_service("host:A", 443, "") is None
    assert canonical_key_for_service("host:A", 443, None) is None
