"""Hermetic tests for the R10 egress guard: mocked subprocess, no iptables/docker."""
import subprocess

import pytest

from kronos.cleanup import CleanupRegistry
from kronos.eval import egress_guard as g

SUBNET = "172.18.0.0/16"
JUMP = ["DOCKER-USER", "-s", SUBNET, "-j", "KRONOS-CYBERGYM-EGRESS"]


class FakeIptables:
    """Stateful iptables simulator; records every argv."""

    def __init__(self):
        self.calls = []
        self.chains = {"DOCKER-USER": [["-j", "RETURN"]], "FORWARD": [["-j", "DOCKER-USER"]]}

    def __call__(self, argv, capture_output=True, text=True):
        assert argv[0] == "iptables"
        args = argv[1:]
        self.calls.append(args)
        op = args[0]

        def res(rc, err=""):
            return subprocess.CompletedProcess(argv, rc, "", err)

        if op == "-N":
            if args[1] in self.chains:
                return res(1, "iptables: Chain already exists.")
            self.chains[args[1]] = []
            return res(0)
        if args[1] not in self.chains:
            return res(1, "iptables: No chain/target/match by that name.")
        rules = self.chains[args[1]]
        rule = args[2:]
        if op == "-F":
            rules.clear()
        elif op == "-A":
            rules.append(rule)
        elif op == "-I":
            rules.insert(0, rule)
        elif op == "-C":
            return res(0) if rule in rules else res(1, "iptables: Bad rule (does a matching rule exist in that chain?).")
        elif op == "-D":
            if rule not in rules:
                return res(1, "iptables: Bad rule (does a matching rule exist in that chain?).")
            rules.remove(rule)
        elif op == "-X":
            del self.chains[args[1]]
        return res(0)


@pytest.fixture
def fake(monkeypatch):
    f = FakeIptables()
    monkeypatch.setattr(g.subprocess, "run", f)
    return f


def test_apply_exact_sequence(fake):
    g.apply_egress_guard(SUBNET)
    assert fake.calls == [
        ["-N", "KRONOS-CYBERGYM-EGRESS"],
        ["-F", "KRONOS-CYBERGYM-EGRESS"],
        ["-A", "KRONOS-CYBERGYM-EGRESS", "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "RETURN"],
        ["-A", "KRONOS-CYBERGYM-EGRESS", "-d", SUBNET, "-j", "RETURN"],
        ["-A", "KRONOS-CYBERGYM-EGRESS", "-d", "127.0.0.0/8", "-j", "RETURN"],
        ["-A", "KRONOS-CYBERGYM-EGRESS", "-j", "DROP"],
        ["-C", *JUMP],
        ["-I", *JUMP],
    ]


def test_apply_idempotent(fake):
    g.apply_egress_guard(SUBNET)
    fake.calls.clear()
    g.apply_egress_guard(SUBNET)
    assert ["-I", *JUMP] not in fake.calls
    assert ["-C", *JUMP] in fake.calls
    assert fake.chains["DOCKER-USER"].count(JUMP[1:]) == 1
    assert len(fake.chains["KRONOS-CYBERGYM-EGRESS"]) == 4


def test_remove_and_idempotence(fake):
    g.apply_egress_guard(SUBNET)
    fake.calls.clear()
    assert g.remove_egress_guard(SUBNET) is None
    assert fake.calls == [
        ["-C", *JUMP],
        ["-D", *JUMP],
        ["-F", "KRONOS-CYBERGYM-EGRESS"],
        ["-X", "KRONOS-CYBERGYM-EGRESS"],
    ]
    assert "KRONOS-CYBERGYM-EGRESS" not in fake.chains
    assert g.remove_egress_guard(SUBNET) == "already_gone"
    assert fake.chains["DOCKER-USER"] == [["-j", "RETURN"]]


def test_remove_genuine_failure_raises(monkeypatch):
    monkeypatch.setattr(
        g.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 4, "", "Permission denied (you must be root)")
    )
    with pytest.raises(RuntimeError):
        g.remove_egress_guard(SUBNET)
    with pytest.raises(RuntimeError):
        g.apply_egress_guard(SUBNET)


def test_teardown_callable(fake):
    g.apply_egress_guard(SUBNET)
    assert g.egress_guard_teardown(SUBNET)() is None
    assert g.egress_guard_teardown(SUBNET)() == "already_gone"


def _registry_with_guard(fake, order):
    reg = CleanupRegistry()
    reg.register("docker", "stack", lambda: order.append("compose_down"))
    g.apply_egress_guard(SUBNET)
    td = g.egress_guard_teardown(SUBNET)
    reg.register("firewall", "cybergym-egress", lambda: (order.append("firewall"), td())[1])
    return reg


def _rolled_back(fake):
    return "KRONOS-CYBERGYM-EGRESS" not in fake.chains and fake.chains["DOCKER-USER"] == [["-j", "RETURN"]]


def test_rollback_normal_exit(fake):
    order = []
    with _registry_with_guard(fake, order):
        assert not _rolled_back(fake)
    assert _rolled_back(fake)
    assert order == ["firewall", "compose_down"]


@pytest.mark.parametrize("exc", [RuntimeError("boom"), KeyboardInterrupt(), SystemExit(2)])
def test_rollback_on_exception_and_baseexception(fake, exc):
    order = []
    with pytest.raises(type(exc)):
        with _registry_with_guard(fake, order):
            raise exc
    assert _rolled_back(fake)
    assert order == ["firewall", "compose_down"]  # LIFO: firewall before compose down


def test_capability_preservation(fake):
    g.apply_egress_guard(SUBNET)
    g.remove_egress_guard(SUBNET)
    all_calls = fake.calls
    # every rule that reaches the guard chain is the subnet-scoped jump
    jumps = [c for c in all_calls if c[0] in ("-I", "-A") and c[1] == "DOCKER-USER"]
    assert jumps and all(c[2:4] == ["-s", SUBNET] for c in jumps)
    # no flush / delete / zero of DOCKER-USER or any foreign chain; -D only the scoped jump
    for c in all_calls:
        if c[0] in ("-F", "-X", "-Z", "-P"):
            assert c[1] == "KRONOS-CYBERGYM-EGRESS", c
        if c[0] == "-D":
            assert c[1:] == JUMP, c
        if c[0] in ("-A", "-I"):
            assert c[1] in ("KRONOS-CYBERGYM-EGRESS", "DOCKER-USER"), c
    assert fake.chains["FORWARD"] == [["-j", "DOCKER-USER"]]


def test_rule_order_return_before_drop(fake):
    g.apply_egress_guard(SUBNET)
    rules = fake.chains["KRONOS-CYBERGYM-EGRESS"]
    drop = rules.index(["-j", "DROP"])
    assert drop == len(rules) - 1
    assert rules.index(["-d", "127.0.0.0/8", "-j", "RETURN"]) < drop
    assert rules.index(["-d", SUBNET, "-j", "RETURN"]) < drop
    assert [r for r in rules if "DROP" in r] == [["-j", "DROP"]]
    # the only DROP is inside the dedicated chain; DOCKER-USER holds just the scoped jump + foreign rule
    assert fake.chains["DOCKER-USER"] == [JUMP[1:], ["-j", "RETURN"]]


def _docker(monkeypatch, rc=0, out="", err=""):
    seen = []

    def run(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, rc, out, err)

    monkeypatch.setattr(g.subprocess, "run", run)
    return seen


def test_discover_subnet_happy(monkeypatch):
    seen = _docker(monkeypatch, out="172.18.0.0/16\n")
    assert g.discover_subnet("cybergym_default") == "172.18.0.0/16"
    assert seen == [["docker", "network", "inspect", "cybergym_default", "--format", "{{(index .IPAM.Config 0).Subnet}}"]]


def test_discover_subnet_missing_network(monkeypatch):
    _docker(monkeypatch, rc=1, err="Error: No such network: cybergym_default")
    with pytest.raises(RuntimeError):
        g.discover_subnet("cybergym_default")


@pytest.mark.parametrize("out", ["", "<no value>", "not-a-cidr", "fd00::/64"])
def test_discover_subnet_unparseable(monkeypatch, out):
    _docker(monkeypatch, out=out)
    with pytest.raises(RuntimeError):
        g.discover_subnet("cybergym_default")
