"""The ONLY scope-authorization mechanism (SPEC.md "SCOPE GUARD").

`scope_guard(target, manifest)` stamps `in_scope` on every node at
creation: excluded globs first (hard deny), then in_scope globs (allow),
default DENY. No other code path is allowed to set `in_scope` directly.
"""

from __future__ import annotations

import fnmatch
import ipaddress

from kronos.manifest import ScopeManifest


def _strip_port_suffix(target: str) -> str:
    """"10.0.5.10:443" -> "10.0.5.10"; anything else is returned unchanged.

    Only strips a single trailing ":<digits>" — a bare IPv6 address has
    more than one colon and is left alone, so this never mangles a real
    IPv6 literal while still recognizing the "ip:port" node-id shape
    SPEC.md's own dedup convention ("same host:port updates") produces.
    """
    if target.count(":") == 1:
        host, _, maybe_port = target.rpartition(":")
        if maybe_port.isdigit():
            return host
    return target


def _matches(pattern: str, target: str) -> bool:
    if "/" in pattern:
        try:
            network = ipaddress.ip_network(pattern, strict=False)
        except ValueError:
            network = None
        if network is not None:
            # Final review Important #3: a CIDR pattern must still catch
            # an "ip:port"-shaped target (e.g. "10.0.5.10:443") rather
            # than silently falling through to glob matching, which
            # could let an excluded IP slip past via an unrelated
            # looser in-scope wildcard.
            for candidate in (target, _strip_port_suffix(target)):
                try:
                    address = ipaddress.ip_address(candidate)
                except ValueError:
                    continue
                return address in network
    return fnmatch.fnmatchcase(target.lower(), pattern.lower())


class ScopeGuard:
    """Compiled view of a manifest's scope globs."""

    def __init__(self, manifest: ScopeManifest) -> None:
        self.excluded = list(manifest.excluded)
        self.in_scope = list(manifest.in_scope)

    def is_in_scope(self, target: str) -> bool:
        if any(_matches(pattern, target) for pattern in self.excluded):
            return False
        if any(_matches(pattern, target) for pattern in self.in_scope):
            return True
        return False


def scope_guard(target: str, manifest: ScopeManifest) -> bool:
    """Exact spec-named entry point: excluded-first, default-deny."""
    return ScopeGuard(manifest).is_in_scope(target)
