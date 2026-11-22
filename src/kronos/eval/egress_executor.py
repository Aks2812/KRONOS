"""Least-privilege executor for the R10 egress guard (remediation for the non-root run).

Privileged iptables work runs either in-process (when the caller is already root) or
through a single fixed, root-owned helper invoked via `sudo -n`. The unprivileged run
never calls iptables directly and never passes arbitrary iptables arguments: it may ask
the helper only for the three fixed verbs apply / remove / status on the fixed
KRONOS-CYBERGYM-EGRESS boundary, with IPv4-validated subnet/gateway values, and never
through a shell.
"""
import ipaddress
import os
import subprocess
from typing import Optional

from kronos.eval import egress_guard

# The authorized, root-owned installed helper. Only this absolute path is invoked, and
# only via `sudo -n`. The repo's writable copy (scripts/kronos-cybergym-egress) is the
# install SOURCE, never the sudoers-whitelisted target.
HELPER_PATH = "/usr/local/sbin/kronos-cybergym-egress"
_VERBS = ("apply", "remove", "status")


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


def _sudo_path() -> str:
    for p in ("/usr/bin/sudo", "/bin/sudo"):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    raise RuntimeError("sudo not found at a trusted absolute path")


def egress_op(op: str, subnet: Optional[str] = None, gateway: Optional[str] = None) -> Optional[str]:
    """Run one fixed egress verb. Already root -> in-process egress_guard; otherwise
    `sudo -n <HELPER_PATH> <verb> [validated args]`. Validates the verb and IPv4 args
    before any dispatch; never uses a shell and never passes raw iptables arguments."""
    if op not in _VERBS:
        raise ValueError(f"unknown egress op: {op!r}")
    if op == "apply":
        if subnet is None or gateway is None:
            raise ValueError("apply requires subnet and gateway")
        subnet = _validate_subnet(subnet)
        gateway = _validate_gateway(gateway)
        if ipaddress.ip_address(gateway) not in ipaddress.ip_network(subnet):
            raise ValueError(f"gateway {gateway} not inside subnet {subnet}")
        helper_args = ["apply", subnet, gateway]
    elif op == "remove":
        if subnet is None:
            raise ValueError("remove requires subnet")
        subnet = _validate_subnet(subnet)
        helper_args = ["remove", subnet]
    else:  # status
        helper_args = ["status"]

    if is_privileged():
        if op == "apply":
            egress_guard.apply_egress_guard(subnet, gateway)
            return None
        if op == "remove":
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
