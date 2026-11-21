"""Bounded host-egress guard for the CyberGym bridge (R10 Option 1).

Routed external (FORWARD) plus container->host-local (INPUT) container-initiated
egress containment, conntrack-preserving for host-initiated published-port probes.

A dedicated chain KRONOS-CYBERGYM-EGRESS is reached only through two scoped jumps:
`DOCKER-USER -s <subnet>` (routed/FORWARD traffic leaving the containers) and
`INPUT -s <subnet>` (traffic from the containers destined to the host itself).
Its first rule returns ESTABLISHED,RELATED so host-initiated published-port probe
responses (e.g. wait_for_services) are preserved; intra-network and loopback
destinations return; everything else is dropped. Because the bridge gateway IP
lies inside <subnet>, the intra-network RETURN also passes container->gateway
traffic, so the INPUT jump narrows to container->non-subnet host addresses only;
container->gateway (the usual host-local target) is intentionally allowed, per
brief section 0. Never flushes DOCKER-USER, INPUT or any foreign chain. Code-only
here: applied by the later gated run.

Idempotency is decided by iptables RETURN CODES and observed state (-L / -C),
never by stderr wording. Every invocation carries `-w` (xtables lock wait).

Residual: that host->container published-port probes still succeed under this
guard on the real host is NOT proven hermetically; it must be confirmed at the
gated section 6/8 run.
"""

import re
import subprocess
from typing import Callable, Optional

CHAIN = "KRONOS-CYBERGYM-EGRESS"
PARENTS = ("DOCKER-USER", "INPUT")

_CIDR_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")
_MAX_JUMP_DELETES = 16


def _iptables(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["iptables", "-w", *args], capture_output=True, text=True)


def _state(args: list[str]) -> bool:
    """Existence probe by return code: 0 -> True, 1 -> False, anything else raises."""
    result = _iptables(args)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise RuntimeError(f"iptables {' '.join(args)} failed (rc={result.returncode}): {(result.stderr or '').strip()}")


def _run(args: list[str]) -> None:
    result = _iptables(args)
    if result.returncode != 0:
        raise RuntimeError(f"iptables {' '.join(args)} failed (rc={result.returncode}): {(result.stderr or '').strip()}")


def _chain_exists() -> bool:
    return _state(["-n", "-L", CHAIN])


def discover_subnet(network_name: str) -> str:
    result = subprocess.run(
        ["docker", "network", "inspect", network_name, "--format", "{{(index .IPAM.Config 0).Subnet}}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker network inspect {network_name} failed: {(result.stderr or '').strip()}")
    subnet = (result.stdout or "").strip()
    if not _CIDR_RE.match(subnet):
        raise RuntimeError(f"unparseable subnet for network {network_name}: {subnet!r}")
    return subnet


def _jump(parent: str, subnet: str) -> list[str]:
    return [parent, "-s", subnet, "-j", CHAIN]


def _chain_rules(subnet: str) -> list[list[str]]:
    return [
        ["-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "RETURN"],
        ["-d", subnet, "-j", "RETURN"],
        ["-d", "127.0.0.0/8", "-j", "RETURN"],
        ["-j", "DROP"],
    ]


def apply_egress_guard(subnet: str) -> None:
    """Idempotent, per-rule, no flush: create chain if absent, add each missing rule
    in order (DROP last), then install the two scoped jumps only after the chain is complete."""
    if not _chain_exists():
        _run(["-N", CHAIN])
    for rule in _chain_rules(subnet):
        if not _state(["-C", CHAIN, *rule]):
            _run(["-A", CHAIN, *rule])
    for parent in PARENTS:
        jump = _jump(parent, subnet)
        if not _state(["-C", *jump]):
            _run(["-I", *jump])


def remove_egress_guard(subnet: str) -> Optional[str]:
    removed = False
    for parent in PARENTS:
        jump = _jump(parent, subnet)
        deletes = 0
        while _state(["-C", *jump]):
            if deletes >= _MAX_JUMP_DELETES:
                raise RuntimeError(f"iptables jump {' '.join(jump)} still present after {deletes} deletes")
            _run(["-D", *jump])
            deletes += 1
            removed = True
    if _chain_exists():
        _run(["-F", CHAIN])
        _run(["-X", CHAIN])
        removed = True
    return None if removed else "already_gone"


def egress_guard_teardown(subnet: str) -> Callable[[], Optional[str]]:
    return lambda: remove_egress_guard(subnet)
