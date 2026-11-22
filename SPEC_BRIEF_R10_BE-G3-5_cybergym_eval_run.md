# SPEC_BRIEF R10 / BE-G3-5 — ONE MANIFEST-BOUNDED CYBERGYM EVALUATION RUN (committed evidence)

Governance: `docs/governance/KRONOS_RND_CONTRACT.md` canonical and sole-binding. This brief operationalizes it and never redefines a gate.

Authorization state (read before anything):
- Baseline: live `origin/main` = `dab9b24d4c838c642b4a2e366b22fc3b0ee45fdb` (protected ruleset `void-rule-kronos` 25333712 active).
- GATE-1 **planning** authorization granted by the maintainer (2026-11-22) to PREPARE this brief only.
- **This brief authorizes NO execution.** The run it specifies is a §6/§8 live action that requires a SEPARATE, explicit maintainer GATE-1 execution authorization AND GATE-2 before any container, firewall rule, or tool is invoked. Drafting, reviewing, and sealing this brief are branch-local, reversible, non-live.
- Milestone: `docs/governance/KRONOS_DONE.md:50` — `BE-G3-5` is **OPEN**: "one authorized, manifest-bounded CyberGym/lab run output committed in-repo." DoD is the authoritative milestone state. The pinned roadmap/research-record (`SRC-ROADMAP`, `SRC-RESEARCH`) are STALE (still stamped old main `78dcb76`, still mark BE-G1-5/6/7 MISSING); they are NOT authoritative for completion and their reconciliation is a separate maintainer governance patch — do not rely on them.

## §0 Root-cause recap (binding on design)
BE-G3-5 requires the committed artifact of exactly ONE authorized, manifest-bounded CyberGym/lab run. All implementation is already merged and hermetically tested: the bounded host-egress guard (`src/kronos/eval/egress_guard.py`, PR #68/#69), the run wrapper (`src/kronos/eval/cybergym_x_score.py`), the local-only lab stack (`cybergym/docker-compose.yml`), the evidence schema (`evaluation_evidence/cybergym-x-score/run_summary.schema.json`), and the redaction/export gate. What is missing is solely the live run and its committed, redacted evidence set. No new product code is required by this brief; if the execution turn finds a thin invocation runner is needed, that is itself a scoped follow-up, not part of this planning brief.

## §1 Authorized target, manifest, scope (exact)
- **Target: local-only lab, no external/public target.** Every service binds `127.0.0.1` (`cybergym/docker-compose.yml:1-3,15,40,52`). Services: `localstack`, `init-buckets`, `sigv4-proxy`, `api`. No real cloud account, no real credentials; every "secret" is a fake fixture.
- **Signed scope manifest (pinned, read-only):** `cybergym/scope_manifest.yaml` raw sha256 `3961c4331133749d4464ba98e038728b5c2db5a12c92e5e207d9864ee1622947`; pubkey `cybergym/scope_manifest_pubkey.pem` raw sha256 `769416bc28aa9dda57ea89cf1e8cf78b5fc89fdc58f0ce5ab7607bb1e2d3e804`; compose `cybergym/docker-compose.yml` raw sha256 `f902808c43f5decf7d5ab061d13d8558b89ffa7cc127ff8b249c598a00834f3f`.
- **Engagement:** `id=cybergym-x-instrument-v1`, `destructive_allowed=false`, window `2026-01-01 .. 2125-12-08` (`cybergym/scope_manifest.yaml:1-7`).
- **In-scope globs only:** `com.kronos.cybergym.*`, `localhost*`, `127.0.0.1*`, `http://localhost*`, `http://127.0.0.1*`, `kronos-cybergym-*`, `arn:aws:s3:::kronos-cybergym-*` (`cybergym/scope_manifest.yaml:8-17`). Excluded: none listed; anything outside in_scope is out of scope.
- **Runtime manifest binding:** the wrapper computes `manifest_id = compute_manifest_id(load_and_verify(manifest_text, pubkey))` (`src/kronos/eval/cybergym_x_score.py:165-167`, `src/kronos/manifest.py:199-258`), which is `"sha256:" + sha256(canonical_content)`. `load_and_verify` raises `ManifestError` on bad signature or outside the time window BEFORE a `manifest_id` exists. The resulting `manifest_id` and `manifest_engagement_id` are embedded in `run_summary.json`. The execution turn MUST record the observed `manifest_id` as evidence; it is the cryptographic proof the run was manifest-bounded.

## §2 Commands / tools and their exact order (for the execution turn; NOT run now)
The ONLY entrypoint is the already-merged wrapper path. The execution turn runs, in order:
1. Preflight (read-only, §4): confirm the three pinned sha256 above match on-disk; confirm Docker present and the host firewall preflight (§5) passes; confirm no stale `KRONOS-CYBERGYM-EGRESS` chain exists.
2. `assert_ipv4_only("cybergym_default")` then `discover_subnet`/`discover_gateway` (`cybergym_x_score.py:241-251`) — IPv6 on the network is a fail-closed STOP (`egress_guard.py` raises `RuntimeError` unless `EnableIPv6==false`).
3. Register teardown callbacks BEFORE applying anything (LIFO): compose-down `cybergym-range-stack` and firewall `cybergym-egress` (`cybergym_x_score.py:235-251`). Register-before-apply guarantees rollback of a partial apply.
4. `apply_egress_guard(subnet, gateway)` — idempotent, fail-closed reconcile; NEVER flushes `DOCKER-USER`/`INPUT`/foreign chains.
5. `compose("up", "-d", "--build")` then `wait_for_services(timeout=90)` (`cybergym/selftest.py:262-263,266-278`).
6. The instrument run (`run()` in `cybergym_x_score.py`), producing `x_score`, `chains`, `budget`.
7. `export_redacted` → committed evidence set; `assert_redacted` gate must pass.
8. Teardown always runs (CleanupRegistry): `compose("down", "-v")` + `remove_egress_guard(subnet)`, recorded in `teardown_report.json` with `all_ok=true`.
No other tool, script, or network call is authorized. No `iptables`/`nft` invocation outside `egress_guard.py`'s own functions. No manual container commands.

## §3 Credentials policy
No real credentials exist or are used. The lab's "secrets" are fake fixtures (`kvr.CHAIN1_SECRET_VALUE`, `CHAIN2_SECRET_VALUE`, and a chain3 value derived from `cybergym/mobile/apk_src/...`). The committed evidence MUST pass `assert_redacted` (`cybergym_x_score.py:123-131`), which fail-closes on any fixture needle or the literal header `X-Cybergym-Key`. Raw secret/needle plaintext and the raw evidence blobs are NEVER committed — only the redacted set (§6). Per project memory, CyberGym `evidence/` raw plaintext is committed NEVER; only the redacted `evidence_manifest` set.

## §4 Egress boundary, host/firewall preflight, kill switch, rollback, teardown, timeout
- **Egress boundary:** bounded host `DOCKER-USER`/`INPUT` chain `KRONOS-CYBERGYM-EGRESS` scoped to the container subnet only (`egress_guard.py:30-31,124-128`): allow `ESTABLISHED,RELATED` RETURN; DROP gateway `/32`; RETURN subnet and `127.0.0.0/8`; final DROP. No `networks.internal:true` (that killed host 127.0.0.1 publishing — see project history); egress is contained at the host firewall instead.
- **Host/firewall preflight (execution turn, before apply):** no pre-existing `KRONOS-CYBERGYM-EGRESS` chain; `iptables -w` lock-wait available; IPv4-only network; expected chain rule-set matches `egress_guard.py:124-128` exactly (reconcile is fail-closed — mismatch raises, never flushes).
- **Kill switch / timeout:** `wait_for_services(timeout=90)` raises `TimeoutError` if services do not come up; any exception, timeout, or KeyboardInterrupt propagates into CleanupRegistry which runs full teardown (`SPEC_BRIEF_R10_egress_guard.md:95-96`).
- **Rollback / teardown:** CleanupRegistry runs teardown on normal return, any `Exception`, and propagating `BaseException`; LIFO so firewall removal and `compose down -v` both execute; `teardown_report.json.all_ok` must be `true` (schema `run_summary.schema.json:44-48`). On ANY export failure the committed dir is `shutil.rmtree`'d (`cybergym_x_score.py:281-282`) — no partial evidence.

## §5 Evidence paths and committed-evidence requirements
- **Schema:** `evaluation_evidence/cybergym-x-score/run_summary.schema.json`. Required `run_summary.json` fields: `run_id, instrument, k, x_score, manifest_id, manifest_engagement_id, lab, chains, started_at, ended_at, kronos_commit, budget, teardown`.
- **Committed redacted set ONLY** (exactly these four, under the maintainer-defined evidence dir): `run_summary.json`, `budget_ledger.json`, `teardown_report.json`, `evidence_manifest.json` (`tests/test_eval_cybergym_x_score.py:144,277`). `evidence_manifest.json` lists `{sha256, kind, size}` per file (`cybergym_x_score.py:106-120`); raw blobs are NOT committed.
- **Maintainer-defined placeholder:** `KRONOS_DONE.md:50` leaves the exact committed path/schema "maintainer-defined." This brief proposes the committed dir `evaluation_evidence/cybergym-x-score/run-<run_id>/` holding the four files; the maintainer confirms or overrides the exact path at the execution GATE. The DoD done-predicate wiring (which PR + which path/test proves BE-G3-5) is a `docs/governance/**` edit = maintainer patch, NOT part of this loop brief.

## §6 Acceptance criteria (§8) for the EXECUTION turn (not satisfiable now)
PASS requires, by evidence: (1) the run completed under the verified signed manifest with a recorded `manifest_id`/`manifest_engagement_id`; (2) the four redacted evidence files committed, validating against `run_summary.schema.json`; (3) `assert_redacted` passed — zero fixture needles / `X-Cybergym-Key` in any committed file; (4) `teardown.all_ok == true`; (5) full hermetic suite green via the canonical runner `TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" rtk test .venv/bin/python -m pytest -q` (decide from the SUMMARY line, never `$?`); (6) no out-of-scope / hard-boundary file touched. Local-only; no public target required.

FAIL / ABORT (the execution turn STOPS and commits NO evidence, teardown still runs): any of — manifest verification fails or is outside the window (`ManifestError`); the network is not IPv4-only or `assert_ipv4_only` raises; a pre-existing `KRONOS-CYBERGYM-EGRESS` chain is found or `apply_egress_guard` reconcile raises (mismatch, never flush); `wait_for_services` `TimeoutError` (90s); `assert_redacted` raises on any committed candidate (redaction violation); `teardown.all_ok != true`; the canonical suite reports any failure; or any attempt to touch an out-of-scope / hard-boundary path. On any such failure the committed dir is removed (`cybergym_x_score.py:281-282`), teardown runs via CleanupRegistry, and the turn emits a BLOCKED stop-report — it never commits a partial or unverified evidence set.

## §7 Seal-tax (`tests/test_commit_authority.py`) — part of THIS brief
Seal the open PRG window and open this brief's window:
1. Add `PRG_MERGE = "dab9b24d4c838c642b4a2e366b22fc3b0ee45fdb"`.
2. Change the open assertion `set(names(f"{PRG_BASE}..HEAD")) <= PRG_SECTION_10` → `set(names(f"{PRG_BASE}..{PRG_MERGE}")) <= PRG_SECTION_10` (sealed).
3. Append a NEW window: `R10EVAL_BASE = "dab9b24d4c838c642b4a2e366b22fc3b0ee45fdb"`, `R10EVAL_SECTION_10 = {"SPEC_BRIEF_R10_BE-G3-5_cybergym_eval_run.md", "tests/test_commit_authority.py"}`, and open assertion `set(names(f"{R10EVAL_BASE}..HEAD")) <= R10EVAL_SECTION_10`. No existing assertion weakened, removed, or reordered.

## §8 Hard boundaries (NEVER edit by loop)
`cybergym/**`, `.claude/**`, `.github/**`, `docs/governance/**` (incl. `KRONOS_DONE.md`, the signed manifest + pubkey, `contract_manifest.json`), `manifest.py` / `src/kronos/manifest.py`. The DoD done-predicate for BE-G3-5 and any reconciliation of the stale pinned roadmap/research sources land ONLY via maintainer governance patch. No network use outside the authorized run.

## §9 Non-goals
Not this brief: BE-G2-6 (R12) live LLM run (blocked on BE-G3-5); reconciling stale `SRC-ROADMAP`/`SRC-RESEARCH`; editing the DoD done-predicate; any new product code; executing the run.
