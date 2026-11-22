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


class FakeDocker:
    """Stateful docker simulator. Only `network inspect <net> --format {{len .Containers}}`
    is accepted (read-only); anything else fails the test."""

    def __init__(self, mode="zero"):
        self.mode = mode  # zero | active | absent | error | garbage
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        assert argv[0].startswith("/"), argv  # absolute docker path, never PATH
        assert argv[1:3] == ["network", "inspect"], argv
        assert argv[4:] == ["--format", "{{len .Containers}}"], argv
        r = lambda rc, out="", err="": subprocess.CompletedProcess(argv, rc, out, err)
        if self.mode == "zero":
            return r(0, "0\n")
        if self.mode == "active":
            return r(0, "2\n")
        if self.mode == "absent":
            return r(1, "", f"Error response from daemon: network {argv[3]} not found")
        if self.mode == "error":
            return r(1, "", "Cannot connect to the Docker daemon")
        return r(0, "not-a-number\n")


CONF = f"subnet={SUBNET}\ngateway={GATEWAY}\nnetwork=cybergym_default\n"


def _install_fakes(mod, monkeypatch, tmp_path, conf=CONF, docker_mode="zero", docker_present=True):
    fake = FakeIptables()
    docker = FakeDocker(docker_mode)

    def run(argv, capture_output=True, text=True, **kw):
        if argv[0].endswith("iptables"):
            return fake(argv, capture_output, text)
        return docker(argv)

    cfg = tmp_path / "egress.conf"
    if conf is not None:
        cfg.write_text(conf)
    monkeypatch.setattr(mod, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(mod, "_iptables_path", lambda: "/usr/sbin/iptables")
    if docker_present:
        monkeypatch.setattr(mod, "_docker_path", lambda: "/usr/bin/docker")
    monkeypatch.setattr(mod.subprocess, "run", run)
    mod._fake = fake
    mod._docker = docker
    return mod


@pytest.fixture
def helper(monkeypatch, tmp_path):
    return _install_fakes(load_helper(), monkeypatch, tmp_path)


MUTATING = (["-N"], ["-A"], ["-I"], ["-D"], ["-F"], ["-X"])


def _no_mutation(mod):
    for args in mod._fake.calls:
        assert args[:1] not in MUTATING, args


# --- parity -------------------------------------------------------------------

def test_helper_chain_rules_parity_with_egress_guard():
    mod = load_helper()
    assert mod._chain_rules(SUBNET, GATEWAY) == egress_guard._chain_rules(SUBNET, GATEWAY)


# --- argument rejection: zero positional args --------------------------------

@pytest.mark.parametrize("argv", [
    ["nuke"],
    ["apply", SUBNET],
    ["apply", SUBNET, GATEWAY],
    ["apply", "extra"],
    ["remove", SUBNET],
    ["remove", "DOCKER-USER"],
    ["remove", "-F"],
    ["status", "x"],
    ["apply", "--flush"],
    ["apply", "172.18.0.0/16; rm -rf /"],
])
def test_helper_rejects_any_argument_or_unknown_verb(helper, argv):
    assert helper.main(argv) != 0
    _no_mutation(helper)
    assert helper._fake.calls == []
    assert helper._docker.calls == []


def test_helper_empty_argv_usage(helper):
    assert helper.main([]) == 2


# --- pinned config drives everything ------------------------------------------

def test_helper_confined_to_pinned_config_subnet(monkeypatch, tmp_path):
    mod = _install_fakes(load_helper(), monkeypatch, tmp_path,
                         conf="subnet=10.77.0.0/24\ngateway=10.77.0.1\nnetwork=labnet\n")
    assert mod.main(["apply"]) == 0
    assert mod._fake.chain_rules == egress_guard._chain_rules("10.77.0.0/24", "10.77.0.1")
    assert mod._fake.parent_jumps["DOCKER-USER"] == [["DOCKER-USER", "-s", "10.77.0.0/24", "-j", CHAIN]]
    # nothing about any other subnet ever reaches iptables
    assert SUBNET not in " ".join(" ".join(c) for c in mod._fake.calls)
    assert mod.main(["remove"]) == 0
    assert mod._docker.calls[0][3] == "labnet"


@pytest.mark.parametrize("conf", [
    None,
    "",
    "subnet=172.18.0.0/16\n",
    f"subnet={SUBNET}\ngateway={GATEWAY}\n",
    f"subnet={SUBNET}\ngateway={GATEWAY}\nnetwork=n\nextra=1\n",
    f"subnet={SUBNET}\nsubnet={SUBNET}\ngateway={GATEWAY}\nnetwork=n\n",
    f"subnet=8.8.8.0/24\ngateway=8.8.8.1\nnetwork=n\n",
    f"subnet={SUBNET}\ngateway={GATEWAY}\nnetwork=bad name;rm\n",
    f"subnet={SUBNET}\ngateway={GATEWAY}\nnetwork=\n",
    f"subnet=notacidr\ngateway={GATEWAY}\nnetwork=n\n",
    f"subnet={SUBNET}\ngateway=::1\nnetwork=n\n",
    "garbage line without equals\n",
])
@pytest.mark.parametrize("verb", ["apply", "remove", "status"])
def test_helper_missing_or_malformed_config_fails_closed(monkeypatch, tmp_path, conf, verb):
    mod = _install_fakes(load_helper(), monkeypatch, tmp_path, conf=conf)
    assert mod.main([verb]) == 1
    assert mod._fake.calls == []  # NO iptables call
    assert mod._docker.calls == []


def test_helper_unreadable_config_fails_closed(monkeypatch, tmp_path):
    mod = _install_fakes(load_helper(), monkeypatch, tmp_path, conf=None)
    (tmp_path / "egress.conf").mkdir()  # a directory: open() raises OSError
    assert mod.main(["status"]) == 1
    assert mod._fake.calls == []


def test_helper_config_path_is_pinned_absolute():
    mod = load_helper()
    assert mod.CONFIG_PATH == "/etc/kronos-cybergym/egress.conf"


# --- gateway validation --------------------------------------------------------

@pytest.mark.parametrize("subnet,gateway", [
    ("172.18.0.0/16", "172.18.0.0"),       # network address
    ("172.18.0.0/16", "172.18.255.255"),   # broadcast address
    ("172.18.0.0/16", "10.0.0.1"),         # outside subnet
    ("10.1.2.0/24", "10.1.2.0"),
    ("10.1.2.0/24", "10.1.2.255"),
])
def test_helper_gateway_network_or_broadcast_rejected(monkeypatch, tmp_path, subnet, gateway):
    mod = _install_fakes(load_helper(), monkeypatch, tmp_path,
                         conf=f"subnet={subnet}\ngateway={gateway}\nnetwork=n\n")
    assert mod.main(["apply"]) == 1
    assert mod._fake.calls == []


@pytest.mark.parametrize("subnet,gateway", [
    ("172.18.0.0/16", "172.18.0.0"),
    ("172.18.0.0/16", "172.18.255.255"),
    ("172.18.0.0/16", "10.0.0.1"),
])
def test_executor_gateway_network_or_broadcast_rejected(subnet, gateway):
    with pytest.raises(ValueError):
        egress_executor.egress_op("apply", subnet, gateway)


# --- apply / remove idempotency ----------------------------------------------

def test_helper_apply_then_idempotent(helper):
    assert helper.main(["apply"]) == 0
    assert helper._fake.chain_rules == egress_guard._chain_rules(SUBNET, GATEWAY)
    assert len(helper._fake.parent_jumps["DOCKER-USER"]) == 1
    assert len(helper._fake.parent_jumps["INPUT"]) == 1
    assert helper.main(["apply"]) == 0
    assert len(helper._fake.parent_jumps["DOCKER-USER"]) == 1
    assert len(helper._fake.parent_jumps["INPUT"]) == 1
    assert helper._docker.calls == []  # apply never consults docker


def test_helper_remove_idempotent_already_gone(helper, capsys):
    assert helper.main(["remove"]) == 0
    assert "already_gone" in capsys.readouterr().out


def test_helper_apply_remove_roundtrip(helper, capsys):
    assert helper.main(["apply"]) == 0
    assert helper.main(["remove"]) == 0
    assert helper._fake.chain_rules is None
    assert helper._fake.parent_jumps["DOCKER-USER"] == []
    assert helper._fake.parent_jumps["INPUT"] == []
    capsys.readouterr()
    assert helper.main(["status"]) == 0
    assert capsys.readouterr().out.strip() == "absent"


# --- remove fail-closed while lab live ----------------------------------------

@pytest.mark.parametrize("mode", ["active", "error", "garbage"])
def test_helper_remove_refuses_while_lab_active_or_unknown(monkeypatch, tmp_path, mode):
    mod = _install_fakes(load_helper(), monkeypatch, tmp_path, docker_mode=mode)
    assert mod.main(["apply"]) == 0
    calls_before = len(mod._fake.calls)
    assert mod.main(["remove"]) == 1
    assert len(mod._fake.calls) == calls_before  # no iptables touched by the refused remove
    assert mod._fake.chain_rules is not None  # guard still in place


def test_helper_remove_refuses_when_docker_absent(monkeypatch, tmp_path):
    mod = _install_fakes(load_helper(), monkeypatch, tmp_path, docker_present=False)
    monkeypatch.setattr(mod, "_DOCKER_CANDIDATES", ("/nonexistent/docker-a", "/nonexistent/docker-b"))
    assert mod.main(["apply"]) == 0
    calls_before = len(mod._fake.calls)
    assert mod.main(["remove"]) == 1
    assert len(mod._fake.calls) == calls_before
    assert mod._fake.chain_rules is not None


def test_helper_docker_candidates_fixed_absolute():
    mod = load_helper()
    assert mod._DOCKER_CANDIDATES == ("/usr/bin/docker", "/usr/local/bin/docker")


def test_helper_remove_proceeds_after_teardown_network_absent(monkeypatch, tmp_path):
    mod = _install_fakes(load_helper(), monkeypatch, tmp_path, docker_mode="absent")
    assert mod.main(["apply"]) == 0
    assert mod.main(["remove"]) == 0
    assert mod._fake.chain_rules is None
    assert mod._fake.parent_jumps["DOCKER-USER"] == []


def test_helper_remove_proceeds_zero_containers(helper):
    assert helper.main(["apply"]) == 0
    assert helper.main(["remove"]) == 0
    assert helper._fake.chain_rules is None
    assert len(helper._docker.calls) == 1


def test_helper_docker_call_is_read_only_inspect(helper):
    helper.main(["remove"])
    assert helper._docker.calls[0] == [
        "/usr/bin/docker", "network", "inspect", "cybergym_default", "--format", "{{len .Containers}}",
    ]


# --- rc 2 fail-closed ------------------------------------------------------------

@pytest.mark.parametrize("verb", ["status", "remove"])
def test_helper_rc2_probe_is_fail_closed_not_absent(monkeypatch, tmp_path, verb, capsys):
    mod = _install_fakes(load_helper(), monkeypatch, tmp_path)
    real = mod._iptables
    mod._iptables = lambda args: (FakeIptables._res(2, stderr="ambiguous") if args[:2] == ["-n", "-L"] or args[:1] == ["-C"] else real(args))
    assert mod.main([verb]) == 1
    out = capsys.readouterr().out
    assert "absent" not in out and "already_gone" not in out
    _no_mutation(mod)


def test_helper_rc1_status_is_absent(helper, capsys):
    assert helper.main(["status"]) == 0
    assert capsys.readouterr().out.strip() == "absent"


def test_helper_state_maps_only_rc1_to_absent(monkeypatch, tmp_path):
    mod = _install_fakes(load_helper(), monkeypatch, tmp_path)
    for rc, ok in ((0, True), (1, False)):
        mod._iptables = lambda args, rc=rc: FakeIptables._res(rc)
        assert mod._state(["-n", "-L", CHAIN]) is ok
    for rc in (2, 3, 4):
        mod._iptables = lambda args, rc=rc: FakeIptables._res(rc)
        with pytest.raises(RuntimeError):
            mod._state(["-n", "-L", CHAIN])


def test_helper_apply_stays_tolerant_on_rc2(monkeypatch, tmp_path):
    mod = _install_fakes(load_helper(), monkeypatch, tmp_path)
    real = mod._iptables

    def rc2_when_missing(args):
        if args[:2] == ["-n", "-L"] and mod._fake.chain_rules is None:
            return FakeIptables._res(2)
        return real(args)

    mod._iptables = rc2_when_missing
    assert mod.main(["apply"]) == 0
    assert mod._fake.chain_rules == egress_guard._chain_rules(SUBNET, GATEWAY)


def test_egress_guard_state_maps_only_rc1_to_absent(monkeypatch):
    for rc, ok in ((0, True), (1, False)):
        monkeypatch.setattr(egress_guard.subprocess, "run", lambda a, rc=rc, **k: subprocess.CompletedProcess(a, rc, "", ""))
        assert egress_guard._state(["-n", "-L", CHAIN]) is ok
    for rc in (2, 3):
        monkeypatch.setattr(egress_guard.subprocess, "run", lambda a, rc=rc, **k: subprocess.CompletedProcess(a, rc, "", ""))
        with pytest.raises(RuntimeError):
            egress_guard._state(["-n", "-L", CHAIN])
        with pytest.raises(RuntimeError):
            egress_guard.status_egress_guard()
        with pytest.raises(RuntimeError):
            egress_guard.remove_egress_guard(SUBNET)


# --- foreign-chain protection -------------------------------------------------

def test_helper_remove_never_touches_foreign_chains(helper):
    helper.main(["apply"])
    helper.main(["remove"])
    for args in helper._fake.calls:
        if args[:1] in (["-F"], ["-X"], ["-N"]):
            assert args[1] == CHAIN, f"foreign chain touched: {args}"
        if args[:1] == ["-D"]:
            assert args[-2:] == ["-j", CHAIN], args
            assert args[1] in ("DOCKER-USER", "INPUT")


# --- failure cleanup ----------------------------------------------------------

def test_helper_apply_failure_is_fail_closed_and_removable(monkeypatch, tmp_path):
    mod = _install_fakes(load_helper(), monkeypatch, tmp_path)
    mod._fake.fail_on = lambda a: a[:1] == ["-A"] and a[2:] and a[2:][:2] == ["-d", f"{GATEWAY}/32"]
    assert mod.main(["apply"]) == 1
    mod._fake.fail_on = None
    assert mod.main(["remove"]) == 0
    assert mod._fake.chain_rules is None


# --- sudoers template ---------------------------------------------------------

SUDOERS = Path(__file__).resolve().parents[1] / "deploy" / "sudoers.d" / "kronos-cybergym-egress"


def _sudoers_rule_lines():
    return [ln for ln in SUDOERS.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def test_sudoers_has_no_wildcard_and_exact_three_commands():
    lines = _sudoers_rule_lines()
    assert len(lines) == 1
    assert "*" not in lines[0]
    cmds = lines[0].split("NOPASSWD:")[1].split(",")
    assert [c.strip() for c in cmds] == [
        "/usr/local/sbin/kronos-cybergym-egress apply",
        "/usr/local/sbin/kronos-cybergym-egress remove",
        "/usr/local/sbin/kronos-cybergym-egress status",
    ]


def test_sudoers_visudo_parses_substituted_scratch_copy(tmp_path):
    import shutil
    visudo = shutil.which("visudo") or next((p for p in ("/usr/sbin/visudo", "/sbin/visudo") if Path(p).exists()), None)
    if visudo is None:
        pytest.skip("visudo not available")
    scratch = tmp_path / "kronos-cybergym-egress"
    scratch.write_text(SUDOERS.read_text().replace("RUNUSER", "nobody"))
    r = subprocess.run([visudo, "-cf", str(scratch)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


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
    assert argv[3:] == ["apply"]  # no subnet/gateway forwarded
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
    assert captured["argv"][2:] == [egress_executor.HELPER_PATH, "remove"]


# --- hardening: private-subnet containment & absolute binaries (F2 / F4) -------

@pytest.mark.parametrize("subnet,gateway", [
    ("0.0.0.0/0", "0.0.0.1"),
    ("8.8.8.0/24", "8.8.8.1"),
])
def test_helper_rejects_overbroad_pinned_subnet(monkeypatch, tmp_path, subnet, gateway):
    mod = _install_fakes(load_helper(), monkeypatch, tmp_path,
                         conf=f"subnet={subnet}\ngateway={gateway}\nnetwork=n\n")
    assert mod.main(["apply"]) != 0
    assert mod._fake.calls == []


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
