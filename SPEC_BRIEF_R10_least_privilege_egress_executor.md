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
