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
"""

from __future__ import annotations

import fnmatch
import ipaddress
import re
from typing import Literal
from urllib.parse import urlsplit

from kronos.manifest import ScopeManifest

TargetShape = Literal["url", "ip", "ip_port", "host", "host_port", "bundle_id", "unknown"]

_STANDARD_PORTS = {"http": 80, "https": 443}

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
    8. Anything else -- a bare hostname, an apex domain, a bundle id, an
       ARN, or any other opaque token -- is "host". §8.2: this module
       never attempts to tell a bundle id apart from a hostname from the
       string alone (it is not safely decidable -- see FORK-T); every
       bare dotted-or-not token folds into "host" by default rather than
       guess. `TargetShape` keeps "bundle_id" for the taxonomy §4
       specifies, but `classify_target` never produces it.
    """
    if not target or not target.strip():
        return "unknown"

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

    return "host"


def _host_port_scheme(target: str, shape: TargetShape) -> tuple[str | None, int | None, str | None]:
    """(host, explicit_port, scheme) for the shapes that carry a host
    component (url/host/host_port); (None, None, None) otherwise. `host`
    is always lowercased; `port` is only the *explicit* port (None when
    none was written, even for a URL whose scheme implies one)."""
    if shape == "url":
        split = urlsplit(target)
        host = split.hostname
        try:
            port = split.port
        except ValueError:
            port = None
        return (host, port, split.scheme)
    if shape == "host_port":
        host, _, port_str = target.rpartition(":")
        return (host.lower(), int(port_str), None)
    if shape == "host":
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
    shape too."""
    if shape not in ("url", "host", "host_port"):
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


def _matches(pattern: str, target: str, *, is_exclusion: bool) -> bool:
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
        return _matches_url_pattern(pattern, target)

    if not any(ch in pattern for ch in "*?[") and shape in ("url", "host", "host_port"):
        # Exact literal, no wildcard: the hostname-exact path applies
        # the standard-port gate correctly for shapes that carry a host
        # identity. Anything without one (an ARN, a SECRET id, ...)
        # falls through to the plain literal comparison below, exactly
        # as it always has.
        return _matches_hostname_pattern(pattern, target, shape, is_exclusion=is_exclusion)

    return _matches_generic_pattern(pattern, target, shape)


class ScopeGuard:
    """Compiled view of a manifest's scope globs."""

    def __init__(self, manifest: ScopeManifest) -> None:
        self.excluded = list(manifest.excluded)
        self.in_scope = list(manifest.in_scope)

    def is_in_scope(self, target: str) -> bool:
        if any(_matches(pattern, target, is_exclusion=True) for pattern in self.excluded):
            return False
        if any(_matches(pattern, target, is_exclusion=False) for pattern in self.in_scope):
            return True
        return False


def scope_guard(target: str, manifest: ScopeManifest) -> bool:
    """Exact spec-named entry point: excluded-first, default-deny."""
    return ScopeGuard(manifest).is_in_scope(target)
