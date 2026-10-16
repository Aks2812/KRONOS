"""Pure canonical-key functions (SPEC_BRIEF4 §3.1), one per node type.

No graph access here at all — every function takes plain strings (the
caller, `runner.py`, is responsible for pulling those strings off the
graph/evidence store) and returns either a stable key string or `None`.
`None` means "this node can't produce a confident key" and the caller
must never merge it with anything (SPEC_BRIEF4 guardrail 6: conservative
bias, a missed merge is always safer than a false one).
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from urllib.parse import urlsplit

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# A purely-hex segment long enough that it's implausible as a literal
# path word (route segments like "v1"/"api"/"ab" never hit 16 hex chars) —
# conservative on purpose: SPEC_BRIEF4 §3.1 says "only clearly-variable
# segments; if unsure, keep the literal segment."
_LONG_HEX_RE = re.compile(r"^[0-9a-f]{16,}$")
_HOSTNAME_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$"
)


def _normalize_secret_material(material: str) -> str:
    """Strip whitespace, then strip one layer of surrounding quotes."""
    stripped = material.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in ("'", '"'):
        stripped = stripped[1:-1]
    return stripped


def canonical_key_for_secret(kind: str, material: str) -> str | None:
    """`f"{kind}:{sha256(normalized_material)}"` — same material + kind
    is the same secret regardless of which extractor/ingester found it.
    Hashed so the canonical key never re-exposes the secret value itself."""
    if not kind or not material:
        return None
    normalized = _normalize_secret_material(material)
    if not normalized:
        return None
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{kind}:{digest}"


def _is_variable_path_segment(segment: str) -> bool:
    if segment.isdigit():
        return True
    if _UUID_RE.match(segment):
        return True
    if _LONG_HEX_RE.match(segment):
        return True
    return False


def _path_template(path: str) -> str:
    segments = path.split("/")
    templated = [
        "{id}" if seg and _is_variable_path_segment(seg.lower()) else seg
        for seg in segments
    ]
    return "/".join(templated)


def canonical_key_for_api_endpoint(method: str, url: str) -> str | None:
    """`f"{method}:{scheme}://{host_lc}{path_template}"`. Conservative
    path templating: only a segment that's purely numeric, a UUID, or a
    long hex blob is replaced with `{id}` — anything else (an ordinary
    word, a short token) is kept literal, so `/users/1` and `/admin/1`
    stay distinct (different literal segments) while `/users/123` and
    `/users/456` collapse to the same template."""
    if not method or not url:
        return None
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{method.upper()}:{parsed.scheme.lower()}://{parsed.netloc.lower()}{_path_template(parsed.path)}"


def _host_shape(value: str) -> tuple[str, str] | None:
    try:
        ipaddress.IPv4Address(value)
        return "ipv4", value
    except ValueError:
        pass
    try:
        ipaddress.IPv6Address(value)
        return "ipv6", value
    except ValueError:
        pass
    candidate = value.lower()
    if candidate.endswith("."):
        candidate = candidate[:-1]
    if candidate and _HOSTNAME_RE.match(candidate):
        return "fqdn", candidate
    return None


def canonical_key_for_host(host_id: str) -> str | None:
    """`shape:value`, shape in {fqdn, ipv4, ipv6}. HOST node ids in this
    codebase ARE the hostname/IP (see `ingest.py`/tests), so the node's
    own id is the material to shape-detect — no separate "value" prop to
    read. Never collapses across shapes (SPEC_BRIEF4 guardrail 5): an
    FQDN and an IP that happen to be the same real host get different
    prefixes and therefore different keys, by construction."""
    if not host_id:
        return None
    shape = _host_shape(host_id)
    if shape is None:
        return None
    kind, value = shape
    return f"{kind}:{value}"


def canonical_key_for_mobile_app(bundle_id: str) -> str | None:
    """`bundle_id:value`. MOBILE_APP node ids ARE the bundle id (see
    `ingest.py`). Bundle ids are case-sensitive by spec, so unlike fqdn
    this is not lowercased."""
    if not bundle_id:
        return None
    value = bundle_id.strip()
    if not value:
        return None
    return f"bundle_id:{value}"


_DEFAULT_PORT_FOR_SCHEME = {"http": 80, "https": 443}


def canonical_key_for_web_endpoint(method: str, url: str) -> str | None:
    """`f"web:{method}:{scheme}://{host}[:{port}]{path}"` (SPEC_BRIEF9
    §4.1). Deliberately NO path templating (FORK-N DEFAULT): a web page
    is a document, not an API route — `/blog/post-1` and `/blog/post-2`
    are different pages with different content, so templating them the
    way `canonical_key_for_api_endpoint` templates `/users/123` would
    merge distinct attack surface and lose findings. The real duplicate
    case here is the same exact URL found by two sources (a crawler and
    a sitemap), not two ids under one route.

    Normalizes: lowercase scheme/host, drop a default port (80/http,
    443/https), strip a trailing slash (except the bare root), drop the
    query string and fragment entirely (both absent from the key by
    construction — `urlsplit` separates them out), uppercase the
    method."""
    if not method or not url:
        return None
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.hostname:
        return None
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    port = parsed.port
    if port is not None and port != _DEFAULT_PORT_FOR_SCHEME.get(scheme):
        host = f"{host}:{port}"
    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    return f"web:{method.upper()}:{scheme}://{host}{path}"


def canonical_key_for_parameter(name: str | None, param_type: str | None, parent_key: str | None) -> str | None:
    """A parameter has no identity of its own (SPEC_BRIEF9 §4.2) —
    `?id=` on `/users` is not `?id=` on `/products`. The key is
    **compound**: an identifier for the parent endpoint plus the
    normalized name and type. The caller (`reconcile/runner.py`'s
    `_group_parameters`) passes the parent endpoint's own RAW node id —
    deliberately NOT a freshly-recomputed
    `canonical_key_for_web_endpoint`/`canonical_key_for_api_endpoint`,
    because those are pure functions of (method, url) alone: two
    genuine endpoint duplicates always produce the same canonical key
    regardless of merge state, which would make SPEC_BRIEF9 §5's
    ordering rule untestable by construction. Using the raw id instead
    means `parent_key` only converges to one shared value across two
    duplicate parameters' parent edges once the endpoint merge has
    actually re-pointed them onto the survivor — see
    `tests/test_reconcile.py`'s ordering test. FORK-O DEFAULT:
    `parent_key is None` propagates straight to `None` rather than
    falling back to a parent-independent key — an unreconcilable parent
    (or one the caller couldn't resolve to exactly one endpoint) makes
    its parameters unreconcilable too; the alternative would merge
    parameters across unrelated endpoints, the worst failure mode
    available here (guardrail 7: conservative bias)."""
    if parent_key is None:
        return None
    if not name or not param_type:
        return None
    name_norm = name.strip()
    type_norm = param_type.strip().lower()
    if not name_norm or not type_norm:
        return None
    return f"param:{parent_key}:{name_norm}:{type_norm}"


def canonical_key_for_service(host_key: str | None, port: int | None, protocol: str | None) -> str | None:
    """Also compound (SPEC_BRIEF9 §4.3): port 443/tcp on host A is not
    port 443/tcp on host B, so the key is an identifier for the host
    plus port and protocol. The caller (`reconcile/runner.py`'s
    `_group_services`) passes the HOST's own RAW node id — same
    reasoning as `canonical_key_for_parameter`'s `parent_key`:
    `canonical_key_for_host` is a pure function of a host id's own
    text, so using it here would make the ordering rule untestable.
    `host_key is None` propagates to `None` (same FORK-O reasoning as
    the parameter key). Protocol is normalized to lowercase; a
    non-positive or missing port never produces a key (guardrail 7)."""
    if host_key is None:
        return None
    if not protocol:
        return None
    if port is None or isinstance(port, bool) or not isinstance(port, int) or port <= 0:
        return None
    protocol_norm = protocol.strip().lower()
    if not protocol_norm:
        return None
    return f"service:{host_key}:{port}:{protocol_norm}"


def canonical_key_for_finding(
    finding_class: str | None, affected_asset_id: str | None, location_sig: str | None
) -> str | None:
    """`f"{finding_class}:{affected_asset_id}:{location_sig}"` — only
    produces a key when all three parts are present (SPEC_BRIEF4 §3.1:
    "findings are the highest-cost false merge"). `FINDING`'s locked
    schema (schema.py) has no `finding_class`/`location_sig` columns
    today and no ingester populates them yet, so in practice this
    currently always returns `None` for every FINDING in the graph —
    which is exactly the safe, conservative default guardrail 6 asks
    for ("a node that can't produce a confident key... is never
    merged"), not a bug. The function exists, fully implemented, so a
    future ingester that DOES provide this data gets correct dedup for
    free rather than needing a second brief to add the formula."""
    if not finding_class or not affected_asset_id or not location_sig:
        return None
    return f"{finding_class}:{affected_asset_id}:{location_sig}"
