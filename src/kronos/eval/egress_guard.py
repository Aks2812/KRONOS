"""Bounded host-egress guard for the CyberGym bridge (R10 Option 1).

Routed external (FORWARD) plus container->host-local (INPUT) container-initiated
egress containment, conntrack-preserving for host-initiated published-port probes.

A dedicated chain KRONOS-CYBERGYM-EGRESS is reached only through two scoped jumps:
`DOCKER-USER -s <subnet>` (routed/FORWARD traffic leaving the containers) and
`INPUT -s <subnet>` (traffic from the containers destined to the host itself).
Its first rule returns ESTABLISHED,RELATED so host-initiated published-port probe
responses (e.g. wait_for_services) are preserved; the bridge gateway /32 is then
dropped; intra-network and loopback destinations return; everything else is
dropped. Because the bridge gateway IP lies inside <subnet>, the gateway DROP is
placed before the intra-network RETURN so container->gateway traffic (the usual
host-local target) is now dropped rather than passed by the subnet RETURN.
Never flushes DOCKER-USER, INPUT or any foreign chain. Code-only
here: applied by the later gated run.

Idempotency is decided by iptables RETURN CODES and observed state (-S),
never by stderr wording. Every invocation carries `-w` (xtables lock wait).

Residual: that host->container published-port probes still succeed under this
guard on the real host is NOT proven hermetically; it must be confirmed at the
gated section 6/8 run.
"""

import ipaddress
import subprocess
from typing import Callable, Optional

CHAIN = "KRONOS-CYBERGYM-EGRESS"
PARENTS = ("DOCKER-USER", "INPUT")

_MAX_JUMP_DELETES = 16


def _iptables(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["iptables", "-w", *args], capture_output=True, text=True)


def _state(args: list[str]) -> bool:
    """Strict existence probe by return code: 0 -> True, 1 -> False (positively absent),
    anything else (including rc 2) raises. Used by status/remove, which must never
    report absent / already_gone on an ambiguous return code."""
    result = _iptables(args)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise RuntimeError(f"iptables {' '.join(args)} failed (rc={result.returncode}): {(result.stderr or '').strip()}")


def _probe(args: list[str]) -> bool:
    """Tolerant presence probe used only by apply (adding is idempotent and safe): 0 ->
    present; rc 1 or rc 2 -> not confirmed present (real `iptables -C` on a missing target
    chain can return rc 2); any other non-zero raises."""
    result = _iptables(args)
    if result.returncode == 0:
        return True
    if result.returncode in (1, 2):
        return False
    raise RuntimeError(f"iptables {' '.join(args)} failed (rc={result.returncode}): {(result.stderr or '').strip()}")


def _run(args: list[str]) -> None:
    result = _iptables(args)
    if result.returncode != 0:
        raise RuntimeError(f"iptables {' '.join(args)} failed (rc={result.returncode}): {(result.stderr or '').strip()}")


def _chain_exists() -> bool:
    """Strict: only a clean rc 1 means absent; rc 2 raises (fail-closed)."""
    return _state(["-n", "-L", CHAIN])


def _chain_exists_for_apply() -> bool:
    return _probe(["-n", "-L", CHAIN])


def discover_subnet(network_name: str) -> str:
    result = subprocess.run(
        ["docker", "network", "inspect", network_name, "--format", "{{(index .IPAM.Config 0).Subnet}}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker network inspect {network_name} failed: {(result.stderr or '').strip()}")
    return _validate_ipv4_subnet((result.stdout or "").strip(), network_name)


def _validate_ipv4_subnet(value: str, network_name: str) -> str:
    try:
        net = ipaddress.ip_network(value, strict=False)
    except ValueError:
        raise RuntimeError(f"unparseable subnet for network {network_name}: {value!r}") from None
    if not isinstance(net, ipaddress.IPv4Network):
        raise RuntimeError(f"non-IPv4 subnet for network {network_name}: {value!r}")
    return str(net)


def discover_gateway(network_name: str) -> str:
    result = subprocess.run(
        ["docker", "network", "inspect", network_name, "--format", "{{(index .IPAM.Config 0).Gateway}}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker network inspect {network_name} failed: {(result.stderr or '').strip()}")
    value = (result.stdout or "").strip()
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        raise RuntimeError(f"unparseable gateway for network {network_name}: {value!r}") from None
    if not isinstance(addr, ipaddress.IPv4Address):
        raise RuntimeError(f"non-IPv4 gateway for network {network_name}: {value!r}")
    return str(addr)


def assert_ipv4_only(network_name: str) -> None:
    # Fail-closed: STOP unless Docker reports IPv6 explicitly disabled (EnableIPv6 == false).
    # true, empty, or any unexpected value raises RuntimeError.
    result = subprocess.run(
        ["docker", "network", "inspect", network_name, "--format", "{{.EnableIPv6}}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker network inspect {network_name} failed: {(result.stderr or '').strip()}")
    value = (result.stdout or "").strip()
    if value != "false":
        raise RuntimeError(
            f"network {network_name} EnableIPv6={value!r}, expected 'false'; the IPv4 guard would not contain it"
        )


def _jump(parent: str, subnet: str) -> list[str]:
    return [parent, "-s", subnet, "-j", CHAIN]


def _chain_rules(subnet: str, gateway: str) -> list[list[str]]:
    return [
        ["-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "RETURN"],
        ["-d", f"{gateway}/32", "-j", "DROP"],
        ["-d", subnet, "-j", "RETURN"],
        ["-d", "127.0.0.0/8", "-j", "RETURN"],
        ["-j", "DROP"],
    ]


def _current_chain_rules() -> list[list[str]]:
    """Read the chain's rules in order via structured `iptables -S CHAIN` stdout (not stderr wording)."""
    result = _iptables(["-S", CHAIN])
    if result.returncode != 0:
        raise RuntimeError(f"iptables -S {CHAIN} failed (rc={result.returncode}): {(result.stderr or '').strip()}")
    rules = []
    for line in (result.stdout or "").splitlines():
        tokens = line.split()
        if tokens[:2] == ["-A", CHAIN]:
            rules.append(tokens[2:])
    return rules


def _normalize_rule(rule: list[str]) -> list[str]:
    """Canonicalize only the conntrack --ctstate member order (iptables -S renders it
    in its own order, e.g. RELATED,ESTABLISHED); every other token stays exactly as-is."""
    out = list(rule)
    for i, tok in enumerate(out):
        if tok == "--ctstate" and i + 1 < len(out):
            out[i + 1] = ",".join(sorted(out[i + 1].split(",")))
    return out


def apply_egress_guard(subnet: str, gateway: str) -> None:
    """Fail-closed reconcile, no flush. Fresh chain: create it and append every rule in
    order (gateway /32 DROP before the subnet RETURN, final DROP last). Existing chain:
    its rules must equal the expected rules exactly (same rules, same order, no extras,
    no gaps) -> idempotent no-op; any mismatch raises RuntimeError (the teardown
    registered before apply removes the chain on rollback). Then install the two scoped
    jumps idempotently, only after the chain is complete."""
    expected = _chain_rules(subnet, gateway)
    if not _chain_exists_for_apply():
        _run(["-N", CHAIN])
        for rule in expected:
            _run(["-A", CHAIN, *rule])
    elif [_normalize_rule(r) for r in _current_chain_rules()] != [_normalize_rule(r) for r in expected]:
        raise RuntimeError(f"existing chain {CHAIN} does not match the expected rules; refusing to reconcile")
    for parent in PARENTS:
        jump = _jump(parent, subnet)
        if not _probe(["-C", *jump]):
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


def status_egress_guard() -> str:
    """Read-only: 'present' / 'absent'. 'absent' only on a positive rc 1; rc 2 or any other
    non-zero raises RuntimeError (unknown, fail-closed), never 'absent'."""
    return "present" if _chain_exists() else "absent"


def egress_guard_teardown(subnet: str) -> Callable[[], Optional[str]]:
    return lambda: remove_egress_guard(subnet)
