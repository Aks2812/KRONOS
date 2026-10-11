"""The ONLY scope-authorization mechanism (SPEC.md "SCOPE GUARD").

`scope_guard(target, manifest)` stamps `in_scope` on every node at
creation: excluded globs first (hard deny), then in_scope globs (allow),
default DENY. No other code path is allowed to set `in_scope` directly.
"""

from __future__ import annotations

import fnmatch
import ipaddress

from kronos.manifest import ScopeManifest


def _matches(pattern: str, target: str) -> bool:
    if "/" in pattern:
        try:
            network = ipaddress.ip_network(pattern, strict=False)
        except ValueError:
            network = None
        if network is not None:
            try:
                address = ipaddress.ip_address(target)
            except ValueError:
                pass
            else:
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
