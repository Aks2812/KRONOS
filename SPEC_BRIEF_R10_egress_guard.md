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
readiness check and validation pass depend on. The fix must deliver **structural
zero container egress** WITHOUT removing host→container `127.0.0.1` publishing.

A host-level `DOCKER-USER` filter achieves this: `DOCKER-USER` is consulted in the
`FORWARD` path (container-routed traffic). A DROP scoped by `-s <container_subnet>`
matches only packets *sourced from* the CyberGym containers. Host→container
published-port traffic (DNAT + loopback, host-sourced) never carries the container
subnet as source, so it never enters the guard and is never dropped — the
capability `internal:true` broke is preserved by construction.

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
   - `apply_egress_guard(subnet: str) -> None`: idempotent. Creates the dedicated
     chain `KRONOS-CYBERGYM-EGRESS` if absent, flushes it to a known state, and
     populates it IN ORDER: `-m conntrack --ctstate ESTABLISHED,RELATED -j RETURN`;
     `-d <subnet> -j RETURN` (intra-network); `-d 127.0.0.0/8 -j RETURN`
     (host/loopback); `-j DROP` (all other egress). Then installs a single jump
     `DOCKER-USER -s <subnet> -j KRONOS-CYBERGYM-EGRESS`, check-before-insert
     (`iptables -C ... || iptables -I ...`) so a re-apply never duplicates it.
     NEVER flushes `DOCKER-USER` or any chain but `KRONOS-CYBERGYM-EGRESS`; NEVER
     touches a rule it did not create.
   - `remove_egress_guard(subnet: str) -> str | None`: idempotent rollback. Deletes
     the scoped `DOCKER-USER` jump if present, then flushes and deletes the
     `KRONOS-CYBERGYM-EGRESS` chain. Treats an already-absent jump/chain as success
     (returns `"already_gone"` when nothing was present, `None` otherwise); raises
     only on a genuine, unexpected `iptables` failure.
   - `egress_guard_teardown(subnet: str) -> Callable[[], str | None]`: returns the
     zero-arg teardown callable (`lambda: remove_egress_guard(subnet)`) in the
     `kronos.cleanup` kind contract, for `CleanupRegistry.register("firewall", …)`.
   - Every live op shells `iptables` through one small private runner that maps
     already-exists / no-such-chain / no-such-rule stderr to the idempotent
     outcome, mirroring `kronos/cleanup/kinds.py:_run_docker`.
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
  sequence; assert chain create → flush → the four rules in the specified order →
  scoped jump installed check-before-insert.
- **Idempotent apply:** two consecutive `apply_egress_guard` calls produce no
  duplicate jump (the `-C` check suppresses the second `-I`) and a re-flushed chain
  (no duplicate rules).
- **Lifecycle (remove) + idempotence:** `remove_egress_guard` deletes the jump,
  flushes and deletes the chain; a second call (nothing present) returns
  `"already_gone"` and raises nothing.
- **Rollback on all paths:** via a real `CleanupRegistry` with a mocked guard,
  assert removal runs (a) on normal exit, (b) when the `with` body raises a normal
  `Exception`, and (c) when it raises a `BaseException` (timeout/interrupt proxy);
  assert LIFO places firewall-removal before `compose down`.
- **Capability preservation (construction proof):** assert every DROP/filter rule
  in the guard is reachable only via the `-s <subnet>` jump (so host-sourced
  `127.0.0.1` traffic is never matched); assert `-d 127.0.0.0/8 -j RETURN` and
  `-d <subnet> -j RETURN` precede the final `-j DROP`; assert no command flushes or
  deletes `DOCKER-USER` or any non-`KRONOS-CYBERGYM-EGRESS` chain (existing firewall
  rules preserved).
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
- (b) A `DOCKER-USER` jump must be scoped by `-s <subnet>` or it would also filter
  host-sourced traffic. The capability-preservation tests fail-close on any rule not
  so scoped, and on any flush/delete of `DOCKER-USER` or a foreign chain.
- (c) Re-apply must not duplicate the jump. Check-before-insert (`-C || -I`) plus a
  per-apply chain flush make `apply_egress_guard` idempotent; a dedicated test
  proves it.
- (d) Removal must survive timeout/interruption. The guard teardown is registered
  with `CleanupRegistry`, whose `__exit__` runs teardown on normal return and on any
  propagating `Exception`/`BaseException`; a test proves removal under each.

## §7 Non-goals

Any live firewall apply or real `iptables` mutation, any `docker compose up` or
container stand-up, the `§6/§8` R10 run itself, any real X-score measurement, any
`cybergym/**` edit, R12 (BE-G2-6), and any other `src/kronos/**` change are OUT of
scope. They belong to the separately authorized `§6/§8` run step.
