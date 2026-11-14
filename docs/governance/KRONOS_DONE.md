# KRONOS Definition of Done

DoD-Version: 1.4.4
DoD-Model: Beta-Entry DoD v1

This artifact is the sole durable, version-pinned Definition of Done (DoD) for KRONOS R&D. It is
bound into `docs/governance/contract_manifest.json`'s hashed file set, so its integrity is checked
fail-closed at start-of-turn. Contract `docs/governance/KRONOS_RND_CONTRACT.md` §13.4 and §14 are the
sole semantic authority; this file enumerates the milestones and the completion predicate they gate.
The milestone content below was adopted by operator decisions D1–D9 on `B54_COMPLETION_DECISION_PACKET`
(2026-11-13); the goal wording is quoted from the pinned reconciliation sources.

## Goals and milestones

Each milestone carries a stable id and a binary done-predicate: the specific evidence that proves it.
Predicate forms, each binary and live-re-derivable at the emitting turn:

- **PR `<40-hex>`** — `git merge-base --is-ancestor <SHA> <live main HEAD>` exits 0 (the squash SHA is
  an ancestor of live main).
- **TEST `<node>`** — the named pytest node passes via the canonical runner
  (`TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/kronos/pytest-tmp" .venv/bin/python -m pytest -q`, decided
  from the runner summary line, never `$?`).
- **EVAL `<path>`** — the named evaluation artifact is present at the stated repo path and matches the
  stated check.

A milestone is DONE only when ALL its listed predicates re-derive live at the emitting turn. Per D8,
every PR-ancestry reference, test path, full test name, and green result in this file MUST be
re-verified by a builder verification pass before any Completion Record citing them is activated.

Goals (quoted verbatim from `docs/research/KRONOS_GOAL_FRAMED_REFERENCE_LEDGER_v1.md`, tracing to the
research record):

- **G1 — STRONGER:** "Build meaningful cross-domain capability, so KRONOS can connect evidence across
  web, infrastructure, mobile, API, and cloud."
- **G2 — MORE EFFECTIVE:** "Increase autonomous planning and execution within explicitly authorized
  scope and signed engagement limits."
- **G3 — FEWER FALSE POSITIVES:** "Make findings validation-gated, evidence-backed, and appropriately
  classified, with abstention when the evidence is insufficient."
- **Precedence:** G3 constrains G1 and G2 (a new domain that cannot produce two-armed evidence does
  not ship; autonomy never widens scope or relaxes a validation gate). G1 before G2 in sequencing.

### G3 (FEWER FALSE POSITIVES) — gates first

| Id | Milestone | Done-predicate |
|---|---|---|
| BE-G3-1 | Two-armed negative-control validation interface (S1) | PR `561cf2b965d9b0bf11c89fe8808018e549bb3ad1` AND TEST `tests/test_negative_controls.py::test_health_shaped_target_closed_end_to_end_on_the_graph` AND TEST `tests/test_negative_controls.py::test_true_positive_http_still_reaches_reachable_with_edge` |
| BE-G3-2 | CyberGym denial fidelity (S1 fix, research record §7.2) | PR `d6dc3264f3de4c63c4063e437b75491c8aadf60c` AND TEST `tests/test_cloud_validator.py::test_canonical_succeeds_and_both_controls_denied_is_live_discriminated` |
| BE-G3-3 | Evidence-gated findings with abstention | PR `7f5f46c3b51393666ca8a930b62810653757f579` AND PR `329194ca7498a4304c28c0e006a3f9aa54ea7129` AND TEST `tests/test_finding_evidence_gate.py` (all three tests) |
| BE-G3-4 | Transitive invalidation / staleness (S7) | PR `81796b4884559fc346f473e0595ca157cdc48c14` AND TEST `tests/test_invalidation.py::test_A_typed_causal_edge` AND TEST `::test_B_producer` AND TEST `::test_C_runner_wiring` |
| BE-G3-5 | Committed evaluation evidence for the five-domain run (**Beta-Entry required, D3**) | EVAL: one authorized, manifest-bounded CyberGym/lab run output committed in-repo; exact path and schema are maintainer-defined and do not exist yet (no public-target run required). OPEN. |

### G1 (STRONGER) — breadth

| Id | Milestone | Done-predicate |
|---|---|---|
| BE-G1-1 | Ingestion contract + canonical keys + owned event stream (S2) | PR `4a2da514a3882f82fd3255deb80969ca7bd1719a` AND TEST `tests/test_ingest_contract.py` AND TEST `tests/test_canonical_keys_s2.py` AND TEST `tests/test_events.py` |
| BE-G1-2 | Infra domain: ingestion + two-armed validation (S3, S4) | PR `19c94640e4921c80381ddef77a56400f4c048f95` AND PR `079a76f6014dba189a55c69bcd1878354954b50c` AND TEST `tests/test_infra_ingest.py` AND TEST `tests/test_infra_validator.py` |
| BE-G1-3 | Web domain: ingestion + two-armed validation (S5, S6) | PR `33ab362fd7c9a1b70fee246769536b7a1c41d579` AND PR `17d38a89cc45c2f3079829bf8f9e0b7955e5669c` AND TEST `tests/test_web_ingest.py` AND TEST `tests/test_web_validator.py` |
| BE-G1-4 | Mobile ingestion + shared-validator capability (mobile, and the HTTP/cloud validators) | TEST `tests/test_mobile_ingest.py` AND TEST `tests/test_http_validator.py` AND TEST `tests/test_cloud_validator.py`. **Scope (D1): this milestone is mobile ingestion plus shared-validator capability only; it does NOT satisfy standalone API ingestion (BE-G1-5) or cloud ingestion (BE-G1-6).** |
| BE-G1-5 | Standalone API ingestion, not mobile-sourced (**required, D4**) | TEST `tests/test_api_ingest.py` (to be created) AND source module `src/kronos/ingest/api/` present. OPEN; mobile-sourced API evidence is insufficient. |
| BE-G1-6 | Cloud ingestion → `CLOUD_RESOURCE`, `IDENTITY` (next increment, D7) | TEST `tests/test_cloud_ingest.py` (to be created) AND source module `src/kronos/ingest/cloud/` present. OPEN; initial hermetic source is the existing provider-neutral cloud-validator fixture/schema (no credentials, no SDK calls, no live cloud access). |
| BE-G1-7 | First usable milestone: five-domain evidence-validated engagement run | TEST `tests/test_five_domain_engagement.py` (to be created), asserting all five domains ingest into one graph and every resulting FINDING carries a two-armed proof, a verdict tier, and a control disposition. OPEN. |

### G2 (MORE EFFECTIVE) — autonomy over the breadth

Hermetic G2 work (BE-G2-1..BE-G2-5) is accepted retroactively as having landed ahead of G1
completion (D2). Live agent execution (BE-G2-6) is BLOCKED until BE-G1-7 and BE-G3-5 are satisfied.

| Id | Milestone | Done-predicate |
|---|---|---|
| BE-G2-1 | Inc 1: dispatcher skeleton + read-only planner, zero side effects | PR `f4559a27504769d24c942e298b9e92bd22626749` AND TEST `tests/test_agent_dispatcher.py::test_H_read_only_planner` AND TEST `::test_I_zero_side_effects` |
| BE-G2-2 | Inc 2: reviewer + rails as commit gate, no live execution | PR `a9f37ecc043b4e67ef923d76cb8e526692ef3cf5` AND TEST `tests/test_agent_reviewer.py::test_A_approved_happy_path` AND TEST `::test_B_no_upgrade_rail` AND TEST `tests/test_agent_commit.py` |
| BE-G2-3 | Inc 3: executor behind the gate, CyberGym range only | PR `5b7001dbd25a26004ef7081a701b8c81bf959454` AND TEST `tests/test_agent_executor.py::test_B_promotion_happy` AND TEST `::test_C_evidenceless_not_promoted` |
| BE-G2-4 | Inc 4+: loop-breaker, conclude-on-timeout, observability | PR `5803bcd1ddbea49019938c375c7531f338446df3` AND PR `1405ed739cec74e1a64dc1d40f21e0dab4f0d6b6` AND TEST `tests/test_agent_dispatcher.py::test_N_conclude_on_timeout` AND TEST `::test_O_run_summary` |
| BE-G2-5 | Durable stop + watchdog + commit authority (G2 control spine) | PR `a229b0dbcdea226f2679af34b19209fe82d8b347` AND TEST `tests/test_stop.py` AND TEST `tests/test_watchdog.py` AND TEST `tests/test_autonomy.py` AND TEST `tests/test_commit_authority.py` |
| BE-G2-6 | Live LLM-backed driver/executor reaching real validators (**Beta-Entry required, D3; BLOCKED until BE-G1-7 and BE-G3-5, D2**) | PR `056f4412f49959a5cbc49db4e27345299190d176` AND PR `73cbe8b106d1099796173bccff99d8189fa3aad2` (both hermetic) AND EVAL: artifact of one authorized, manifest-bounded live run (maintainer-defined; does not exist yet). OPEN. |

## Reconciliation-Sources

Pinned per contract §13.2/§13.4 as `<stable-id> <repo-path> <sha256>`. At incomplete-idle recovery and
at any turn reading these sources, the orchestrator re-derives each source's sha256 from disk and
compares to the pin: a missing source or a sha256 mismatch forces `HOLD` with exact remediation and
yields no candidate. Pins are of the in-repo copy only (no absolute-path authority); they are updated
only by maintainer patch to this file.

```
SRC-RESEARCH docs/research/KRONOS_RESEARCH_RECORD.md 7b00347661b1d96c9924c6e8bda501ad117a2861e415571637c4b3489dcfca5d
SRC-LEDGER docs/research/KRONOS_GOAL_FRAMED_REFERENCE_LEDGER_v1.md 6f2e0c6d5b7c040d2386bb27ebc015c906167dc5e9ec979322ea730c8a482e79
SRC-GAPMAP docs/research/sequence8-goal-gap-map.md a7602d33c16bba8fb544bc322aaa35dfae25c37174562816eb63d078feb03f4f
SRC-ROADMAP docs/roadmap/KRONOS_ROADMAP.md ad4256de5409d26dc1389829fe0b2fd637e62f21c74fcf617fc8712552a471ae
```

## Completion-Criteria

KRONOS R&D is DONE if and only if:

1. every G1/G2/G3 milestone's done-predicate above is satisfied by cited evidence that re-derives
   live (including the Beta-Entry-required BE-G3-5 and BE-G2-6 per D3); AND
2. no open roadmap item remains in the pinned `SRC-ROADMAP` (`docs/roadmap/KRONOS_ROADMAP.md`); AND
3. an **active** Completion Record (contract §13.4) exists, activated by an explicit operator
   COMPLETION-GATE naming the full 40-hex certified main SHA, this file's DoD-Version and sha256, and
   a non-circular evidence digest; bound to live `origin/main` HEAD; and integrity-verifying at the
   emitting turn.

Absent all three, the loop is incomplete-idle (§13.2), never `NO-ACTION`.
