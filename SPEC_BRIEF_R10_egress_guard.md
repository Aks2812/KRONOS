# SPEC_BRIEF R10 — EGRESS GUARD (Option 1 remediation, BUILD only)

Successor to the R10 egress-containment merge (PR #67, squash `be30b9e`). The one
operator-authorized R10 bounded run (loop seq 423) FAILED: the sole runtime change
vs the pre-containment wrapper — `networks.default.internal:true`
(`src/kronos/eval/cybergym_internal_net.override.yml`) — gives the Compose default
network no gateway, which on this Docker severs host→container published-port
reachability, so `cybergym/selftest.py:278 wait_for_services()` host probes to
`127.0.0.1:8091 /health` and `127.0.0.1:4567` never connect (loop seq 424).

**GATE-1 authorization (2026-11-20, operator, Option 1 — BUILD PHASE ONLY):**
remove the `internal:true` injection and implement a bounded host-level egress
guard using a dedicated, idempotent `DOCKER-USER` chain scoped only to the
CyberGym bridge subnet; preserve existing firewall rules and KRONOS runtime
behavior; guarantee rollback on every success, failure, timeout, and interruption
path; add mocked hermetic lifecycle and capability-preservation tests;
independently review; open a draft PR; STOP at GATE-2.

**This brief authorizes NO live execution:** no `iptables`/`nft` apply, no
`docker compose up`, no container stand-up, no `§6/§8` R10 run. The guard code is
built and proven hermetically (mocked `subprocess`); it is never executed against a
real host or daemon in this step. The bounded RUN that applies the guard for real
is a SEPARATE, later `§6/§8` step requiring its own explicit maintainer
authorization.

## §0 Root-cause recap (binding on the design)

`internal:true` is config-neutral (ports stay bound `127.0.0.1`) but NOT
runtime-capability-neutral: an internal Docker network has no gateway, which blocks
host↔container published-port traffic — the exact capability the lab's host-probe
readiness check and validation pass depend on. The fix must deliver **routed external (FORWARD) + container→host-local (INPUT)
container-initiated egress containment, conntrack-preserving for host-initiated
published-port probes**, WITHOUT removing host→container `127.0.0.1` publishing.

Two scoped jumps reach one dedicated chain, `KRONOS-CYBERGYM-EGRESS`:
`DOCKER-USER -s <subnet>` (routed/FORWARD traffic leaving the containers to
non-local destinations) and `INPUT -s <subnet>` (traffic from the container subnet
destined to the host itself). The chain's FIRST rule is
`-m conntrack --ctstate ESTABLISHED,RELATED -j RETURN`, so the responses to
host-initiated published-port probes (ESTABLISHED from the container's return
direction) are preserved — this is what keeps `wait_for_services()` working.
Host-initiated traffic never carries the container subnet as a NEW-connection
source, so it is not dropped.

**Residual (not provable hermetically):** that host→container published-port probe
success is preserved on the real host must be confirmed at the gated `§6/§8` run.
Container→host-gateway traffic inside the subnet (`-d <subnet> -j RETURN`) is
intentionally allowed.

## §1 Deliverables of THIS build step

1. **Remove the `internal:true` injection** from the wrapper's live path
   (`src/kronos/eval/cybergym_x_score.py`): delete `_compose_file_args()` and the
   `OVERRIDE_PATH` constant, revert `run()` to call the `cybergym.selftest.compose`
   primitive directly (`compose("up", "-d", "--build")` / `compose("down", "-v")`
   via `compose_down`), exactly as the pre-#67 wrapper did. Delete the override
   file `src/kronos/eval/cybergym_internal_net.override.yml`. No other behavior of
   `run()` changes.
2. **New module `src/kronos/eval/egress_guard.py`** — a bounded host-egress guard:
   - `discover_subnet(network_name: str) -> str`: returns the IPv4 CIDR of the
     given Docker network via `docker network inspect <name>
     --format '{{(index .IPAM.Config 0).Subnet}}'`; raises on missing network or
     unparseable output. (Network name for the CyberGym stack is `cybergym_default`
     — Compose project = `cybergym/` dir basename, `cwd=cybergym`.)
   - `apply_egress_guard(subnet: str) -> None`: idempotent per rule, with NO flush
     of a live chain. Existence/presence is decided by `iptables` RETURN CODE
     (never stderr text): chain via `iptables -w -n -L KRONOS-CYBERGYM-EGRESS`
     (rc 0 = exists), created with `-N` only when absent; each rule via
     `iptables -w -C <chain> <rule>`, added with `-A` only when `-C` reports it
     absent, IN ORDER: `-m conntrack --ctstate ESTABLISHED,RELATED -j RETURN`;
     `-d <subnet> -j RETURN` (intra-network); `-d 127.0.0.0/8 -j RETURN`
     (host/loopback); `-j DROP` (all other egress). Then installs two scoped
     jumps, each check-before-insert (`-C`, then `-I` only if absent):
     `DOCKER-USER -s <subnet> -j KRONOS-CYBERGYM-EGRESS` and
     `INPUT -s <subnet> -j KRONOS-CYBERGYM-EGRESS`. NEVER flushes `DOCKER-USER`,
     `INPUT`, or any chain but `KRONOS-CYBERGYM-EGRESS`; NEVER touches a rule it
     did not create.
   - `remove_egress_guard(subnet: str) -> str | None`: idempotent rollback. Deletes
     each scoped jump (`DOCKER-USER` and `INPUT`) while its `-C` check says
     present, then, only if the chain exists (`-L` rc), flushes and `-X`-deletes
     `KRONOS-CYBERGYM-EGRESS`. Returns `"already_gone"` when nothing was present,
     `None` otherwise; raises only on a genuine unexpected failure (a rc that is
     neither a clean success nor the "absent" rc 1).
   - `egress_guard_teardown(subnet: str) -> Callable[[], str | None]`: returns the
     zero-arg teardown callable (`lambda: remove_egress_guard(subnet)`) in the
     `kronos.cleanup` kind contract, for `CleanupRegistry.register("firewall", …)`.
   - Every live op shells `iptables -w ...` (lock wait) through one small private
     runner; outcomes are decided by return code / observed state, never by
     matching stderr wording.
3. **Wire the guard into `run()`** so rollback is guaranteed on all paths: after
   `compose(... up ...)` and after registering `compose_down`, register the egress
   guard teardown (`registry.register("firewall", …, egress_guard_teardown(subnet),
   …)`) and THEN apply it — registration precedes apply so a partial apply is still
   rolled back. LIFO order gives: firewall removed first, then `compose down`. The
   `CleanupRegistry` context manager already runs teardown on normal return, on any
   `Exception`, on a propagating `BaseException` (timeout/`KeyboardInterrupt`), and
   records a `TeardownReport`. `run()` is NOT executed in this step; its wiring is
   verified by source inspection, exactly as the existing `test_pipeline_reuse_neutral`
   and `test_compose_file_args` tests verify `run()`.
4. **Hermetic tests** (mocked `subprocess`; no live `docker`, no `iptables`, no
   network, no run) — see §2.
5. **Seal-tax** (`tests/test_commit_authority.py`) — see §3.

## §2 Test obligations (hermetic, mocked)

New `tests/test_egress_guard.py` and edits to `tests/test_eval_cybergym_x_score.py`:

- **Lifecycle (apply):** mocked `subprocess` captures the exact `iptables` call
  sequence; assert `-L` existence check → `-N` only when absent → per rule `-C`
  then `-A` only when absent, in the specified order → both scoped jumps
  (`DOCKER-USER`, `INPUT`) installed check-before-insert. Every call carries `-w`.
- **Idempotent apply:** two consecutive `apply_egress_guard` calls produce no
  duplicate jump or rule (every `-C` check succeeds, so no `-N`/`-A`/`-I`/`-F` is
  issued): the live chain is never flushed on re-apply.
- **Lifecycle (remove) + idempotence:** `remove_egress_guard` deletes both scoped jumps,
  flushes and deletes the chain; removal succeeds with empty/arbitrary stderr; a second call (nothing present) returns
  `"already_gone"` and raises nothing.
- **Rollback on all paths (behavioral register-before-apply):** with a real
  `CleanupRegistry`, register the guard teardown FIRST, then call
  `apply_egress_guard` with a failure injected part-way (jump-install step, after
  chain + rules exist); assert teardown still runs on `__exit__` and leaves nothing
  behind. Also assert cleanup on normal exit, `Exception`, `TimeoutError`,
  `KeyboardInterrupt` and `SystemExit`, and LIFO firewall-removal before
  `compose down`.
- **Capability preservation (construction proof):** assert every DROP/filter rule
  in the guard is reachable only via the `-s <subnet>` jump (so host-sourced
  `127.0.0.1` traffic is never matched); assert `-d 127.0.0.0/8 -j RETURN` and
  `-d <subnet> -j RETURN` precede the final `-j DROP`; assert no command mutates
  (`-R -E -N -P -F -X -Z`, or `-A/-I/-D` other than the two scoped jumps) any chain
  other than `KRONOS-CYBERGYM-EGRESS`, `DOCKER-USER`, `INPUT`; assert no jump into
  `KRONOS-CYBERGYM-EGRESS` exists except the two `-s <subnet>` jumps.
- **Subnet discovery:** mocked `docker network inspect` output yields the CIDR;
  missing-network / unparseable output raises.
- **Injection removed:** `OVERRIDE_PATH`, `_compose_file_args`, and
  `cybergym_internal_net.override.yml` no longer exist; `run()` source calls
  `compose("up", "-d", "--build")` directly and references the egress guard
  (`apply_egress_guard` / `egress_guard_teardown`) and `registry.register("firewall"`.
  Replace the four override-specific tests in `tests/test_eval_cybergym_x_score.py`
  (`test_override_file_is_internal_only`, `test_compose_file_args`,
  `test_resolved_config_is_internal_isolated`, `test_override_adds_only_internal_key`)
  accordingly; weaken no other assertion.

## §3 Seal-tax (`tests/test_commit_authority.py`)

Whole-window seal tax, surgical, weakening no other assertion:

1. **Seal the R10NET window** (PR #67) to its merge SHA: add
   `R10NET_MERGE = "be30b9e"` and change the open assertion
   `set(names(f"{R10NET_BASE}..HEAD")) <= R10NET_SECTION_10` to
   `set(names(f"{R10NET_BASE}..{R10NET_MERGE}")) <= R10NET_SECTION_10`.
2. **Open the R10 egress-guard window:** add `R10EG_BASE = "be30b9e"` and
   ```
   R10EG_SECTION_10 = {
       "SPEC_BRIEF_R10_egress_guard.md",
       "src/kronos/eval/cybergym_x_score.py",
       "src/kronos/eval/cybergym_internal_net.override.yml",  # deleted; still in diff
       "src/kronos/eval/egress_guard.py",
       "tests/test_eval_cybergym_x_score.py",
       "tests/test_egress_guard.py",
       "tests/test_commit_authority.py",
   }
   ```
   and assertion `set(names(f"{R10EG_BASE}..HEAD")) <= R10EG_SECTION_10`.

## §4 Hard boundaries

- `cybergym/**`, `.claude/**`, `.github/**`, `docs/governance/**`, and the signed
  manifest are NEVER-edit. The guard never edits `cybergym/**`; it reuses
  `cybergym.selftest.compose` / `wait_for_services` by import only and filters at
  the host, outside the lab target.
- NO live execution of any kind in this step: no `iptables`/`nft` apply, no
  `docker compose up`, no container stand-up, no `§6/§8` R10 run, no real
  credentials, no network.
- The guard mutates host firewall state ONLY when `run()` is later executed under a
  separate `§6/§8` authorization; this step neither applies nor removes a real rule.
- Exactly the seven files in §3 `R10EG_SECTION_10` may be touched.

## §5 Acceptance (§8 criteria)

- Exactly the seven files in `R10EG_SECTION_10` on branch
  `kronos/r10-egress-guard`; nothing else touched; no `cybergym/**`, `.claude/**`,
  `.github/**`, or governance file changed.
- `internal:true` injection fully gone: override file deleted, `OVERRIDE_PATH` /
  `_compose_file_args` removed, `run()` reverted to direct `compose(...)`.
- `egress_guard.py` implements apply/remove/discover/teardown-factory with the §1
  idempotency, scoping, and rollback semantics; `run()` registers the guard
  teardown before applying it.
- All §2 hermetic tests present and the full canonical suite is **0 failed** via
  `TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" rtk test .venv/bin/python -m pytest -q`,
  decided on the runner SUMMARY line, never `$?`.
- Seal-tax §3 applied; scope audit green.
- No live run, no firewall apply, no container stand-up.

## §6 Risks

- (a) The real container subnet is assigned by Docker at `up` time and discovered
  at runtime; hermetic tests mock discovery. RESOLVED-by-design: `discover_subnet`
  is a thin, tested shell around `docker network inspect`; the live value flows into
  apply/remove only when `run()` is later executed under `§6/§8`.
- (b) Each scoped jump (`DOCKER-USER`, `INPUT`) must be scoped by `-s <subnet>` or it would also filter
  host-sourced traffic. The capability-preservation tests fail-close on any rule not
  so scoped, and on any flush/delete of `DOCKER-USER`, `INPUT` or a foreign chain.
- (c) Re-apply must not duplicate the jump. Check-before-insert (`-C || -I`) and
  per-rule `-C || -A` (no flush of the live chain, so no fail-open window) make
  `apply_egress_guard` idempotent; dedicated tests prove it.
- (d) Removal must survive timeout/interruption. The guard teardown is registered
  with `CleanupRegistry`, whose `__exit__` runs teardown on normal return and on any
  propagating `Exception`/`BaseException`; a test proves removal under each.

## §7 Non-goals

Any live firewall apply or real `iptables` mutation, any `docker compose up` or
container stand-up, the `§6/§8` R10 run itself, any real X-score measurement, any
`cybergym/**` edit, R12 (BE-G2-6), and any other `src/kronos/**` change are OUT of
scope. They belong to the separately authorized `§6/§8` run step.
