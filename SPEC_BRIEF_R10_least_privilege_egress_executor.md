# SPEC_BRIEF R10 — LEAST-PRIVILEGE EGRESS-GUARD EXECUTOR (remediation, BUILD only)

Governance: `docs/governance/KRONOS_RND_CONTRACT.md` canonical and sole-binding. This brief operationalizes it and never redefines a gate.

Authorization state (read before anything):
- Baseline: live `origin/main` = `93e1743cc38f9004e8c751160e2c15ef9502342d` (protected ruleset `void-rule-kronos` 25333712 active).
- GATE-1 authorization: build a least-privilege R10 egress-guard executor (remediation for seq 465 HOLD: the single authorized run cannot apply the bounded host-egress guard because `iptables` requires root and the run user is non-root with no passwordless sudo).
- **This brief authorizes NO execution.** No helper installation, no sudoers modification, no container start, no firewall mutation, no target access, no §6/§8 run, and NO rerun of R10. All deliverables are branch-local, reversible, hermetically tested. Stop at GATE-2 with a draft PR.

## §0 Root-cause recap (binding on design)
`src/kronos/eval/egress_guard.py` calls `iptables -w …` directly in-process. Under a non-root run that fails `Permission denied (you must be root)`, and the mandatory egress containment cannot be applied — so the run HARD-STOPs (seq 465). Remediation: keep the privileged iptables capability behind a single fixed, root-owned, sudoers-whitelisted helper exercising only three validated verbs on the fixed `KRONOS-CYBERGYM-EGRESS` boundary; route the run through it when non-root, direct in-process when already root. No capability is widened: the run user may only ask the helper to apply/remove/status the one fixed chain with IPv4-validated subnet/gateway, never raw iptables.

## §1 Deliverables (permitted files, exact)
1. `scripts/kronos-cybergym-egress` — root-owned install SOURCE; self-contained stdlib-only helper. Verbs: `apply <subnet> <gateway>`, `remove <subnet>`, `status`. Strict IPv4 validation; fixed chain only; absolute iptables path (no PATH lookup, no shell); never flushes `DOCKER-USER`/`INPUT`/foreign chains; idempotent by return codes; guaranteed teardown on `remove`; fail-closed. Does NOT import the repo package.
2. `src/kronos/eval/egress_executor.py` — privilege router. `egress_op(op, subnet=None, gateway=None)`: root → in-process `egress_guard`; non-root → `sudo -n /usr/local/sbin/kronos-cybergym-egress <verb> [validated args]` (no shell, no raw iptables args). `egress_teardown(subnet)` → CleanupRegistry callable. Validates verb + IPv4 before dispatch.
3. `src/kronos/eval/egress_guard.py` — ADD read-only `status_egress_guard()` only (chain present/absent). No other change; no existing behaviour altered.
4. `src/kronos/eval/cybergym_x_score.py` — rewire the egress steps ONLY to the executor: import `egress_op`/`egress_teardown`; the `cybergym-egress` teardown registers `egress_teardown(subnet)`; the apply step calls `egress_op("apply", subnet, gateway)`. `assert_ipv4_only`/`discover_subnet`/`discover_gateway` unchanged. No other logic touched.
5. `deploy/sudoers.d/kronos-cybergym-egress` — sudoers TEMPLATE (not installed). Whitelists only the installed absolute helper path + three verbs for `RUNUSER`; documents that the helper re-validates.
6. `docs/ops/R10_EGRESS_HELPER_INSTALL.md` — human install / verify / rollback / uninstall runbook (root-owned install, 0755 helper / 0440 sudoers, `visudo -c`, verify, rollback via `remove`, uninstall).
7. `tests/test_egress_helper.py` — hermetic proofs (see §2).
8. `tests/test_commit_authority.py` — seal-tax only (see §3).
9. `tests/test_eval_cybergym_x_score.py` — update the two run-source wiring-guard assertions from the old egress symbols to `egress_op("apply", …)` / `egress_teardown`; intent (presence + ordering) preserved.

## §2 Test obligations (hermetic; `tests/test_egress_helper.py`)
No real iptables/docker/sudo/network. Prove: (a) ARGUMENT REJECTION — unknown verb, wrong arg count, non-IPv4 subnet/gateway, IPv6, injection strings, flag/chain-name as arg → non-zero, no mutating iptables call; (b) FOREIGN-CHAIN PROTECTION — `-F`/`-X`/`-N` only ever target `KRONOS-CYBERGYM-EGRESS`, never `DOCKER-USER`/`INPUT`/foreign; (c) NO CAPABILITY EXPANSION — non-root `egress_op` uses `sudo -n <HELPER_PATH>` with the fixed verb only, never `shell=True`, never `iptables` in argv; root path calls in-process and never spawns sudo; (d) APPLY/REMOVE IDEMPOTENCY — second apply is a no-op, remove-when-absent is `already_gone`, roundtrip returns to `absent`; (e) FAILURE CLEANUP — a mid-apply iptables failure is fail-closed and the chain is still removable; (f) PARITY — helper `_chain_rules` equals `egress_guard._chain_rules`.

## §3 Seal-tax (`tests/test_commit_authority.py`)
Seal the open R10EVAL window and open this brief's window:
1. Add `R10EVAL_MERGE = "93e1743cc38f9004e8c751160e2c15ef9502342d"`.
2. Change the open assertion `set(names(f"{R10EVAL_BASE}..HEAD")) <= R10EVAL_SECTION_10` → `…{R10EVAL_BASE}..{R10EVAL_MERGE}…` (sealed).
3. Append a NEW window `LPEG_BASE = "93e1743cc38f9004e8c751160e2c15ef9502342d"`, `LPEG_SECTION_10 = {` the deliverable paths above plus `tests/test_eval_cybergym_x_score.py` and `tests/test_commit_authority.py` `}`, and open assertion `set(names(f"{LPEG_BASE}..HEAD")) <= LPEG_SECTION_10`. No existing assertion weakened, removed, or reordered.

## §4 Hard boundaries (NEVER edit by loop)
`cybergym/**`, `.claude/**`, `.github/**`, `docs/governance/**` (incl. the signed manifest + `contract_manifest.json`), `manifest.py` / `src/kronos/manifest.py`. No helper install, no sudoers install, no firewall/network mutation, no container, no target, no §6/§8 run, no R10 rerun.

## §5 Acceptance
PASS: all files in LPEG_SECTION_10 present as specified; `tests/test_egress_helper.py` and the full canonical suite green via `TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" rtk test .venv/bin/python -m pytest -q` (0 failed, decided from the SUMMARY line); `test_B31_Q_scope_audit` green; diff scope == exactly the files enumerated in LPEG_SECTION_10 (tests/test_commit_authority.py §3); no hard-boundary file touched; independent reviewer PASS; draft PR opened; stopped at GATE-2 with no install/run.

## §6 Risks / residuals (confirm at the gated §6/§8 run)
- sudoers argument wildcards (`apply *`) are coarse (LOW); the helper's strict internal validation is the authoritative boundary (documented in the template). - The helper duplicates the chain-rule logic (cannot import writable repo code and stay root-safe); parity is enforced by test. - Rewiring `cybergym_x_score.py` is a run-path change; it is behaviour-preserving when root (in-process) and only adds the non-root helper route. - `_state` treats iptables rc 2 as "absent" (LOW, inherited unchanged from the already-merged `src/kronos/eval/egress_guard.py`): a transient rc 2 could make `status`/`remove` report `absent`/`already_gone` while the chain persists — a FALSE-STATUS risk (guard stays applied, no egress escape), to confirm against real iptables at the run. - Subnet acceptance uses `ipaddress.is_private` (rejects all public-routable ranges and `0.0.0.0/0`); it also admits a few non-RFC1918 private ranges (e.g. `127.0.0.0/8`, `169.254.0.0/16`), none public-routable, so containment holds.

## §7 Non-goals
Not this brief: installing the helper or sudoers; running or rerunning R10; mutating the firewall; the §6/§8 evaluation; reconciling stale `SRC-ROADMAP`/`SRC-RESEARCH`; editing the DoD done-predicate.

## §8 AMENDMENT — pin to one lab subnet, fail-closed removal (GATE-1, Option (b), BUILD only)

Authorization: operator decision Option (b) — residuals **R1 and R2 are REJECTED** as merge residuals. GATE-1 authorizes amending PR #74 (branch `eval/r10-leastpriv-egress-executor`, base main `93e1743`) before merge. Still BUILD-only: no merge, no helper install, no sudoers/firewall/network mutation, no container, no target access, no §6/§8 run. Carry the R10EVAL seal at `93e1743`; the LPEG window stays open `93e1743..HEAD` and the amended diff must remain within `LPEG_SECTION_10` (scope audit green).

### §8.1 Pinned installed state (closes R1)
The helper no longer accepts a caller-supplied subnet/gateway. It reads the single authorized boundary from **root-owned, non-user-writable installed state** `/etc/kronos-cybergym/egress.conf`, mode `0644` root:root, three keys:
```
subnet=<private IPv4 CIDR, from the signed scope_manifest.yaml / compose ipam>
gateway=<IPv4 host address inside subnet>
network=<the Docker network name the lab Compose pins (e.g. cybergym_default)>
```
The human operator writes this file at install time from the signed manifest / compose (the install runbook instructs exactly how). The run user is never granted write access to it. On a missing, unreadable, or malformed config the helper **fails closed**: non-zero exit, no `iptables` call. The helper rejects every other subnet, project, chain, hash, path, environment variable, and argument — nothing but the three pinned values can direct it.

### §8.2 Zero-argument verbs (closes R1 + the sudoers wildcard)
Helper verbs are exactly `apply`, `remove`, `status` with **no positional arguments**; `apply`/`remove`/`status` derive subnet/gateway/network solely from the pinned config. Any extra argument, unknown verb, flag, or chain name is rejected with no mutation. The sudoers template is tightened to whitelist the three fixed commands with **no wildcard**:
```
RUNUSER ALL=(root) NOPASSWD: /usr/local/sbin/kronos-cybergym-egress apply, /usr/local/sbin/kronos-cybergym-egress remove, /usr/local/sbin/kronos-cybergym-egress status
```
The executor's non-root path invokes `sudo -n <HELPER_PATH> <verb>` with no subnet argument; its existing `egress_op("apply", subnet, gateway)` / `egress_teardown(subnet)` call signatures are **unchanged** (the non-root branch simply does not forward subnet/gateway to the helper argv), so `cybergym_x_score.py` and `tests/test_eval_cybergym_x_score.py` are not touched.

### §8.3 Fail-closed removal while the lab is live (closes R2)
`remove` may run **only after Compose teardown**. Before touching iptables it performs a **read-only** `"<docker>" network inspect <pinned network> --format "{{len .Containers}}"` using an absolute docker binary resolved from a fixed candidate list (`/usr/bin/docker`, `/usr/local/bin/docker`), never via `PATH`, and **creates no container or network** (honors "no discovery provisioning"). Decision table, fail-closed by default:
- network absent (inspect reports no such network) → lab torn down → removal of the exact recorded guard is allowed;
- network present with `0` attached containers → allowed;
- network present with `>=1` attached container/endpoint → **REFUSE** (fail closed);
- docker binary absent, inspect errors, or output unparseable → **REFUSE** (fail closed).
Removal only ever targets the exact recorded `KRONOS-CYBERGYM-EGRESS` guard for the pinned subnet; it never flushes `DOCKER-USER`, `INPUT`, or any foreign chain. The runbook documents a manual root `iptables` override for the (misconfigured-host) docker-absent edge.

### §8.4 rc=2 fail-closed (closes R3) — refined, apply-preserving
The false-absent risk is that `status`/`remove` report `absent`/`already_gone` while the chain actually persists (a transient rc `2` masking a present chain). The fix must close that **without** making a legitimate `apply`/`remove` refuse on a host where a genuinely-absent chain returns rc `2` (a real condition the existing `tests/test_egress_guard.py` models with `FakeIptables(missing_chain_rc=2)`, and R6 flags as unverifiable off-host). Therefore, in both the helper and `src/kronos/eval/egress_guard.py`:
- **`apply` stays tolerant:** its presence-probe treats a non-zero `-C` (rc 1 **or** rc 2) as "not confirmed present → add", because adding is idempotent and safe. `apply` behavior is unchanged.
- **`status` never returns `absent` on rc 2:** only a clean rc `1` is reported `absent`; rc `2` (and any other non-zero) is reported as an **error / `unknown`**, never `absent` — fail-closed for status truthfulness.
- **`remove` never claims success on rc 2:** `removed`/`already_gone` is claimed only on a positive rc `1` confirmation that the chain is gone; an rc `2` yields an **error** (the guard is treated as possibly-still-applied), never `already_gone`.

**Scope decision (orchestrator, Option A):** this changes the shared merged `egress_guard._state`/status/remove semantics, which breaks three rc 2 tests in `tests/test_egress_guard.py` (`test_rc2_remove_on_clean_host_is_already_gone`, `test_rc2_apply_installs_full_chain` — may survive since apply stays tolerant —, `test_rc2_mid_apply_failure_leaves_nothing_after_teardown`). That file is therefore **added to `LPEG_SECTION_10`** in `tests/test_commit_authority.py`, and its rc 2 tests are rewritten to assert the new behavior: `apply` still builds the chain on an rc 2 host; `status` returns `unknown`/error (not `absent`) on rc 2; `remove` returns an error (not `already_gone`) on rc 2. Update the `_state` comment (egress_guard.py ~lines 45-46) to match. No other assertion in that file is weakened or reordered.

### §8.5 Gateway validation (closes R8)
`apply` requires the pinned gateway to be a host address **strictly inside** the pinned subnet — not the network address, not the broadcast address — in both helper and `egress_executor.py`. A gateway equal to the network or broadcast address, or outside the subnet, is rejected with no mutation.

### §8.6 Uninstall gating (closes R7)
The install runbook's uninstall sequence gates `rm -f` of the helper/sudoers on a confirmed `status` = `absent` after a successful `remove`; it never removes the helper while the guard is still applied or after a failed `remove`. The pinned config is removed last, only once the guard is absent.

### §8.7 Adversarial test obligations (`tests/test_egress_helper.py`, hermetic)
No real iptables/docker/sudo/network. Add proofs that: a caller cannot supply or override subnet/gateway/network (positional args rejected); a config pointing at a different/foreign subnet is still confined to the pinned one (the helper uses the config, not caller input); missing/malformed/unreadable config fails closed with no iptables call; `remove` with the pinned network still showing `>=1` container **refuses** (fail closed), with docker-absent/inspect-error **refuses**, and only with network-gone/`0`-containers proceeds and removes the exact recorded guard; rc `2` yields error/fail-closed (never `absent`/`already_gone`) in helper and `egress_guard._state`; gateway equal to network or broadcast is rejected; the sudoers template carries no wildcard and `visudo -cf` parses it on a substituted scratch copy; `remove` never targets `DOCKER-USER`/`INPUT`/foreign. Mock the docker `network inspect` call (stateful) and iptables as in the existing hermetic harness.

### §8.8 Acceptance
All §8 behaviors implemented within `LPEG_SECTION_10`; `tests/test_egress_helper.py` and the full canonical suite green via `TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" rtk test .venv/bin/python -m pytest -q` (0 failed, decided from the SUMMARY line); `test_B31_Q_scope_audit` green; diff scope ⊆ `LPEG_SECTION_10` and no hard-boundary file touched; fresh independent security review PASS at the new exact head; amended PR pushed; stop at GATE-2 with no merge/install/run.
