"""Least-privilege executor for the R10 egress guard (remediation for the non-root run).

Privileged iptables work runs either in-process (when the caller is already root) or
through a single fixed, root-owned helper invoked via `sudo -n`. The unprivileged run
never calls iptables directly and never passes arbitrary iptables arguments: it may ask
the helper only for the three fixed verbs apply / remove / status on the fixed
KRONOS-CYBERGYM-EGRESS boundary, with NO arguments (the helper takes subnet/gateway/network
only from its pinned root-owned config), and never through a shell.
"""
import ipaddress
import os
import re
import subprocess
from typing import Optional

from kronos.eval import egress_guard

# The authorized, root-owned installed helper. Only this absolute path is invoked, and
# only via `sudo -n`. The repo's writable copy (scripts/kronos-cybergym-egress) is the
# install SOURCE, never the sudoers-whitelisted target.
HELPER_PATH = "/usr/local/sbin/kronos-cybergym-egress"
_VERBS = ("apply", "remove", "status")
# The single pinned authorized boundary (root-owned, world-readable). Same path/format the
# helper reads; the executor never trusts caller values that differ from it.
PINNED_CONFIG_PATH = "/etc/kronos-cybergym/egress.conf"
_CONFIG_KEYS = ("subnet", "gateway", "network")
_NETWORK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_DOCKER_CANDIDATES = ("/usr/bin/docker", "/usr/local/bin/docker")


def is_privileged() -> bool:
    return os.geteuid() == 0


def _validate_subnet(subnet: str) -> str:
    net = ipaddress.ip_network(subnet, strict=False)
    if not isinstance(net, ipaddress.IPv4Network):
        raise ValueError(f"non-IPv4 subnet: {subnet!r}")
    # Only a private, non-public lab subnet is acceptable (ipaddress.is_private, satisfied
    # by a Docker RFC1918 bridge range); rejects 0.0.0.0/0 and any public-routable range so
    # the guard can never be made to pass all egress.
    if not net.is_private:
        raise ValueError(f"non-private or over-broad subnet: {subnet!r}")
    return str(net)


def _validate_gateway(gateway: str) -> str:
    addr = ipaddress.ip_address(gateway)
    if not isinstance(addr, ipaddress.IPv4Address):
        raise ValueError(f"non-IPv4 gateway: {gateway!r}")
    return str(addr)


def _validate_gateway_in_subnet(subnet: str, gateway: str) -> None:
    """Gateway must be a host address strictly inside subnet (not network/broadcast)."""
    net = ipaddress.ip_network(subnet)
    addr = ipaddress.ip_address(gateway)
    if net.prefixlen > 30 or addr not in net or addr == net.network_address or addr == net.broadcast_address:
        raise ValueError(f"gateway {gateway} is not a host address strictly inside subnet {subnet}")


def read_pinned_config() -> tuple:
    """Read and validate the pinned config (same format as the helper). Any problem raises
    (fail closed). Returns (subnet, gateway, network)."""
    try:
        with open(PINNED_CONFIG_PATH, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as e:
        raise RuntimeError(f"cannot read pinned config {PINNED_CONFIG_PATH}: {e}") from None
    vals = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if not sep or key not in _CONFIG_KEYS or key in vals or not val:
            raise RuntimeError(f"malformed pinned config {PINNED_CONFIG_PATH}")
        vals[key] = val
    if set(vals) != set(_CONFIG_KEYS):
        raise RuntimeError(f"malformed pinned config {PINNED_CONFIG_PATH}: need exactly subnet, gateway, network")
    try:
        subnet = _validate_subnet(vals["subnet"])
        gateway = _validate_gateway(vals["gateway"])
        _validate_gateway_in_subnet(subnet, gateway)
    except ValueError as e:
        raise RuntimeError(f"invalid pinned config {PINNED_CONFIG_PATH}: {e}") from None
    if not _NETWORK_RE.match(vals["network"]):
        raise RuntimeError(f"invalid network name in pinned config: {vals['network']!r}")
    return subnet, gateway, vals["network"]


def _docker_path() -> str:
    for p in _DOCKER_CANDIDATES:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    raise RuntimeError("docker not found at a trusted absolute path")


def lab_network_gone(network: str) -> None:
    """Read-only fail-closed gate for the privileged in-process remove: allow only when the
    pinned network is absent or has 0 attached containers; raise (REFUSE) on >=1 container,
    docker absent, inspect error, or unparseable output. Creates nothing."""
    docker = _docker_path()
    r = subprocess.run(
        [docker, "network", "inspect", network, "--format", "{{len .Containers}}"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        err = (r.stderr or "").lower()
        if "no such network" in err or f"network {network.lower()} not found" in err:
            return
        raise RuntimeError(f"docker network inspect {network} failed (rc={r.returncode}); refusing remove")
    out = (r.stdout or "").strip()
    if not re.fullmatch(r"[0-9]+", out):
        raise RuntimeError(f"unparseable docker network inspect output {out!r}; refusing remove")
    if int(out) != 0:
        raise RuntimeError(f"network {network} still has {out} attached container(s); refusing remove")


def _sudo_path() -> str:
    for p in ("/usr/bin/sudo", "/bin/sudo"):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    raise RuntimeError("sudo not found at a trusted absolute path")


def egress_op(op: str, subnet: Optional[str] = None, gateway: Optional[str] = None) -> Optional[str]:
    """Run one fixed egress verb. Already root -> in-process egress_guard; otherwise
    `sudo -n <HELPER_PATH> <verb>` (no subnet/gateway argument: the helper reads its pinned config). Validates the verb and IPv4 args
    before any dispatch; never uses a shell and never passes raw iptables arguments."""
    if op not in _VERBS:
        raise ValueError(f"unknown egress op: {op!r}")
    # Always consult the pinned boundary first (fail closed if missing/malformed).
    pinned_subnet, pinned_gateway, pinned_network = read_pinned_config()
    if op == "apply":
        if subnet is None or gateway is None:
            raise ValueError("apply requires subnet and gateway")
        subnet = _validate_subnet(subnet)
        gateway = _validate_gateway(gateway)
        _validate_gateway_in_subnet(subnet, gateway)
        if subnet != pinned_subnet or gateway != pinned_gateway:
            raise ValueError(
                f"caller subnet/gateway {subnet}/{gateway} differ from pinned {pinned_subnet}/{pinned_gateway}"
            )
        helper_args = ["apply"]
    elif op == "remove":
        if subnet is None:
            raise ValueError("remove requires subnet")
        subnet = _validate_subnet(subnet)
        if subnet != pinned_subnet:
            raise ValueError(f"caller subnet {subnet} differs from pinned {pinned_subnet}")
        helper_args = ["remove"]
    else:  # status
        helper_args = ["status"]

    if is_privileged():
        if op == "apply":
            egress_guard.apply_egress_guard(subnet, gateway)
            return None
        if op == "remove":
            lab_network_gone(pinned_network)  # refuse while the lab is live
            return egress_guard.remove_egress_guard(subnet)
        return egress_guard.status_egress_guard()

    proc = subprocess.run(
        [_sudo_path(), "-n", HELPER_PATH, *helper_args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"egress helper {op} failed (rc={proc.returncode}): {(proc.stderr or '').strip()}"
        )
    return (proc.stdout or "").strip() or None


def egress_teardown(subnet: str):
    """Teardown callable for CleanupRegistry: removes the guard via the least-privilege path."""
    return lambda: egress_op("remove", subnet)
