# SPEC_BRIEF R10 — EGRESS GUARD HARDENING (pre-run, BUILD only)

Governance: `docs/governance/KRONOS_RND_CONTRACT.md` is canonical and sole-binding.
Authorized by maintainer **GATE-1** this turn: a bounded pre-run hardening BUILD on
`main` @ `454c179`, stopping at **GATE-2** (draft PR). **No firewall application, no
container stand-up, no §6/§8 run.** This brief folds the three mandatory R10 pre-run
conditions (carried in loop-state seq 430–432) into code plus hermetic tests. It
does **not** perform the R10 §6/§8 evidence run, which remains separately gated.

Baseline: `454c179` (R10 egress-guard merge, PR #68). This brief hardens
`src/kronos/eval/egress_guard.py` and its wrapper call in
`src/kronos/eval/cybergym_x_score.py`, and seals the R10EG window.

## §0 Root-cause recap (binding on the design)

The merged guard (`egress_guard.py`) contains three residuals the operator now
resolves by code:

1. **Container→gateway was intentionally allowed.** Because the bridge gateway IP
   lies inside `<subnet>`, the `-d <subnet> -j RETURN` rule also passed
   container-initiated traffic to the host-local gateway. GATE-1 reverses this:
   container→gateway must be **dropped**, while host-initiated published-port probe
   responses (ESTABLISHED,RELATED) are still preserved.
2. **Loose CIDR validation.** `_CIDR_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")`
   accepts malformed values (e.g. `999.0.0.0/99`). Replace with strict stdlib
   `ipaddress` validation, IPv4 only.
3. **IPv4-only guard with no IPv6 stop.** The guard issues `iptables` only (no
   `ip6tables`); if the Docker network has IPv6 enabled, egress over IPv6 would be
   uncontained. The guard must **STOP** (raise) rather than apply a half-guard.

Plus reviewer finding 1 (R10EG review, hermetically unverifiable there): real
`iptables -C` against a **missing target chain** may return **rc 2**, not rc 1, so
the existence probe must treat rc 2 as "absent" to stay idempotent and fail-closed.

## §1 Deliverables of THIS build step

All in `src/kronos/eval/egress_guard.py` unless noted. Preserve every existing
docstring; update wording only where behaviour changes.

1. **Strict subnet validation.** Remove `_CIDR_RE`. Add a helper that parses with
   `ipaddress.ip_network(value, strict=False)` and requires an `IPv4Network`;
   raise `RuntimeError` on `ValueError`/malformed input or on a non-IPv4 (e.g. IPv6)
   result. `discover_subnet` uses it; the returned subnet string is the normalized
   `str(IPv4Network)`.
2. **Gateway discovery + validation.** Add `discover_gateway(network_name: str) -> str`
   calling `docker network inspect <name> --format "{{(index .IPAM.Config 0).Gateway}}"`,
   raising `RuntimeError` on non-zero rc or on a value that is not a valid IPv4
   **host** address (`ipaddress.ip_address` → `IPv4Address`). Return the address
   string (no mask).
3. **IPv6 stop.** Add `assert_ipv4_only(network_name: str) -> None` calling
   `docker network inspect <name> --format "{{.EnableIPv6}}"`; raise `RuntimeError`
   UNLESS the value is exactly `false` (fail-closed: unknown/empty/`true` -> STOP).
   Raise `RuntimeError` on non-zero rc. (This is the "Docker IPv6 disabled or STOP" guarantee.)
4. **Gateway DROP rule.** In `_chain_rules`, insert exactly one new rule
   `["-d", f"{gateway}/32", "-j", "DROP"]` **after** the
   `ESTABLISHED,RELATED → RETURN` rule and **before** `-d <subnet> -j RETURN`.
   Final chain order MUST be:
   1. `-m conntrack --ctstate ESTABLISHED,RELATED -j RETURN`
   2. `-d <gateway>/32 -j DROP`   ← NEW
   3. `-d <subnet> -j RETURN`
   4. `-d 127.0.0.0/8 -j RETURN`
   5. `-j DROP`
   `_chain_rules`, `apply_egress_guard` gain a `gateway` parameter:
   `apply_egress_guard(subnet: str, gateway: str)`. `remove_egress_guard` /
   `egress_guard_teardown` are unchanged (removal flushes the whole chain by `-F`/`-X`,
   so they need no gateway). Apply semantics (fail-closed reconcile): fresh chain ->
   append all rules in order (DROP last); existing chain that does not exactly match the
   expected rules (same rules, same order, no extras, no gaps) -> raise `RuntimeError`
   fail-closed (rollback removes it); existing correct chain -> idempotent no-op. The
   chain is read via `iptables -S CHAIN` (structured stdout, not stderr wording).
5. **Fail-closed rc handling.** The existence probe `_state` must treat
   `returncode in (1, 2)` as **absent** (`False`) and raise only on other non-zero
   codes (e.g. 3, 4 permission). Mutating `_run` is unchanged (raises on any
   non-zero). `_chain_exists` (`-n -L CHAIN`, rc 1 when absent) is unchanged in
   behaviour. Rationale in a short comment: real `iptables -C` on a missing target
   chain can return rc 2; both rc 1 and rc 2 mean "not present", so treating them as
   absent keeps apply/remove idempotent and leaves no leftover rule on a
   partial/interrupted application.
6. **Wrapper wiring** (`src/kronos/eval/cybergym_x_score.py`, `run()` only):
   import `discover_gateway`, `assert_ipv4_only`; before applying, call
   `assert_ipv4_only("cybergym_default")`, then `discover_subnet(...)` (unchanged),
   then `gateway = discover_gateway("cybergym_default")`; keep the register-BEFORE-apply
   teardown ordering; change the apply call to `apply_egress_guard(subnet, gateway)`.
   No other behaviour in `run()` changes. **Build only — `run()` is never executed
   in this step.**
7. **Seal-tax** (`tests/test_commit_authority.py`) — see §3.

## §2 Test obligations (hermetic, mocked; `tests/test_egress_guard.py` + `tests/test_eval_cybergym_x_score.py`)

No real `iptables`/`docker`/network. Extend the existing `FakeIptables` and docker
mocks. Required coverage:

1. **Gateway DROP present and ordered.** Updated `RULES`/sequence tests prove the
   new `-d <gateway>/32 -j DROP` sits immediately after the ESTABLISHED,RELATED
   RETURN and before `-d <subnet> RETURN`, and that the final `-j DROP` stays last.
2. **ESTABLISHED,RELATED still first** (host-probe responses preserved): the
   conntrack RETURN remains rule 0, ahead of the gateway DROP.
3. **Strict subnet validation.** `discover_subnet` rejects malformed CIDRs that the
   old regex accepted (e.g. `999.0.0.0/99`, `172.18.0.0/33`) and IPv6
   (`fd00::/64`), and accepts/normalizes a valid IPv4 subnet.
4. **discover_gateway** happy path (valid IPv4 host) and rejection (missing network
   rc≠0; non-IPv4 / malformed gateway).
5. **assert_ipv4_only**: passes when `EnableIPv6` is `false`; raises when `true`;
   raises on non-zero rc.
6. **rc=2 idempotence (fail-closed).** A `FakeIptables` mode returning rc 2 for `-C`
   against a missing target chain: `remove_egress_guard` returns `already_gone`
   (no raise) and `apply_egress_guard` still installs the full chain; no leftover
   rule after a mid-apply failure under the rc-2 regime.
7. **Partial/interrupted apply teardown** preserved under the new rule set (register
   -before-apply rollback; LIFO firewall-before-compose) — extend the existing
   `test_rollback_*` / `test_mid_apply_failure_*` to the gateway-bearing chain.
8. **Capability preservation** holds: no flush/delete/mutation of `DOCKER-USER`,
   `INPUT`, `FORWARD` or any foreign chain; the only jumps into the guard chain are
   the two `-s <subnet> -j CHAIN` jumps.
9. **Wrapper wiring** (`tests/test_eval_cybergym_x_score.py`): `run()` source calls
   `assert_ipv4_only("cybergym_default")` and `discover_gateway("cybergym_default")`
   before `apply_egress_guard(subnet, gateway)`, still registers `"firewall"` before
   apply and before `wait_for_services()`, and keeps `discover_subnet("cybergym_default")`.

## §3 Seal-tax (`tests/test_commit_authority.py`)

Whole-window seal tax, surgical, weakening no other assertion:

1. **Seal the R10EG window** (PR #68) to its merge SHA: add `R10EG_MERGE = "454c179"`
   and change the open assertion
   `set(names(f"{R10EG_BASE}..HEAD")) <= R10EG_SECTION_10` to
   `set(names(f"{R10EG_BASE}..{R10EG_MERGE}")) <= R10EG_SECTION_10`.
2. **Open the R10 egress-guard-hardening window:** add `R10EGH_BASE = "454c179"` and
   ```
   R10EGH_SECTION_10 = {
       "SPEC_BRIEF_R10_egress_guard_hardening.md",
       "src/kronos/eval/egress_guard.py",
       "src/kronos/eval/cybergym_x_score.py",
       "tests/test_egress_guard.py",
       "tests/test_eval_cybergym_x_score.py",
       "tests/test_commit_authority.py",
   }
   ```
   and assertion `set(names(f"{R10EGH_BASE}..HEAD")) <= R10EGH_SECTION_10`.

## §4 Hard boundaries

- `cybergym/**`, `.claude/**`, `.github/**`, `docs/governance/**`, and the signed
  manifest are NEVER-edit. The guard never edits `cybergym/**`; it reuses
  `cybergym.selftest.compose` / `wait_for_services` by import only and filters at the
  host, outside the lab target.
- **NO live execution of any kind in this step:** no `iptables`/`nft` apply, no
  `docker compose up`, no container stand-up, no `§6/§8` R10 run, no real
  credentials, no network. `docker network inspect` is invoked only by the later
  gated `run()`; hermetic tests mock it.
- The guard mutates host firewall state ONLY when `run()` is later executed under a
  separate `§6/§8` authorization; this step neither applies nor removes a real rule.
- Exactly the six files in §3 `R10EGH_SECTION_10` may be touched.

## §5 Acceptance (§8 criteria)

- Exactly the six files in `R10EGH_SECTION_10` on branch
  `kronos/r10-egress-guard-hardening`; nothing else touched; no `cybergym/**`,
  `.claude/**`, `.github/**`, or governance file changed.
- `_CIDR_RE` removed; `discover_subnet` validates via `ipaddress` (IPv4 only).
- `discover_gateway` and `assert_ipv4_only` added with the §1 semantics.
- Chain order exactly: ESTABLISHED,RELATED RETURN → `-d <gateway>/32 DROP` →
  `-d <subnet> RETURN` → `-d 127.0.0.0/8 RETURN` → `-j DROP`.
- `_state` treats rc∈{1,2} as absent and raises on other non-zero; register-before-
  apply rollback preserved; no leftover rule on partial/interrupted apply.
- `run()` wires `assert_ipv4_only` + `discover_gateway` and calls
  `apply_egress_guard(subnet, gateway)`; register-before-apply order preserved.
- All §2 hermetic tests present and the full canonical suite is **0 failed** via
  `TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" rtk test .venv/bin/python -m pytest -q`,
  decided on the runner SUMMARY line, never `$?`.
- Seal-tax §3 applied; scope audit green.
- No live run, no firewall apply, no container stand-up.

## §6 Risks

- (a) Real `iptables -C` return codes vary by backend (legacy vs nft). RESOLVED-by-
  design: the existence probe treats rc 1 and rc 2 as "absent" and raises on other
  non-zero; dedicated rc-2 tests prove idempotent apply/remove with no leftover rule.
  Real-binary confirmation still belongs to the §6/§8 run.
- (b) The gateway DROP must not shadow host-initiated probe responses. RESOLVED: the
  ESTABLISHED,RELATED RETURN precedes the gateway DROP, so only container-initiated
  NEW flows to the gateway are dropped; a test fixes this ordering.
- (c) Gateway/subnet values are Docker-assigned at `up` time and discovered at
  runtime; hermetic tests mock discovery. The live values flow into apply only when
  `run()` is later executed under `§6/§8`. Re-apply onto a stale/gapped chain raises
  fail-closed instead of appending rules after the final DROP (fresh -> build in order;
  existing-mismatched -> raise; existing-correct -> no-op).
- (d) IPv6 dual-stack networks would bypass an IPv4-only guard. RESOLVED: `run()`
  calls `assert_ipv4_only` first and STOPs (raises) before any apply if IPv6 is
  enabled.

## §7 Non-goals

Any live firewall apply or real `iptables` mutation, any `docker compose up` or
container stand-up, the `§6/§8` R10 run itself, any real X-score measurement, any
`cybergym/**` edit, R12 (BE-G2-6), and any other `src/kronos/**` change are OUT of
scope. They belong to the separately authorized `§6/§8` run step.
