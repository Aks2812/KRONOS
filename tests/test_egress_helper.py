"""Hermetic tests for the R10 least-privilege egress executor and root-owned helper.

No real iptables, docker, sudo, or network. The helper is loaded by path (it is an
installed script, not a package module) and its iptables runner is monkeypatched with a
stateful fake. The executor's privilege routing is exercised with a faked geteuid and a
captured subprocess.run.

Proves, per the GATE-1 remediation mandate: argument rejection, foreign-chain
protection, no capability expansion, apply/remove idempotency, and failure cleanup.
"""
import importlib.util
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

from kronos.eval import egress_guard
from kronos.eval import egress_executor

HELPER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "kronos-cybergym-egress"
CHAIN = "KRONOS-CYBERGYM-EGRESS"
SUBNET = "172.18.0.0/16"
GATEWAY = "172.18.0.1"


def load_helper():
    """Load the installed-script helper by path as a fresh module (not a package import)."""
    spec = importlib.util.spec_from_loader("kcge_helper", SourceFileLoader("kcge_helper", str(HELPER_PATH)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeIptables:
    """Stateful iptables simulator for the fixed KRONOS-CYBERGYM-EGRESS boundary. Return
    codes derive from observed state only; stderr is arbitrary. Records every argv
    (without the leading absolute binary and `-w`)."""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on  # predicate(args) -> True forces rc 4
        self.chain_rules = None  # None => chain absent; list => present
        self.parent_jumps = {"DOCKER-USER": [], "INPUT": []}

    @staticmethod
    def _res(rc, stdout="", stderr=""):
        return subprocess.CompletedProcess(args=["iptables"], returncode=rc, stdout=stdout, stderr=stderr)

    def __call__(self, argv, capture_output=True, text=True):
        assert argv[0].endswith("iptables"), argv
        assert argv[1] == "-w", argv  # lock wait on EVERY invocation
        args = argv[2:]
        self.calls.append(args)
        if self.fail_on and self.fail_on(args):
            return self._res(4, stderr="forced failure")
        if args[:2] == ["-n", "-L"] and len(args) == 3:
            return self._res(0 if (args[2] == CHAIN and self.chain_rules is not None) else 1)
        if args[:1] == ["-S"] and len(args) == 2:
            if args[1] == CHAIN and self.chain_rules is not None:
                out = f"-N {CHAIN}\n" + "".join(f"-A {CHAIN} {' '.join(r)}\n" for r in self.chain_rules)
                return self._res(0, stdout=out)
            return self._res(1)
        if args[:1] == ["-N"]:
            self.chain_rules = []
            return self._res(0)
        if args[:1] == ["-A"] and len(args) >= 2 and args[1] == CHAIN:
            self.chain_rules.append(args[2:])
            return self._res(0)
        if args[:1] == ["-C"]:
            parent = args[1]
            return self._res(0 if args[1:] in self.parent_jumps.get(parent, []) else 1)
        if args[:1] == ["-I"]:
            parent = args[1]
            self.parent_jumps.setdefault(parent, []).append(args[1:])
            return self._res(0)
        if args[:1] == ["-D"]:
            parent = args[1]
            if args[1:] in self.parent_jumps.get(parent, []):
                self.parent_jumps[parent].remove(args[1:])
                return self._res(0)
            return self._res(1)
        if args[:1] == ["-F"] and len(args) == 2 and args[1] == CHAIN:
            if self.chain_rules is not None:
                self.chain_rules = []
            return self._res(0)
        if args[:1] == ["-X"] and len(args) == 2 and args[1] == CHAIN:
            self.chain_rules = None
            return self._res(0)
        return self._res(2, stderr=f"unexpected argv {args}")


@pytest.fixture
def helper(monkeypatch):
    mod = load_helper()
    fake = FakeIptables()
    monkeypatch.setattr(mod, "_iptables_path", lambda: "/usr/sbin/iptables")
    monkeypatch.setattr(mod.subprocess, "run", fake)
    mod._fake = fake
    return mod


# --- parity -------------------------------------------------------------------

def test_helper_chain_rules_parity_with_egress_guard():
    mod = load_helper()
    assert mod._chain_rules(SUBNET, GATEWAY) == egress_guard._chain_rules(SUBNET, GATEWAY)


# --- argument rejection -------------------------------------------------------

@pytest.mark.parametrize("argv", [
    ["nuke"],
    ["apply"],
    ["apply", SUBNET],
    ["apply", SUBNET, GATEWAY, "extra"],
    ["remove"],
    ["remove", SUBNET, "extra"],
    ["status", "x"],
    ["apply", "not-a-subnet", GATEWAY],
    ["apply", SUBNET, "not-an-ip"],
    ["apply", "172.18.0.0/16; rm -rf /", GATEWAY],
    ["apply", "--flush", GATEWAY],
    ["remove", "DOCKER-USER"],
    ["remove", "-F"],
    ["apply", "::1/128", GATEWAY],   # IPv6 subnet rejected
    ["apply", SUBNET, "fe80::1"],    # IPv6 gateway rejected
])
def test_helper_rejects_bad_arguments(helper, argv):
    rc = helper.main(argv)
    assert rc != 0
    # no mutating iptables call escaped on a rejected argument
    for args in helper._fake.calls:
        assert args[:1] not in (["-N"], ["-A"], ["-I"], ["-D"], ["-F"], ["-X"]), args


def test_helper_empty_argv_usage(helper):
    assert helper.main([]) == 2


# --- apply / remove idempotency ----------------------------------------------

def test_helper_apply_then_idempotent(helper):
    assert helper.main(["apply", SUBNET, GATEWAY]) == 0
    assert helper._fake.chain_rules == egress_guard._chain_rules(SUBNET, GATEWAY)
    assert len(helper._fake.parent_jumps["DOCKER-USER"]) == 1
    assert len(helper._fake.parent_jumps["INPUT"]) == 1
    # second apply is a clean no-op (matching chain, jumps already present)
    assert helper.main(["apply", SUBNET, GATEWAY]) == 0
    assert len(helper._fake.parent_jumps["DOCKER-USER"]) == 1
    assert len(helper._fake.parent_jumps["INPUT"]) == 1


def test_helper_remove_idempotent_already_gone(helper):
    # removing when nothing is applied -> already_gone, rc 0
    assert helper.main(["remove", SUBNET]) == 0


def test_helper_apply_remove_roundtrip(helper):
    assert helper.main(["apply", SUBNET, GATEWAY]) == 0
    assert helper.main(["remove", SUBNET]) == 0
    assert helper._fake.chain_rules is None
    assert helper._fake.parent_jumps["DOCKER-USER"] == []
    assert helper._fake.parent_jumps["INPUT"] == []
    assert helper.main(["status"]) == 0


# --- foreign-chain protection -------------------------------------------------

def test_helper_remove_never_touches_foreign_chains(helper):
    helper.main(["apply", SUBNET, GATEWAY])
    helper.main(["remove", SUBNET])
    for args in helper._fake.calls:
        if args[:1] in (["-F"], ["-X"], ["-N"]):
            assert args[1] == CHAIN, f"foreign chain touched: {args}"


# --- failure cleanup ----------------------------------------------------------

def test_helper_apply_failure_is_fail_closed_and_removable(monkeypatch):
    mod = load_helper()
    fake = FakeIptables(fail_on=lambda a: a[:1] == ["-A"] and a[2:] and a[2:][:2] == ["-d", f"{GATEWAY}/32"])
    monkeypatch.setattr(mod, "_iptables_path", lambda: "/usr/sbin/iptables")
    monkeypatch.setattr(mod.subprocess, "run", fake)
    # apply fails mid-chain -> non-zero, fail-closed
    assert mod.main(["apply", SUBNET, GATEWAY]) == 1
    # teardown still cleans the partial chain
    fake.fail_on = None
    assert mod.main(["remove", SUBNET]) == 0
    assert fake.chain_rules is None


# --- executor: validation -----------------------------------------------------

def test_executor_rejects_unknown_op():
    with pytest.raises(ValueError):
        egress_executor.egress_op("flush")


@pytest.mark.parametrize("subnet,gateway", [
    ("not-a-subnet", GATEWAY),
    (SUBNET, "not-an-ip"),
    ("::1/128", GATEWAY),
])
def test_executor_rejects_bad_ipv4(subnet, gateway):
    with pytest.raises(ValueError):
        egress_executor.egress_op("apply", subnet, gateway)


# --- executor: privilege routing ---------------------------------------------

def test_executor_non_root_uses_sudo_helper_no_shell(monkeypatch):
    monkeypatch.setattr(egress_executor.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(egress_executor, "_sudo_path", lambda: "/usr/bin/sudo")
    captured = {}

    def fake_run(argv, capture_output=True, text=True, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="applied\n", stderr="")

    monkeypatch.setattr(egress_executor.subprocess, "run", fake_run)
    egress_executor.egress_op("apply", SUBNET, GATEWAY)
    argv = captured["argv"]
    assert argv[0].endswith("sudo")
    assert argv[1] == "-n"
    assert argv[2] == egress_executor.HELPER_PATH
    assert argv[3:] == ["apply", SUBNET, GATEWAY]
    # no capability expansion: never a shell, never raw iptables args
    assert captured["kwargs"].get("shell") is not True
    assert "iptables" not in argv


def test_executor_root_uses_inprocess_not_sudo(monkeypatch):
    monkeypatch.setattr(egress_executor.os, "geteuid", lambda: 0)
    called = {}
    monkeypatch.setattr(egress_executor.egress_guard, "apply_egress_guard",
                        lambda s, g: called.setdefault("apply", (s, g)))

    def forbidden_run(*a, **k):
        raise AssertionError("sudo/subprocess must not run when privileged")

    monkeypatch.setattr(egress_executor.subprocess, "run", forbidden_run)
    egress_executor.egress_op("apply", SUBNET, GATEWAY)
    assert called["apply"] == (SUBNET, GATEWAY)


def test_executor_helper_nonzero_raises(monkeypatch):
    monkeypatch.setattr(egress_executor.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(egress_executor, "_sudo_path", lambda: "/usr/bin/sudo")

    def fake_run(argv, capture_output=True, text=True, **kwargs):
        return subprocess.CompletedProcess(args=argv, returncode=1, stdout="", stderr="denied")

    monkeypatch.setattr(egress_executor.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        egress_executor.egress_op("remove", SUBNET)


def test_executor_teardown_removes_via_least_privilege(monkeypatch):
    monkeypatch.setattr(egress_executor.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(egress_executor, "_sudo_path", lambda: "/usr/bin/sudo")
    captured = {}

    def fake_run(argv, capture_output=True, text=True, **kwargs):
        captured["argv"] = argv
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="removed\n", stderr="")

    monkeypatch.setattr(egress_executor.subprocess, "run", fake_run)
    egress_executor.egress_teardown(SUBNET)()
    assert captured["argv"][2:] == [egress_executor.HELPER_PATH, "remove", SUBNET]


# --- hardening: private-subnet containment & absolute binaries (F2 / F4) -------

@pytest.mark.parametrize("argv", [
    ["apply", "0.0.0.0/0", "0.0.0.1"],       # default route rejected
    ["apply", "8.8.8.0/24", "8.8.8.1"],      # public subnet rejected
    ["apply", "172.18.0.0/16", "10.0.0.1"],  # gateway outside subnet rejected
])
def test_helper_rejects_overbroad_or_mismatched(helper, argv):
    assert helper.main(argv) != 0
    for args in helper._fake.calls:
        assert args[:1] not in (["-N"], ["-A"], ["-I"], ["-D"], ["-F"], ["-X"]), args


def test_executor_rejects_non_private_subnet():
    with pytest.raises(ValueError):
        egress_executor.egress_op("apply", "0.0.0.0/0", "0.0.0.1")


def test_executor_rejects_gateway_outside_subnet():
    with pytest.raises(ValueError):
        egress_executor.egress_op("apply", SUBNET, "10.0.0.1")


def test_helper_iptables_path_resolution(monkeypatch):
    mod = load_helper()
    monkeypatch.setattr(mod.os.path, "isfile", lambda p: p == "/usr/sbin/iptables")
    monkeypatch.setattr(mod.os, "access", lambda p, m: p == "/usr/sbin/iptables")
    assert mod._iptables_path() == "/usr/sbin/iptables"
    monkeypatch.setattr(mod.os.path, "isfile", lambda p: False)
    with pytest.raises(RuntimeError):
        mod._iptables_path()


def test_executor_sudo_path_absolute(monkeypatch):
    monkeypatch.setattr(egress_executor.os.path, "isfile", lambda p: p == "/usr/bin/sudo")
    monkeypatch.setattr(egress_executor.os, "access", lambda p, m: p == "/usr/bin/sudo")
    assert egress_executor._sudo_path() == "/usr/bin/sudo"
    monkeypatch.setattr(egress_executor.os.path, "isfile", lambda p: False)
    with pytest.raises(RuntimeError):
        egress_executor._sudo_path()
