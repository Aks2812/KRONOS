"""Hermetic tests for the R10 egress guard: mocked subprocess, no iptables/docker."""
import subprocess

import pytest

from kronos.cleanup import CleanupRegistry
from kronos.eval import egress_guard as g

SUBNET = "172.18.0.0/16"
CHAIN = "KRONOS-CYBERGYM-EGRESS"
JUMP = ["DOCKER-USER", "-s", SUBNET, "-j", CHAIN]
JUMP_INPUT = ["INPUT", "-s", SUBNET, "-j", CHAIN]
RULES = [
    ["-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "RETURN"],
    ["-d", SUBNET, "-j", "RETURN"],
    ["-d", "127.0.0.0/8", "-j", "RETURN"],
    ["-j", "DROP"],
]


class FakeIptables:
    """Stateful iptables simulator. rc derives from chain/rule STATE only; stderr is
    deliberately arbitrary/empty. Records every argv (without the leading `-w`)."""

    def __init__(self, stderr="", fail_on=None):
        self.calls = []
        self.stderr = stderr
        self.fail_on = fail_on  # predicate(args) -> True means raise RuntimeError-worthy failure (rc 4)
        self.chains = {
            "DOCKER-USER": [["-j", "RETURN"]],
            "INPUT": [["-j", "ACCEPT"]],
            "FORWARD": [["-j", "DOCKER-USER"]],
        }

    def __call__(self, argv, capture_output=True, text=True):
        assert argv[0] == "iptables"
        assert argv[1] == "-w", argv  # F6: lock wait on EVERY invocation
        args = argv[2:]
        self.calls.append(args)

        def res(rc):
            return subprocess.CompletedProcess(argv, rc, "", self.stderr)

        if self.fail_on and self.fail_on(args):
            return res(4)
        if args[:2] == ["-n", "-L"]:
            return res(0 if args[2] in self.chains else 1)
        op, chain = args[0], args[1]
        rule = args[2:]
        if op == "-N":
            if chain in self.chains:
                return res(1)
            self.chains[chain] = []
            return res(0)
        if chain not in self.chains:
            return res(1)
        rules = self.chains[chain]
        if op == "-C":
            return res(0 if rule in rules else 1)
        if op == "-F":
            rules.clear()
        elif op == "-A":
            rules.append(rule)
        elif op == "-I":
            rules.insert(0, rule)
        elif op == "-D":
            if rule not in rules:
                return res(1)
            rules.remove(rule)
        elif op == "-X":
            del self.chains[chain]
        else:
            return res(2)
        return res(0)


@pytest.fixture
def fake(monkeypatch):
    f = FakeIptables()
    monkeypatch.setattr(g.subprocess, "run", f)
    return f


def _pristine(fake):
    return (
        CHAIN not in fake.chains
        and fake.chains["DOCKER-USER"] == [["-j", "RETURN"]]
        and fake.chains["INPUT"] == [["-j", "ACCEPT"]]
        and fake.chains["FORWARD"] == [["-j", "DOCKER-USER"]]
    )


def test_apply_exact_sequence(fake):
    g.apply_egress_guard(SUBNET)
    expected = [["-n", "-L", CHAIN], ["-N", CHAIN]]
    for r in RULES:
        expected += [["-C", CHAIN, *r], ["-A", CHAIN, *r]]
    expected += [["-C", *JUMP], ["-I", *JUMP], ["-C", *JUMP_INPUT], ["-I", *JUMP_INPUT]]
    assert fake.calls == expected
    assert fake.chains[CHAIN] == RULES
    assert fake.chains["DOCKER-USER"][0] == JUMP[1:]
    assert fake.chains["INPUT"][0] == JUMP_INPUT[1:]


def test_apply_idempotent_no_flush_no_mutation(fake):
    g.apply_egress_guard(SUBNET)
    snapshot = {k: [list(r) for r in v] for k, v in fake.chains.items()}
    fake.calls.clear()
    g.apply_egress_guard(SUBNET)
    assert fake.chains == snapshot
    assert all(c[0] in ("-n", "-C") for c in fake.calls), fake.calls  # no -F/-N/-A/-I on re-apply
    assert fake.chains["DOCKER-USER"].count(JUMP[1:]) == 1
    assert fake.chains["INPUT"].count(JUMP_INPUT[1:]) == 1


def test_apply_reapply_never_flushes_live_chain(fake):
    g.apply_egress_guard(SUBNET)
    fake.calls.clear()
    g.apply_egress_guard(SUBNET)
    assert not [c for c in fake.calls if c[0] == "-F"]


def test_apply_adds_only_missing_rules(fake):
    g.apply_egress_guard(SUBNET)
    fake.chains[CHAIN].remove(["-d", "127.0.0.0/8", "-j", "RETURN"])
    fake.calls.clear()
    g.apply_egress_guard(SUBNET)
    assert [c for c in fake.calls if c[0] == "-A"] == [["-A", CHAIN, "-d", "127.0.0.0/8", "-j", "RETURN"]]


def test_remove_and_idempotence(fake):
    g.apply_egress_guard(SUBNET)
    fake.calls.clear()
    assert g.remove_egress_guard(SUBNET) is None
    assert fake.calls == [
        ["-C", *JUMP],
        ["-D", *JUMP],
        ["-C", *JUMP],
        ["-C", *JUMP_INPUT],
        ["-D", *JUMP_INPUT],
        ["-C", *JUMP_INPUT],
        ["-n", "-L", CHAIN],
        ["-F", CHAIN],
        ["-X", CHAIN],
    ]
    assert _pristine(fake)
    assert g.remove_egress_guard(SUBNET) == "already_gone"


def test_remove_ignores_stderr_wording(monkeypatch):
    for err in ("", "totally unrelated words", "Chain already exists. No chain/target/match by that name"):
        f = FakeIptables(stderr=err)
        monkeypatch.setattr(g.subprocess, "run", f)
        g.apply_egress_guard(SUBNET)
        assert g.remove_egress_guard(SUBNET) is None
        assert _pristine(f)
        assert g.remove_egress_guard(SUBNET) == "already_gone"


def test_remove_partial_state_jump_only_input(fake):
    fake.chains[CHAIN] = list(RULES)
    fake.chains["INPUT"].insert(0, JUMP_INPUT[1:])
    assert g.remove_egress_guard(SUBNET) is None
    assert _pristine(fake)


def test_genuine_failure_raises(monkeypatch):
    monkeypatch.setattr(
        g.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 4, "", "Permission denied (you must be root)")
    )
    with pytest.raises(RuntimeError):
        g.remove_egress_guard(SUBNET)
    with pytest.raises(RuntimeError):
        g.apply_egress_guard(SUBNET)


def test_every_invocation_has_lock_wait(fake):
    g.apply_egress_guard(SUBNET)
    g.remove_egress_guard(SUBNET)
    assert fake.calls  # FakeIptables itself asserts argv[1] == "-w" on each call


def test_teardown_callable(fake):
    g.apply_egress_guard(SUBNET)
    assert g.egress_guard_teardown(SUBNET)() is None
    assert g.egress_guard_teardown(SUBNET)() == "already_gone"


# ---- F2: register-before-apply, behaviorally, with mid-apply failure ----


def _ordered_registry(fake, order):
    reg = CleanupRegistry()
    reg.register("docker", "stack", lambda: order.append("compose_down"))
    td = g.egress_guard_teardown(SUBNET)
    reg.register("firewall", "cybergym-egress", lambda: (order.append("firewall"), td())[1])
    return reg


def test_rollback_mid_apply_failure_install_jump(monkeypatch):
    # fail on the jump-install step, after chain + rules exist
    f = FakeIptables(fail_on=lambda a: a[0] == "-I" and a[1] == "DOCKER-USER")
    monkeypatch.setattr(g.subprocess, "run", f)
    order = []
    reg = _ordered_registry(f, order)
    with pytest.raises(RuntimeError):
        with reg:
            g.apply_egress_guard(SUBNET)  # registered FIRST, then apply
    assert order == ["firewall", "compose_down"]
    assert _pristine(f)
    assert reg.last_report.all_ok


def test_mid_apply_failure_leaves_partial_state_before_teardown(monkeypatch):
    f = FakeIptables(fail_on=lambda a: a[0] == "-I" and a[1] == "INPUT")
    monkeypatch.setattr(g.subprocess, "run", f)
    with pytest.raises(RuntimeError):
        g.apply_egress_guard(SUBNET)
    # chain + rules + first jump exist (proves the failure was genuinely part-way)
    assert f.chains[CHAIN] == RULES
    assert JUMP[1:] in f.chains["DOCKER-USER"]
    assert g.remove_egress_guard(SUBNET) is None
    assert _pristine(f)


def test_rollback_normal_exit(fake):
    order = []
    with _ordered_registry(fake, order):
        g.apply_egress_guard(SUBNET)
        assert not _pristine(fake)
    assert _pristine(fake)
    assert order == ["firewall", "compose_down"]


@pytest.mark.parametrize(
    "exc", [RuntimeError("boom"), TimeoutError("t"), KeyboardInterrupt(), SystemExit(2)], ids=["Exception", "TimeoutError", "KeyboardInterrupt", "SystemExit"]
)
def test_rollback_on_every_path_inside_body(fake, exc):
    order = []
    with pytest.raises(type(exc)):
        with _ordered_registry(fake, order):
            g.apply_egress_guard(SUBNET)
            raise exc
    assert _pristine(fake)
    assert order == ["firewall", "compose_down"]  # LIFO: firewall before compose down


def test_capability_preservation(fake):
    g.apply_egress_guard(SUBNET)
    g.remove_egress_guard(SUBNET)
    foreign_ok_parents = ("DOCKER-USER", "INPUT")
    mutators = ("-A", "-I", "-D", "-R", "-E", "-N", "-P", "-F", "-X", "-Z", "-S")
    for c in fake.calls:
        if c[0] not in mutators:
            assert c[0] in ("-C", "-n"), c
            continue
        if c[0] in ("-A", "-I", "-D"):
            if c[1] == CHAIN:
                continue
            assert c[1:] == JUMP or c[1:] == JUMP_INPUT, c
            assert c[2:4] == ["-s", SUBNET]
        else:
            assert c[0] in ("-N", "-F", "-X") and c[1] == CHAIN, c  # never -R -E -P -Z or foreign
    # no jump into the guard chain except the two -s <subnet> jumps (checked at apply-time state)
    g.apply_egress_guard(SUBNET)
    for name, rules in fake.chains.items():
        if name == CHAIN:
            continue
        for r in rules:
            if r[-2:] == ["-j", CHAIN]:
                assert name in foreign_ok_parents and r[:2] == ["-s", SUBNET], (name, r)
    assert fake.chains["FORWARD"] == [["-j", "DOCKER-USER"]]
    assert fake.chains["DOCKER-USER"][-1] == ["-j", "RETURN"]
    assert fake.chains["INPUT"][-1] == ["-j", "ACCEPT"]


@pytest.mark.parametrize("op", ["-R", "-E", "-N", "-P", "-F", "-X", "-Z"])
def test_foreign_chain_mutation_is_never_issued(fake, op):
    g.apply_egress_guard(SUBNET)
    g.remove_egress_guard(SUBNET)
    foreign = [c for c in fake.calls if c[0] == op and c[1] != CHAIN]
    assert foreign == []


def test_rule_order_return_before_drop(fake):
    g.apply_egress_guard(SUBNET)
    rules = fake.chains[CHAIN]
    drop = rules.index(["-j", "DROP"])
    assert drop == len(rules) - 1
    assert rules[0] == ["-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "RETURN"]
    assert rules.index(["-d", "127.0.0.0/8", "-j", "RETURN"]) < drop
    assert rules.index(["-d", SUBNET, "-j", "RETURN"]) < drop
    assert [r for r in rules if "DROP" in r] == [["-j", "DROP"]]
    assert fake.chains["DOCKER-USER"] == [JUMP[1:], ["-j", "RETURN"]]
    assert fake.chains["INPUT"] == [JUMP_INPUT[1:], ["-j", "ACCEPT"]]


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
