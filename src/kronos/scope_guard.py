"""The ONLY scope-authorization mechanism (SPEC.md "SCOPE GUARD").

`scope_guard(target, manifest)` stamps `in_scope` on every node at
creation: excluded globs first (hard deny), then in_scope globs (allow),
default DENY. No other code path is allowed to set `in_scope` directly.

SPEC_BRIEF10 (FORK-2): the matcher is now shape-aware. A flat untyped
`fnmatch` over the raw string treated an IP, a CIDR, a URL, a
`host:port`, and a bundle id identically, which both under-matched
exclusions (F1-F3: an excluded `10.0.0.5` did not deny
`https://10.0.0.5/admin`) and over-matched allows (F4-F5: a loose glob
written to route around the under-matching could itself be matched by
attacker-controlled strings). The fix dispatches on the *target's*
apparent shape (`classify_target`) and compares like to like: an
address-shaped pattern only ever sees address identities, a
hostname-shaped pattern only ever sees the target's host component
(never its path/query/fragment/userinfo -- FORK-S), and a `host:port`
pattern matches both the bare form and the URL form of that exact host
and port (F8). The signed-manifest schema is untouched: patterns stay a
flat, untyped string list (issue #2 option (b) -- typed-prefix entries
-- was explicitly rejected); all of the new intelligence lives in how a
string is *interpreted* here, never in how it is stored.

§1.1 (operator-ratified, governing) is the authoritative reading of
scope intent this module implements:

1. A hostname pattern `*.acme.com` authorizes DNS subdomains, never the
   apex `acme.com` -- an operator wanting the apex adds it as its own
   entry.
2. Standard ports are 80 for http and 443 for https. A hostname pattern
   authorizes the bare host, the host at a standard port, and
   http/https URLs on those ports, implicit or explicit.
3. Path and query never affect authorization once the host is
   authorized -- scope is host-level, not path-level.
4. A nonstandard port needs an explicit `host:port` entry, which then
   authorizes both the bare `host:port` and its URL form (F8).
5. No authorization transfer via URL content: only the URL's host
   component (and effective port) are ever consulted (FORK-S). A
   hostname in a path, query, fragment, or userinfo authorizes nothing.
6. Allow is narrow; deny is broad, deliberately asymmetric: an excluded
   host is excluded on every port, scheme, path, and representation,
   regardless of how the exclusion entry itself is written.
7. A CIDR or bare-IP pattern authorizes ALL ports on a matching address
   (operator-ratified 2026-10-16, resolving §8.5) -- an IP range in a
   signed SOW is network-level authorization, not web-tier intent, so
   it does not inherit the hostname rule's standard-port limit.
   Address-shaped and hostname-shaped allow semantics are NOT unified;
   that asymmetry is the specification, not an inconsistency.

SPEC_BRIEF10.1 (amends PR #12, pre-merge): the trailing-glob boundary
rule. PR #12 (per the rules above) still matched a trailing `*` on a
host-shaped pattern (`api.acme.com*`, `localhost*`, a `host*` in a
literal URL pattern) by raw character prefix, so `api.acme.com*`
authorized the attacker-registerable `api.acme.com.attacker.net` --
the exact class SPEC_BRIEF10 exists to close, surviving in the one
pattern shape CyberGym's own signed manifest actually uses. §1.1
below (operator-ratified) is the fix; it governs every trailing-`*`
match in this module from here on.

§1.1 The boundary rule (SPEC_BRIEF10.1, governing). A trailing `*` on
a hostname/URL/IP-shaped target expands only at a delimiter boundary:
`:` (port), `/` (path), or end-of-string. It never expands across a
`.` into another DNS label, and never mid-label. So `api.acme.com*`
covers `api.acme.com`, `api.acme.com:<port>`,
`https://api.acme.com/...` and `https://api.acme.com:<port>/...` --
and nothing else; `api.acme.com.attacker.net` crosses a label and
`api.acme.com-evil.net` expands mid-label, so both deny.

§1.2 Port semantics for a trailing `*` (SPEC_BRIEF10.1, Option A,
operator-ratified DEFAULT). A trailing `*` after a complete host
means "this host, any port, any path" -- deliberately wider than a
bare host entry (§1.1 rule 2 above, standard ports only): the operator
gets all-ports authorization by typing `*`, never by accident, and it
is bounded to that one host by the boundary rule. This is what
preserves CyberGym's `localhost*`/`127.0.0.1*`/`http://localhost*`
entries (covering its nonstandard 8091/4566 ports) with no manifest
edit. A bare `api.acme.com` still denies `:8443` per §1.1 rule 4,
unchanged -- the widening is an explicit act, the trailing `*` itself.

§1.3 Buckets and ARNs stay distinct from hostnames (SPEC_BRIEF10.1).
`kronos-cybergym-*` must keep matching `kronos-cybergym-general-secrets`
-- mid-label expansion, correct for a bucket name, forbidden for a
hostname. So the boundary rule is selected by the *target's* shape,
not the pattern's text: a hostname/URL/IP-shaped target gets the
boundary rule above; a `bucket_name`- or `arn`-shaped target keeps
free glob expansion, exactly as before this amendment. A bucket/ARN
pattern can therefore never authorize a hostname-shaped target (its
glob expansion is never even attempted against one -- see
`classify_target`'s new `bucket_name`/`arn` shapes below), and a
hostname pattern still never authorizes a bundle id (SPEC_BRIEF10
§5.7, unaffected).

SPEC_BRIEF10.4 (FORK-2's closing piece) fixes the two real defects seq
5 independent review found in SPEC_BRIEF10.3's table (D1/D2 -- see
DECISIONS.md and README_scope.md for the full account) and finishes
H3's deny-broad rule for a path-bearing URL exclusion pattern:

§1.1 `scope_key` is gated by its own shape, independent of `node_type`.
A `scope_key` is an explicit, operator- or ingester-supplied assertion
of a node's in-scope network identity -- it is not an id, so
`NODE_TYPE_SHAPES`'s id-shape table does not apply to it at all.
`is_in_scope` now takes a second required keyword argument,
`target_kind` (`"id"` or `"scope_key"`), stating which string it was
handed; an unrecognised value denies, same as every other fail-closed
case here. Fail-closed is unaffected either way: an unrecognised,
empty, or `None` `node_type` still denies before any pattern is even
consulted, whether or not a `scope_key` is present. `graph.py:140`'s
`scope_key or id` precedence is unchanged (§1.5) -- this module is
simply told, via the new kwarg, which of the two strings it is
looking at.

§1.2 No row of `NODE_TYPE_SHAPES` may be assigned by analogy; no
evidence means an empty family. This generalises 10.3's own FORK-W
rule (already applied to IDENTITY/TECHNOLOGY/FINDING) to every row
without exception. `WEB_ENDPOINT` therefore becomes `frozenset()`:
there is no production WEB_ENDPOINT ingester, its only documented key
(`canonical_key_for_web_endpoint`) is a *merge* key
(`reconcile/runner.py:84`), never a node id, and that key classifies
as `"unknown"`, not `"url"` -- so `{"url"}` described a shape nothing
produces. `SECRET`'s 10.3 row (`{"host"}`) existed only to make the
scope_key path work before this module could tell scope_key and id
apart; now that it can (§1.1), that justification is gone, and
`SECRET`'s own id (sha256-derived) matches no shape family this
module has, so it too becomes `frozenset()` (FORK-Y) -- every
production SECRET call site sets `scope_key=bundle_id` regardless, so
this never denies a real SECRET in practice.

§1.3 (closing 10.3's own H3 fix) An exclusion is shape-blind, port-
blind, scheme-blind *and* path-blind -- including when the pattern
itself is a URL that carries a path. `excluded =
["http://localhost:8091/internal/*"]` must deny `localhost`,
`localhost:8091`, and `http://localhost:8091/other` exactly as
broadly as the path-free `http://localhost:8091*` already does; a
*more* specific exclusion pattern must never produce a *narrower*
deny. The allow side is unchanged: `_matches_url_pattern`'s literal,
path-aware behaviour still governs an explicit allow entry that
spells a path out (FORK-S governs only what an implicit pattern may
infer, never what an operator explicitly wrote). FORK-Z (DEFAULT
yes): the exclusion's host-identity comparison also discards a URL
pattern's query/fragment, by the same rule-6 reasoning -- in practice
this falls out for free, since a URL's parsed hostname never included
them to begin with.
"""

from __future__ import annotations

import fnmatch
import ipaddress
import re
from typing import Literal
from urllib.parse import urlsplit

from kronos.manifest import ScopeManifest

TargetShape = Literal[
    "url", "ip", "ip_port", "host", "host_port", "bundle_id", "arn", "bucket_name", "unknown"
]

_STANDARD_PORTS = {"http": 80, "https": 443}

# SPEC_BRIEF10.3 §1.2: every scope-gated node type's permitted target
# shape family, owned here (the guard owns scope policy; `graph.py`
# only reports what kind of node it is holding -- §4). A type absent
# from this mapping, or present with an empty frozenset, denies
# unconditionally (§1.1's fail-closed rule) before any pattern is even
# consulted -- there is no permissive default.
#
# SPEC_BRIEF10.5 §1.1 RULE 5 (re-derivation, per-row citation + rule):
# when NEITHER a production producer NOR a ratified predecessor-brief
# prose decision exists for a type (rule 1 unsatisfiable by either),
# the family is derived from schema.py: if the schema gives the type no
# identity-bearing column other than `id` (or only qualifiers such as
# port/protocol), identity lives in the id and the id's shape family
# applies; if it gives a column carrying network identity (url, name),
# the id is not required to carry it and the family is frozenset().
# Rule 1 outranks rule 5; rules 3 and 4 still bind (no row by analogy;
# canonical/merge key is never evidence of id production).
#   Per-row evidence and rule. SPEC_BRIEF10.5 §8.2 requires BOTH a
#   citation naming a schema.py line or a producer call site, AND the
#   rule number, for EVERY row. The machine-readable form is
#   NODE_TYPE_SHAPE_EVIDENCE below, which a test asserts against
#   NODE_TYPE_SHAPES -- the claim is enforced, not merely written down.
#   No row cites a docstring, a convention, or another type.
#   HOST           rule 1  Brief #10.3 §1.2's RATIFIED prose table assigns
#                          HOST `host, ip, host_port, ip_port` ("boundary
#                          rule applies"), and test_b103_h2[HOST-localhost*-
#                          localhost:8091-True] locks it. A ratified
#                          predecessor prose decision IS rule-1 evidence, so
#                          rule 5 is never reached for this row. FORK-AB:
#                          narrowing to {host, ip} from src/kronos/schema.py:223's
#                          missing `port` column was PROPOSED AND REJECTED --
#                          a missing port COLUMN does not forbid a
#                          port-bearing ID (SERVICE stores a port separately
#                          AND carries one in its id). See SPEC_BRIEF10.5
#                          §1.1 and DECISIONS.md.
#   SERVICE        rule 5  src/kronos/schema.py:224 NODE_COLUMNS (+port, protocol
#                          qualifiers; NODE_PROPS_ALWAYS :166) -> identity
#                          in the id -> {host, ip, host_port, ip_port}.
#   WEB_ENDPOINT   rule 5  src/kronos/schema.py:225 (`url` column carries identity)
#                          -> frozenset().
#   PARAMETER      rule 5  src/kronos/schema.py:226 (`name` column) -> frozenset().
#   API_ENDPOINT   rule 1  ingest/mobile/parser.py:276 upserts
#                          id=found.url (src/kronos/schema.py:227 also has url/method
#                          but rule 1 outranks rule 5) -> {url}.
# SPEC_BRIEF10.5 §8.2: (rule, citation) per row. Rule 1 = a production
# producer call site. Rule 5 = derived from schema.py because neither a
# producer nor a ratified predecessor-brief prose decision exists.
NODE_TYPE_SHAPE_EVIDENCE: dict[str, tuple[int, str]] = {
    "HOST": (1, "SPEC_BRIEF10.3 §1.2 ratified prose table; locked by test_b103_h2 (FORK-AB)"),
    "SERVICE": (5, "src/kronos/schema.py:224 NODE_COLUMNS (+port, protocol are qualifiers); NODE_PROPS_ALWAYS:166"),
    "WEB_ENDPOINT": (5, "src/kronos/schema.py:225 NODE_COLUMNS -- `url` column carries the network identity"),
    "API_ENDPOINT": (1, "src/kronos/ingest/mobile/parser.py:276 -- NodeUpsert(\"API_ENDPOINT\", found.url)"),
    "CLOUD_RESOURCE": (1, "NodeUpsert(\"CLOUD_RESOURCE\", ...) at cybergym/kronos_validation_run.py:252,257 (bucket-name and ARN ids). NOTE: this is the CyberGym validation harness, the ONLY producer of this type that exists -- no src/ ingester does. This row grants the only free mid-token glob expansion in the system, so it rests on the weakest producer evidence of any row; revisit when a real cloud ingester lands."),
    "MOBILE_APP": (1, "src/kronos/ingest/mobile/parser.py:171 and src/kronos/ingest/__init__.py:46 -- NodeUpsert(\"MOBILE_APP\", bundle_id)"),
    "MOBILE_COMPONENT": (1, "src/kronos/ingest/mobile/parser.py:177 -- NodeUpsert(\"MOBILE_COMPONENT\", f\"{bundle_id}/{name}\")"),
    "SECRET": (1, "NodeUpsert(\"SECRET\", ...) at src/kronos/ingest/mobile/parser.py:244 and src/kronos/ingest/__init__.py:47 -- id is sha256-derived and matches no shape family, so the family is empty and scope arrives via scope_key (FORK-Y)"),
    "PARAMETER": (5, "src/kronos/schema.py:226 NODE_COLUMNS -- `name` column carries the identity; §1.4"),
    "IDENTITY": (5, "src/kronos/schema.py:231 NODE_COLUMNS -- `name`/`provider` columns carry the identity; no producer"),
    "TECHNOLOGY": (5, "src/kronos/schema.py:233 NODE_COLUMNS -- `name`/`version` columns carry the identity; no producer"),
    "FINDING": (1, "SPEC_BRIEF10.3 FORK-W(2) ratified prose: no production producer and no established id convention, so the family is empty. NOT rule 5 -- src/kronos/schema.py:234's `title`/`severity` are not NETWORK identities, so rule 5's first branch would wrongly yield a non-empty family."),
}

NODE_TYPE_SHAPES: dict[str, frozenset[TargetShape]] = {
    "HOST": frozenset({"host", "ip", "host_port", "ip_port"}),
    "SERVICE": frozenset({"host", "ip", "host_port", "ip_port"}),
    "WEB_ENDPOINT": frozenset(),
    "API_ENDPOINT": frozenset({"url"}),
    "CLOUD_RESOURCE": frozenset({"bucket_name", "arn"}),
    "MOBILE_APP": frozenset({"host"}),
    "MOBILE_COMPONENT": frozenset({"host"}),
    "SECRET": frozenset(),
    "PARAMETER": frozenset(),
    "IDENTITY": frozenset(),
    "TECHNOLOGY": frozenset(),
    "FINDING": frozenset(),
}

_BRACKETED_RE = re.compile(r"^\[(?P<addr>.+)\](?::(?P<port>\d+))?$")


def _try_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _parse_bracketed_ip(target: str) -> tuple[str, int | None] | None:
    """"[addr]" / "[addr]:port" -> (addr, port) when addr is a valid IP
    literal (zone indices and IPv4-mapped forms included -- Python's
    `ipaddress` accepts both natively, §8.4); else None."""
    match = _BRACKETED_RE.match(target)
    if match is None:
        return None
    addr = match.group("addr")
    if _try_ip(addr) is None:
        return None
    port_str = match.group("port")
    return addr, (int(port_str) if port_str else None)


def classify_target(target: str) -> TargetShape:
    """Classify `target`'s apparent shape. Detection order (each step
    rules out every later one; documented per §4/§10 since order
    matters):

    1. Empty or whitespace-only -> "unknown".
    2. Bracketed `[addr]` / `[addr]:port` where `addr` is a valid IP
       literal -> "ip_port" if a port follows, else "ip".
    3. Unbracketed, exactly one ":" where the left side alone is a
       valid IP address and the right side is all digits -> "ip_port"
       (the "ip:port" node-id shape SPEC.md's dedup convention
       produces). This never fires for a bare IPv6 literal, which has
       more than one colon.
    4. The whole string parses directly as an IP address (bare IPv4, a
       multi-colon bare IPv6 literal, zone-indexed, or IPv4-mapped) ->
       "ip".
    5. `urlsplit()` yields an http/https scheme with a non-empty
       `netloc` -> "url". (A string like "api.acme.com:443" is NOT
       mistaken for a URL here: `urlsplit` treats "api.acme.com" as a
       bogus *scheme*, which this step's explicit `in ("http",
       "https")` check rejects.)
    6. Unbracketed, exactly one ":" (reaching here means the left side
       is never an IP) with an all-digit right side -> "host_port".
    7. A malformed URL-like fragment -- contains "://" but `urlsplit`
       found no netloc (e.g. "http://" or "://" alone) -> "unknown".
    8. Starts with the literal "arn:" -> "arn" (SPEC_BRIEF10.1 §1.3).
       Unambiguous -- no hostname, IP, or bundle id is ever spelled this
       way -- so it's checked before the final fallback, not guessed.
    9. Anything else with no "." at all -> "bucket_name" (SPEC_BRIEF10.1
       §1.3). A bare, dot-free token is the one shape this module can
       tell apart from a multi-label hostname/lookalike-domain target
       by the string alone: every lookalike this brief's G1-G6 close
       introduces its new label via a literal "." (an attacker always
       registers `<something>.attacker.net`), so "no dot at all" is a
       safe, conservative signal for "free glob expansion is fine
       here" -- it only ever *relaxes* matching back to this module's
       pre-SPEC_BRIEF10.1 behavior for such a target, never narrows an
       existing allow or exclusion. A genuinely single-label hostname
       (`localhost`) is unaffected in practice: every existing
       standard-port/exact-match/host:port code path below still
       produces the same verdict for it regardless of which of these
       two shape names it carries (see `README_scope.md`).
    10. Anything else -- a bare hostname, an apex domain, or a bundle id
        -- is "host". §8.2 (SPEC_BRIEF10): this module never attempts to
        tell a bundle id apart from a hostname from the string alone (it
        is not safely decidable -- see FORK-T); every dotted bare token
        folds into "host" by default rather than guess. `TargetShape`
        keeps "bundle_id" for the taxonomy §4 specifies, but
        `classify_target` never produces it.
    """
    if not target or not target.strip():
        return "unknown"

    if target.startswith("arn:"):
        return "arn"

    bracketed = _parse_bracketed_ip(target)
    if bracketed is not None:
        _, port = bracketed
        return "ip_port" if port is not None else "ip"

    if target.count(":") == 1:
        host, _, maybe_port = target.rpartition(":")
        if host and maybe_port.isdigit() and _try_ip(host) is not None:
            return "ip_port"

    if _try_ip(target) is not None:
        return "ip"

    split = urlsplit(target)
    if split.scheme in ("http", "https") and split.netloc:
        return "url"

    if target.count(":") == 1:
        host, _, maybe_port = target.rpartition(":")
        if host and maybe_port.isdigit():
            return "host_port"

    if "://" in target:
        return "unknown"

    if "." not in target:
        return "bucket_name"

    return "host"


def _effective_shape(target: str, node_type: str) -> TargetShape:
    """SPEC_BRIEF10.3 §4/H2: `classify_target` keeps its own pure,
    type-blind shape detection unchanged -- including step 9's
    "dot-free -> bucket_name" fallback -- but the ALLOW side never acts
    on that fallback for anything except `CLOUD_RESOURCE`. Both
    `localhost*` -> `localhostevil` (must deny, a hostname) and
    `kronos-cybergym-*` -> `kronos-cybergym-general-secrets` (must
    allow, a bucket) are dot-free and therefore identical strings to
    `classify_target`; the node type is the only signal that tells
    them apart, so it's applied here, once, right before the type gate
    and the matcher both see it -- never inferred from the string.
    Every other shape passes through unchanged; this only ever
    *narrows* a dot-free non-CLOUD_RESOURCE target back to `"host"`'s
    boundary-rule-governed matching, never widens anything."""
    shape = classify_target(target)
    if shape == "bucket_name" and node_type != "CLOUD_RESOURCE":
        return "host"
    return shape


def _scope_key_shape(target: str) -> TargetShape:
    """SPEC_BRIEF10.4 §1.1: a `scope_key`'s matching shape is its own,
    independent of any `node_type` -- there is no node-type signal to
    consult for it at all (unlike `_effective_shape`, which exists
    *because* an id's ambiguous dot-free string needs the node type to
    tell a bucket name from a bare host apart). Without that signal,
    the ambiguous dot-free case must resolve to the narrower reading:
    a dot-free `scope_key` is always treated as `"host"` (boundary-
    rule-governed), never `"bucket_name"`'s free mid-token glob
    expansion -- `scope_key="localhost"` on a CLOUD_RESOURCE becomes
    governed by the host boundary rule, narrower than bucket-glob
    treatment, never looser (guardrail §9: the allow side is not
    widened anywhere). An unambiguous shape -- an explicit `arn:...`
    scope_key, for instance -- passes straight through unaffected,
    so CyberGym's own ARN-form scope_keys keep their free glob
    expansion exactly as before."""
    shape = classify_target(target)
    if shape == "bucket_name":
        return "host"
    return shape


def _host_port_scheme(target: str, shape: TargetShape) -> tuple[str | None, int | None, str | None]:
    """(host, explicit_port, scheme) for the shapes that carry a host
    component (url/host/host_port); (None, None, None) otherwise. `host`
    is always lowercased; `port` is only the *explicit* port (None when
    none was written, even for a URL whose scheme implies one).

    SPEC_BRIEF10.3 §1.3/H3: `"bucket_name"` is treated the same as
    `"host"` here -- the whole token IS the host text, there is no
    port to extract. This only ever matters on the exclusion path:
    there, `shape` is the *raw*, node-type-independent
    `classify_target` result (never the allow side's type-corrected
    `_effective_shape`), so a dot-free bare exclusion target like
    `excluded = ["http://localhost:8091*"]` denying the bare
    `localhost` form of the same host needs this -- without it, the
    exclusion's own host-identity comparison (`_matches_explicit_port_url_pattern`,
    `_matches_trailing_host_glob`) would see `"bucket_name"`, not
    `"host"`, and silently never match."""
    if shape == "url":
        split = urlsplit(target)
        host = split.hostname
        try:
            port = split.port
        except ValueError:
            port = None
        return (host, port, split.scheme)
    if shape in ("ip", "ip_port"):
        # SPEC_BRIEF10.5 §1.2/§4.1: address-shaped targets carry an
        # address (and port, if present) identity, bracketed / zone-
        # indexed / IPv4-mapped IPv6 included. Previously fell through
        # to (None, None, None), so every exclusion host-identity branch
        # bailed out for them. Allow-side callers are all gated on
        # url/host/host_port shapes or use _matches_address_pattern, so
        # this does not change the allow side.
        bracketed = _parse_bracketed_ip(target)
        if bracketed is not None:
            return (bracketed[0].lower(), bracketed[1], None)
        if shape == "ip_port":
            host, _, port_str = target.rpartition(":")
            return (host.lower(), int(port_str), None)
        return (target.lower(), None, None)
    if shape == "host_port":
        host, _, port_str = target.rpartition(":")
        return (host.lower(), int(port_str), None)
    if shape in ("host", "bucket_name"):
        return (target.lower(), None, None)
    return (None, None, None)


def _is_standard_port(scheme: str | None, port: int | None) -> bool:
    """§1.1 rule 2: no port at all (a bare host) is always fine -- there
    is no nonstandard port being asserted. A known scheme must pair with
    its own standard port exactly (http+80, https+443); a schemeless
    `host:port` target accepts either standard port, since there is no
    scheme to pair it against."""
    if port is None:
        return True
    if scheme is not None:
        return _STANDARD_PORTS.get(scheme) == port
    return port in _STANDARD_PORTS.values()


def _address_candidates(target: str, shape: TargetShape) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Every IP address literal `target` carries, regardless of outer
    shape -- guardrail §2.3: an exclusion must see every equivalent
    representation (a bracketed IPv6 literal, an IP embedded in a URL
    or `host:port`, ...). Empty when the target genuinely carries no
    address (it is hostname/bundle-id shaped)."""
    if shape in ("ip", "ip_port"):
        bracketed = _parse_bracketed_ip(target)
        if bracketed is not None:
            addr = _try_ip(bracketed[0])
        elif shape == "ip_port":
            host, _, _ = target.rpartition(":")
            addr = _try_ip(host)
        else:
            addr = _try_ip(target)
        return [addr] if addr is not None else []
    if shape in ("url", "host_port", "host"):
        host, _, _ = _host_port_scheme(target, shape)
        addr = _try_ip(host) if host else None
        return [addr] if addr is not None else []
    return []


def _address_in_network(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    network: ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> bool:
    """Containment with IPv4-mapped normalization (§8.4): `::ffff:x.x.x.x`
    must be recognized as the same address as `x.x.x.x` for exclusion
    purposes, in both directions, rather than silently failing to match
    across the two `ipaddress` types (which never raises -- it simply
    returns False -- so this would otherwise be a silent F1-class
    bypass, not a crash)."""
    if address in network:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None and mapped in network:
        return True
    return False


def _network_from_pattern(
    pattern: str,
) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    """A CIDR or bare-IP pattern (§1.1 rule 7 treats both the same --
    `ip_network(..., strict=False)` already turns a bare address into
    its own /32 or /128)."""
    try:
        return ipaddress.ip_network(pattern, strict=False)
    except ValueError:
        return None


def _matches_address_pattern(
    network: ipaddress.IPv4Network | ipaddress.IPv6Network, target: str, shape: TargetShape
) -> bool:
    return any(_address_in_network(address, network) for address in _address_candidates(target, shape))


def _matches_hostname_pattern(pattern: str, target: str, shape: TargetShape, *, is_exclusion: bool) -> bool:
    """A leading-`*.` subdomain pattern, or a bare exact-hostname
    pattern (no wildcard at all). Only ever consults the target's host
    component (FORK-S) -- never its path, query, fragment, or userinfo."""
    if shape not in ("url", "host", "host_port"):
        return False
    host, port, scheme = _host_port_scheme(target, shape)
    if not host:
        return False

    if pattern.startswith("*."):
        if is_exclusion and pattern.endswith("*"):
            # SPEC_BRIEF10.5 §1.3 (PD-5, maintainer-ruled): a both-ends
            # glob such as `*.acme.com*` used as an EXCLUSION is
            # deny-broad. The strict `*.`-suffix rule below treats
            # pattern[2:] ("acme.com*") as a literal suffix, so it fails
            # to deny `api.acme.com` -- the exact host the pattern names.
            # That is the under-match class FORK-2 exists to close, and
            # §1.3's "strictly broader than the allow side and that
            # asymmetry is the specification" governs. The comparison is
            # against the HOST identity only (FORK-S: never the path,
            # query, fragment or userinfo), so this widens the deny side
            # and cannot widen the allow side. SPEC_BRIEF10.1 FORK-U
            # still governs the ALLOW side, where a both-ends glob is
            # not a host pattern and denies (§1.3, allow-narrow).
            host_ok = fnmatch.fnmatchcase(host, pattern.lower())
        else:
            suffix = pattern[2:].lower()
            host_ok = host != suffix and host.endswith("." + suffix)
    else:
        host_ok = host == pattern.lower()

    if not host_ok:
        return False
    if is_exclusion:
        return True  # rule 6: deny is broad -- port-blind, scheme-blind
    return _is_standard_port(scheme, port)  # rule 2/4: allow is narrow


def _is_bundle_glob_pattern(pattern: str) -> bool:
    """A trailing-`.*` pattern (e.g. `com.acme.*`), and only that shape
    -- one literal wildcard, at the very end, with no leading `*.` (that
    would make it a hostname-subdomain pattern instead)."""
    return pattern.endswith(".*") and pattern.count("*") == 1 and not pattern.startswith("*.")


def _matches_bundle_glob_pattern(pattern: str, target: str) -> bool:
    """FORK-T: rather than guess whether a bare dotted target is "really"
    a bundle id or a hostname (§8.2 -- not safely decidable from the
    string alone), the fix lives entirely in what the trailing wildcard
    of a bundle-id-style *pattern* is allowed to consume: exactly one
    further label, never a multi-label hostname-style suffix. This is
    what closes F5 (`com.acme.*` must not authorize
    `com.acme.evil.attacker.net`) while keeping the existing
    `com.acme.mobileapp` match intact."""
    prefix = pattern[:-1].lower()  # keep the trailing "."
    lowered = target.lower()
    if not lowered.startswith(prefix):
        return False
    remainder = lowered[len(prefix) :]
    return bool(remainder) and "." not in remainder


def _host_port_pattern(pattern: str) -> tuple[str, int] | None:
    """An explicit `host:port` pattern (not address-shaped -- that is
    handled separately and takes priority)."""
    if pattern.count(":") != 1:
        return None
    host, _, port_str = pattern.rpartition(":")
    if not host or not port_str.isdigit() or _try_ip(host) is not None:
        return None
    return host.lower(), int(port_str)


def _matches_explicit_port_pattern(
    pattern_host: str, pattern_port: int, target: str, shape: TargetShape, *, is_exclusion: bool
) -> bool:
    """F8: an explicit `host:port` entry authorizes both the bare
    `host:port` form and the URL form of that same host and port,
    exactly -- never a different port, and (rule: "a port entry does
    not authorize the bare host") never a target with no port at all.
    As an exclusion, rule 6 still wins: broad, port-blind, for this
    shape too -- and (SPEC_BRIEF10.3 §1.3/H3) also accepts a raw
    `"bucket_name"` shape (a dot-free bare target like `localhost`),
    which `_host_port_scheme` now treats as a plain host identity."""
    host_shapes = ("url", "host", "host_port", "bucket_name") if is_exclusion else ("url", "host", "host_port")
    if shape not in host_shapes:
        return False
    host, port, _scheme = _host_port_scheme(target, shape)
    if host != pattern_host:
        return False
    if is_exclusion:
        return True
    return port is not None and port == pattern_port


def _matches_url_pattern(pattern: str, target: str) -> bool:
    """A pattern that itself contains "://" opts into literal,
    path-aware matching against the full raw target string -- the one
    place this module still does that, because the operator spelled the
    path out explicitly (e.g. an explicit `https://host/v1/*` entry, or
    CyberGym's `http://localhost*` covering its nonstandard port). This
    is not a FORK-S bypass: FORK-S governs what an *implicit*
    hostname/glob pattern may infer from a URL target, not what an
    operator explicitly wrote out."""
    return fnmatch.fnmatchcase(target.lower(), pattern.lower())


def _matches_url_exclusion_host_identity(pattern: str, target: str, shape: TargetShape) -> bool:
    """SPEC_BRIEF10.4 §1.3 (closing 10.3's own H3 fix): a URL pattern
    that itself carries a path reaches here only on the exclusion side,
    after the simple explicit-port and trailing-glob shortcuts above
    have both declined it -- e.g. `http://localhost:8091/internal/*`.
    Falling through to `_matches_url_pattern`'s literal, path-aware
    `fnmatch` (as 10.3 still did) made a *more* specific exclusion
    pattern deny *less*: `http://localhost:8091/other` and the bare
    `localhost`/`localhost:8091` forms of the same host all slipped
    through, even though the path-free `http://localhost:8091*` already
    denied all of them (measured, §0's table). Rule 6 (deny broad) means
    an exclusion is never allowed to get narrower just because the
    operator wrote a more specific path -- so here the pattern is
    reduced to its host identity only (`urlsplit().hostname`: scheme,
    port, path, query, and fragment are all discarded, FORK-Z) and
    compared against any host-ish identity the target carries, exactly
    like every other exclusion shape in this module."""
    pattern_host = urlsplit(pattern).hostname
    if not pattern_host:
        return False
    if shape not in _HOST_SHAPES_FOR_EXCLUSION:
        return False
    host, _, _ = _host_port_scheme(target, shape)
    if host is None:
        return False
    return fnmatch.fnmatchcase(host.lower(), pattern_host.lower())


def _matches_generic_pattern(pattern: str, target: str, shape: TargetShape) -> bool:
    """Everything else: an unstructured glob (`localhost*`, `*`, an ARN
    glob, ...). For a URL-shaped target this still only ever sees the
    host identity (FORK-S: no authorization transfer via path/query --
    this is F4's actual fix); for every other shape it sees the raw
    target string unchanged, exactly as the matcher always has."""
    if shape == "url":
        host, _, _ = _host_port_scheme(target, shape)
        candidate = host or ""
    else:
        candidate = target
    return fnmatch.fnmatchcase(candidate.lower(), pattern.lower())


_HOST_SHAPES_FOR_BOUNDARY: tuple[TargetShape, ...] = ("url", "host", "host_port", "ip", "ip_port")

# SPEC_BRIEF10.3 §1.3/H3: the exclusion-only widening of the shapes
# above -- a dot-free bare target's RAW shape is "bucket_name"
# (classify_target never node-type-corrects it on the exclusion path),
# but for exclusion-identity comparison it must still be treated as a
# potential host, exactly like "host" itself: deny is broad, and the
# alternative (silently never matching) is precisely H3's under-match.
_HOST_SHAPES_FOR_EXCLUSION: tuple[TargetShape, ...] = _HOST_SHAPES_FOR_BOUNDARY + ("bucket_name",)


def _is_simple_trailing_glob(pattern: str) -> bool:
    """A pattern that is exactly `<something>*` -- one wildcard, at the
    very end, and no other glob metacharacter anywhere (`?`, `[`), and
    not the bare `*` alone (that already means "match everything" and
    stays on its existing, unrestricted path -- SPEC_BRIEF10 §5.8).
    This is the only pattern shape SPEC_BRIEF10.1 §1.1's boundary rule
    applies to; every other glob shape (`*.sub`, `name.*`, an explicit
    `scheme://host/path*`, `ho?t`, `[abc]*`, ...) is untouched and
    keeps its pre-existing, already-reviewed matching path."""
    return (
        len(pattern) > 1
        and pattern.endswith("*")
        and pattern.count("*") == 1
        and "?" not in pattern
        and "[" not in pattern
    )


def _simple_trailing_host_glob_in_url_pattern(pattern: str) -> tuple[str, str] | None:
    """`scheme://host*` and nothing else -- no explicit path before the
    star (that's an operator-written path glob, SPEC_BRIEF10's
    documented `_matches_url_pattern` case, left untouched), no other
    wildcard. Returns `(scheme, host_prefix)` or `None`. This is what
    lets CyberGym's own `http://localhost*` entry (covering its
    nonstandard 8091 port with no manifest edit) go through the same
    §1.1 boundary rule as a bare `localhost*` entry, instead of the
    literal whole-string glob `_matches_url_pattern` uses for an
    explicit path glob. `rest` must carry no colon either: an entry
    that already pins an explicit port before the star (e.g.
    `http://host:8091*`) is handled separately, structurally, by
    `_simple_explicit_port_host_glob_in_url_pattern` below -- this
    helper only ever claims the bare-host case Option A's
    port-widening is about."""
    scheme, sep, rest = pattern.partition("://")
    if not sep or not scheme:
        return None
    if "/" in rest or "?" in rest or "[" in rest or ":" in rest:
        return None
    if rest.count("*") != 1 or not rest.endswith("*") or len(rest) <= 1:
        return None
    return scheme.lower(), rest[:-1]


def _simple_explicit_port_host_glob_in_url_pattern(pattern: str) -> tuple[str, str, int] | None:
    """`scheme://host:port*` and nothing else -- SPEC_BRIEF10.2's fix.
    Brief #10.1 left this shape on `_matches_url_pattern`'s literal
    whole-string path, which matches by raw character prefix: a target
    with userinfo (`http://localhost:8091@evil.net/x` -- the real host
    is `evil.net`), a lookalike suffix on the "port"
    (`http://localhost:8091.attacker.net/x`,
    `http://localhost:8091evil.net/x`), or simply a different numeric
    port that happens to share the same leading digits
    (`http://localhost:80915/x`) all shared that literal prefix and so
    were all wrongly in scope.

    Parsing mirrors `_host_port_pattern`'s own host:port split (reject
    an empty host, reject a non-digit port) so this helper only ever
    claims a pattern that is genuinely unambiguous as written; anything
    else (more than one colon, a non-digit port, a path before the
    star) falls through to the old literal path unchanged, never
    raising."""
    scheme, sep, rest = pattern.partition("://")
    if not sep or not scheme:
        return None
    if "/" in rest or "?" in rest or "[" in rest:
        return None
    if rest.count("*") != 1 or not rest.endswith("*") or len(rest) <= 1:
        return None
    host_port = rest[:-1]
    if host_port.count(":") != 1:
        return None
    host, _, port_str = host_port.rpartition(":")
    if not host or not port_str.isdigit():
        return None
    return scheme.lower(), host.lower(), int(port_str)


def _matches_explicit_port_url_pattern(
    pattern_scheme: str,
    pattern_host: str,
    pattern_port: int,
    target: str,
    shape: TargetShape,
    *,
    is_exclusion: bool,
) -> bool:
    """SPEC_BRIEF10.2 §1: a `scheme://host:port*` pattern means that
    scheme, that host, that EXACT port, any path/query/fragment --
    compared structurally via `_host_port_scheme`'s
    `urlsplit().hostname` (so userinfo resolves to the real host, H1a)
    and `urlsplit().port` (so an unparseable "port" -- H1b/H1c/H1d --
    is simply `None` and therefore never matches), never by raw string
    prefix. Only a url-shaped target even has these three components to
    compare; anything else can't possibly satisfy a pattern that names
    all three. As an exclusion, rule 6 still wins: host-only,
    port-blind AND scheme-blind -- the same breadth every other shape's
    exclusion side already gets.

    SPEC_BRIEF10.3 §1.3/H3: an exclusion also crosses *shape*
    boundaries, not just scheme/port/representation within the URL
    shape -- `excluded = ["http://localhost:8091*"]` must deny the bare
    `localhost:8091` and `localhost` forms of the same host too, since
    an exclusion computes every identity a target carries, regardless
    of how either side was written (Brief #10 §1.1 rule 6). So on the
    exclusion path only, this accepts any host-ish shape, not only
    `"url"`, and never checks scheme or port at all -- the old
    `shape != "url": return False` gate (still the allow side's rule
    below) is exactly the under-match H3 measured."""
    if is_exclusion:
        if shape not in _HOST_SHAPES_FOR_EXCLUSION:
            return False
        host, _, _ = _host_port_scheme(target, shape)
        return host == pattern_host
    if shape != "url":
        return False
    host, port, scheme = _host_port_scheme(target, shape)
    if host != pattern_host:
        return False
    return scheme == pattern_scheme and port is not None and port == pattern_port


def _matches_trailing_host_glob(
    prefix: str,
    target: str,
    shape: TargetShape,
    *,
    required_scheme: str | None = None,
    is_exclusion: bool = False,
) -> bool:
    """SPEC_BRIEF10.1 §1.1/§1.3: does `prefix` + `*` legally match
    `target`? Selected by the *target's* shape, never the pattern's
    text (§1.3): a hostname/URL/IP-shaped target (`_HOST_SHAPES_FOR_BOUNDARY`)
    may only match at a delimiter boundary -- `:`, `/`, or
    end-of-string -- never across a `.` or mid-label; a
    `bucket_name`/`arn`-shaped target (or anything else) keeps free
    glob expansion, exactly as this module always has (so
    `kronos-cybergym-*` still matches `kronos-cybergym-general-secrets`
    unchanged). `required_scheme`, when given (the
    `scheme://host*`-pattern case), is only ever satisfiable by a
    url-shaped target carrying that exact scheme -- a schemeless target
    or the other scheme never matches, so an explicit `http://host*`
    entry can't be stretched into authorizing `https://`.

    For a url-shaped target specifically, the dot check below runs
    against the *extracted host*, not the target's own top-level shape:
    `classify_target` only ever returns "url" for a scheme+netloc
    string, never "bucket_name", so a dot-free embedded host (a bare
    test endpoint like `http://ep-0`) would otherwise always take the
    boundary path even though a dot-free bare target with the exact
    same text would get `bucket_name`'s free expansion (§1.3's own
    "no dot at all" signal) -- checking the extracted host directly
    keeps the two consistent.

    SPEC_BRIEF10.3 §1.3/H3: on the exclusion path, `required_scheme`
    is dropped entirely (scheme-blind, same as every other shape's
    exclusion side) and any host-ish shape qualifies, not only
    `"url"` -- `excluded = ["http://localhost*"]` must also deny the
    bare `localhost:8091` form of the same host. The comparison
    becomes a plain host-identity equality (prefix *is* the complete
    host under Option A, never a partial needing further glob
    matching), ignoring port/path/boundary entirely -- deny stays
    broad."""
    if is_exclusion and required_scheme is not None:
        if shape not in _HOST_SHAPES_FOR_EXCLUSION:
            return False
        host, _, _ = _host_port_scheme(target, shape)
        return host is not None and host.lower() == prefix.lower()
    if required_scheme is not None:
        if shape != "url":
            return False
        host, _, scheme = _host_port_scheme(target, shape)
        if not host or scheme != required_scheme:
            return False
        if "." not in host:
            return fnmatch.fnmatchcase(host.lower(), (prefix + "*").lower())
        candidate = host
    elif shape == "url":
        host, _, _ = _host_port_scheme(target, shape)
        if host and "." not in host:
            return fnmatch.fnmatchcase(host.lower(), (prefix + "*").lower())
        candidate = host or ""
    elif shape in _HOST_SHAPES_FOR_BOUNDARY:
        candidate = target
    else:
        # bucket_name / arn / unknown: free expansion, as today.
        return fnmatch.fnmatchcase(target.lower(), (prefix + "*").lower())

    prefix_l, candidate_l = prefix.lower(), candidate.lower()
    if not candidate_l.startswith(prefix_l):
        return False
    remainder = candidate_l[len(prefix_l) :]
    return remainder == "" or remainder[0] in (":", "/")


def _matches(pattern: str, target: str, *, is_exclusion: bool, shape: TargetShape | None = None) -> bool:
    """SPEC_BRIEF10.3 §4: `shape`, when given, is the caller's
    already-computed shape -- the allow side passes `_effective_shape`
    (the node-type-gated one, H2), the exclusion side passes nothing
    and this computes the plain, type-blind `classify_target` itself
    (§1.3: exclusions are independent of node type, and the un-narrowed
    shape is the more-permissive-to-deny one anyway)."""
    if shape is None:
        shape = classify_target(target)

    network = _network_from_pattern(pattern)
    if network is not None:
        return _matches_address_pattern(network, target, shape)

    if pattern.startswith("*."):
        return _matches_hostname_pattern(pattern, target, shape, is_exclusion=is_exclusion)

    if _is_bundle_glob_pattern(pattern):
        if shape == "host":
            return _matches_bundle_glob_pattern(pattern, target)
        return _matches_generic_pattern(pattern, target, shape)

    host_port_pattern = _host_port_pattern(pattern)
    if host_port_pattern is not None:
        pattern_host, pattern_port = host_port_pattern
        return _matches_explicit_port_pattern(
            pattern_host, pattern_port, target, shape, is_exclusion=is_exclusion
        )

    if "://" in pattern:
        simple_port_glob = _simple_explicit_port_host_glob_in_url_pattern(pattern)
        if simple_port_glob is not None:
            pattern_scheme, pattern_host, pattern_port = simple_port_glob
            return _matches_explicit_port_url_pattern(
                pattern_scheme, pattern_host, pattern_port, target, shape, is_exclusion=is_exclusion
            )
        simple_url_glob = _simple_trailing_host_glob_in_url_pattern(pattern)
        if simple_url_glob is not None:
            pattern_scheme, host_prefix = simple_url_glob
            return _matches_trailing_host_glob(
                host_prefix, target, shape, required_scheme=pattern_scheme, is_exclusion=is_exclusion
            )
        if is_exclusion:
            # §1.3: a path-bearing URL pattern is reduced to its host
            # identity on the exclusion side only -- the allow side
            # below keeps its literal, path-aware behaviour unchanged.
            return _matches_url_exclusion_host_identity(pattern, target, shape)
        return _matches_url_pattern(pattern, target)

    if not any(ch in pattern for ch in "*?[") and shape in ("url", "host", "host_port"):
        # Exact literal, no wildcard: the hostname-exact path applies
        # the standard-port gate correctly for shapes that carry a host
        # identity. Anything without one (an ARN, a SECRET id, ...)
        # falls through to the plain literal comparison below, exactly
        # as it always has.
        return _matches_hostname_pattern(pattern, target, shape, is_exclusion=is_exclusion)

    if not is_exclusion and _is_simple_trailing_glob(pattern):
        # SPEC_BRIEF10.1 §1.1/§1.2: the boundary rule and Option A's
        # "any port, any path" both apply to the allow side only --
        # guardrail §2's "exclusions stay port-blind, representation-
        # blind, boundary-rule-free" (deny is broad on purpose). An
        # exclusion written as `host*` keeps the old, unrestricted
        # glob below, which is the *more* permissive-to-deny direction,
        # never a narrowing of what gets excluded.
        return _matches_trailing_host_glob(pattern[:-1], target, shape)

    return _matches_generic_pattern(pattern, target, shape)


class ScopeGuard:
    """Compiled view of a manifest's scope globs."""

    def __init__(self, manifest: ScopeManifest) -> None:
        self.excluded = list(manifest.excluded)
        self.in_scope = list(manifest.in_scope)

    def is_in_scope(self, target: str, *, node_type: str, target_kind: Literal["id", "scope_key"]) -> bool:
        """SPEC_BRIEF10.3 §1.1 / SPEC_BRIEF10.4 §1.1: `node_type` and
        `target_kind` are both REQUIRED keyword arguments -- no
        default, no permissive fallback, so no call site can forget
        either (the compiler enforces what a convention would not; a
        permissive-by-omission path is exactly how H2 happened).
        Exclusions are checked first and are completely independent of
        `node_type`/`target_kind` (§1.3) -- a type mismatch, an
        unrecognised type, or an unrecognised `target_kind` must never
        cause an exclusion to be skipped.

        `target_kind` states which of the two strings `graph.py:140`'s
        `scope_key or id` resolved to -- `target_kind="id"` applies
        `NODE_TYPE_SHAPES`'s id-shape family filter exactly as before
        (`_effective_shape`, node-type-gated); `target_kind="scope_key"`
        never consults that table at all (§1.1 normative: a scope_key
        is not an id), instead gating on the scope_key's own shape
        (`_scope_key_shape`, independent of node_type). An unrecognised
        `target_kind` denies, same as every other fail-closed case
        here.

        Fail-closed on `node_type` applies identically on both paths,
        before any allow pattern is even consulted: an unrecognised,
        empty, or `None` `node_type` denies unconditionally, whether or
        not a `scope_key` is present (§2.4/§8.3) -- it is only the
        *family filter itself* that target_kind="scope_key" skips, not
        the type-recognition gate."""
        if any(_matches(pattern, target, is_exclusion=True) for pattern in self.excluded):
            return False
        if target_kind not in ("id", "scope_key"):
            return False
        if node_type not in NODE_TYPE_SHAPES:
            return False
        if target_kind == "scope_key":
            shape = _scope_key_shape(target)
            return any(
                _matches(pattern, target, is_exclusion=False, shape=shape) for pattern in self.in_scope
            )
        permitted_shapes = NODE_TYPE_SHAPES[node_type]
        if not permitted_shapes:
            return False
        effective_shape = _effective_shape(target, node_type)
        if effective_shape not in permitted_shapes:
            return False
        if any(
            _matches(pattern, target, is_exclusion=False, shape=effective_shape) for pattern in self.in_scope
        ):
            return True
        return False


def scope_guard(
    target: str, manifest: ScopeManifest, *, node_type: str, target_kind: Literal["id", "scope_key"]
) -> bool:
    """Exact spec-named entry point: excluded-first, default-deny.

    SPEC_BRIEF10.3 FORK-V (DEFAULT 1): `node_type` is a required kwarg
    here too, matching `ScopeGuard.is_in_scope` -- fail-closed by
    construction beats a second, permissive-by-omission path with its
    own rules, which is exactly how H2 happened. SPEC_BRIEF10.4 §1.1
    adds `target_kind` for the same reason. This is a documented
    signature conflict with SPEC.md's "SCOPE GUARD" section, which
    still reads `scope_guard(target, manifest)` (two positional
    arguments, no type, no kind) -- SPEC.md is outside this brief's §3
    file list, so it is reported here rather than edited."""
    return ScopeGuard(manifest).is_in_scope(target, node_type=node_type, target_kind=target_kind)
