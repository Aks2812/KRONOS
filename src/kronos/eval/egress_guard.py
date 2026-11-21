"""Bounded host-egress guard for the CyberGym bridge (R10 Option 1).

A dedicated chain KRONOS-CYBERGYM-EGRESS, reachable only through a single
`DOCKER-USER -s <subnet>` jump, drops container-sourced egress while leaving
host->container published-port traffic (host-sourced) untouched. Never flushes
DOCKER-USER or any foreign chain. Code-only here: applied by the later gated run.
"""

import re
import subprocess
from typing import Callable, Optional

CHAIN = "KRONOS-CYBERGYM-EGRESS"
PARENT = "DOCKER-USER"

_ABSENT_MARKERS = (
    "no chain/target/match by that name",
    "does a matching rule exist",
    "bad rule",
    "no such file or directory",
)
_EXISTS_MARKERS = ("chain already exists",)
_CIDR_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")


def _iptables(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["iptables", *args], capture_output=True, text=True)


def _check(args: list[str]) -> bool:
    """True if the `-C` rule check succeeds; False if rule/chain absent."""
    result = _iptables(args)
    if result.returncode == 0:
        return True
    stderr = (result.stderr or "").lower()
    if any(m in stderr for m in _ABSENT_MARKERS):
        return False
    raise RuntimeError(f"iptables {' '.join(args)} failed: {result.stderr.strip()}")


def _run(args: list[str], *, tolerate: tuple[str, ...] = ()) -> Optional[str]:
    result = _iptables(args)
    if result.returncode == 0:
        return None
    stderr = (result.stderr or "").lower()
    if any(m in stderr for m in tolerate):
        return "already_gone"
    raise RuntimeError(f"iptables {' '.join(args)} failed: {result.stderr.strip()}")


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


def _jump(subnet: str) -> list[str]:
    return [PARENT, "-s", subnet, "-j", CHAIN]


def apply_egress_guard(subnet: str) -> None:
    _run(["-N", CHAIN], tolerate=_EXISTS_MARKERS)
    _run(["-F", CHAIN])
    _run(["-A", CHAIN, "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "RETURN"])
    _run(["-A", CHAIN, "-d", subnet, "-j", "RETURN"])
    _run(["-A", CHAIN, "-d", "127.0.0.0/8", "-j", "RETURN"])
    _run(["-A", CHAIN, "-j", "DROP"])
    if not _check(["-C", *_jump(subnet)]):
        _run(["-I", *_jump(subnet)])


def remove_egress_guard(subnet: str) -> Optional[str]:
    removed = False
    if _check(["-C", *_jump(subnet)]):
        _run(["-D", *_jump(subnet)])
        removed = True
    if _run(["-F", CHAIN], tolerate=_ABSENT_MARKERS) is None:
        removed = True
    if _run(["-X", CHAIN], tolerate=_ABSENT_MARKERS) is None:
        removed = True
    return None if removed else "already_gone"


def egress_guard_teardown(subnet: str) -> Callable[[], Optional[str]]:
    return lambda: remove_egress_guard(subnet)
