# Sequence 8 goal-gap map

Status: research decision only; not implemented, not authorized. Companion to `ledger/KRONOS_GOAL_FRAMED_REFERENCE_LEDGER_v1.md`. Decisions are identical to the ledger and `ledger/KRONOS_REFERENCE_DECISIONS_v1.jsonl`.

> **PRIVATE-CAIRN WARNING.** Proposals 71-79 and 83 derive from `cairn-private-fork` @ `1bf6062b9401ea4133d8e1fbe60bab6c09c4d832` and are **PRIVATE-DERIVED**. Only ID, decision, goal and citation are recorded here. **Private Cairn content cannot be transmitted or published without separate authorization.** Sequence 7 flagged 75, 79, 83 as needing a separate operator gate before any runtime analysis.

## Goals and precedence

- **G1 — STRONGER:** "Build meaningful cross-domain capability, so KRONOS can connect evidence across web, infrastructure, mobile, API, and cloud."
- **G2 — MORE EFFECTIVE:** "Increase autonomous planning and execution within explicitly authorized scope and signed engagement limits."
- **G3 — FEWER FALSE POSITIVES:** "Make findings validation-gated, evidence-backed, and appropriately classified, with abstention when the evidence is insufficient."
- **Precedence:** "G3 constrains G1 and G2: a new domain that cannot produce two-armed evidence does not ship (G1 yields to G3), and autonomy never widens scope or relaxes a validation gate (G2 yields to G3 and to the signed manifest). G1 before G2 in sequencing: breadth first, then autonomy over that breadth."

(Source: `KRONOS_RESEARCH_RECORD.md:25-42`.)

## G1 — cross-domain capability

**Gap this corpus is meant to close:** evidence connection across web, infrastructure, mobile, API and cloud. **Corpus support is thin.** Proposals touching G1 per the adjudication: 16 (INVESTIGATE), 23 (INVESTIGATE), 36 (ADAPT), 55 (ADAPT), 56 (ADAPT), 57 (ADAPT), 60 (ADAPT), 63 (INVESTIGATE), mostly jointly with G2 or G3.

| ID | Decision | Joint goals | Gap closed |
|---|---|---|---|
| 16 | INVESTIGATE | G1, G2 | per-role model + cost accounting (routing plumbing); evidence insufficient |
| 23 | INVESTIGATE | G1, G2 | fresh-episode bounded retrieval windows; evidence insufficient |
| 36 | ADAPT | G1, G3 | coverage ledger with negative space: surfaces with no coverage entry are surfaced at terminal call |
| 55 | ADAPT | G1, G3 | pre-dispatch goal ambiguity gate: target must be named |
| 56 | ADAPT | G1, G2 | stagnation signal on repeated work direction with no finding |
| 57 | ADAPT | G1, G2 | adversarial disproof gate before reporting (prompt-only upstream; bind to a code gate) |
| 60 | ADAPT | G1, G3 | absolute-deadline settle sequence with guarded terminal status |
| 63 | INVESTIGATE | G1, G2 | server-validated completion of review pass; server validator unread |

**Reconciliation note (flagged for maintainer):** the Sequence-6 tables also tag G1 on 21 (REJECT), 68 (REJECT), 72 (ADAPT), 73 (INVESTIGATE), 78 (ADAPT), 79 (DEFER), 80 (ADAPT), 84 (INVESTIGATE). The adjudication list above names only eight G1 proposals. The JSONL `goals` field keeps the Sequence-6 tags verbatim, so these also carry G1 there. Of these, only 72, 78, 80 are ADAPT (batch 4 / Cairn, mostly process and contract-validation mechanisms rather than domain breadth); 21 and 68 are REJECT; 73, 84 are INVESTIGATE; 79 is DEFER. None changes the conclusion below.

**Standing gap:** G1 breadth has the fewest corpus-backed adoptions. The corpus is pentest-centric. No corpus repo materially advances the mobile or cloud domains. G1 remains under-served; this is an explicit gap, not closed by Sequence 8. By precedence, G3 still constrains any future G1 domain (no domain ships without two-armed evidence).

## G2 — autonomy within scope

**Strongest cluster in the corpus.** Grouped by the gap each closes:

### Scope gates

Proposals: 6 (ADAPT), 25 (ADAPT), 26 (ADAPT), 28 (ADAPT), 44 (ADAPT), 46 (INVESTIGATE).

Gap closed: Enforce signed scope at the execution layer: gate on every tool call (6), single choke point with drift test (25), non-disableable deterministic deny floor (26), fail-closed on guardrail error (28), oracle probes pass scope+rate gate (44, re-expressed single-dispatcher-owned), operator authorization receipt (46, INVESTIGATE: not cryptographically signed upstream).

### Budget / lifecycle

Proposals: 11 (ADAPT), 13 (ADAPT), 14 (ADAPT), 37 (ADAPT), 38 (ADAPT), 39 (ADAPT), 40 (ADAPT), 50 (ADAPT), 60 (ADAPT), 65 (DEFER), 82 (ADAPT).

Gap closed: Bounded, recoverable, honestly-terminating runs: retry taxonomy (11), tool-call timeouts (13), repeat-call breaker (14), terminal refused while child work active (37), staged cost wind-down (38), bounded auto-recovery (39), per-turn call cap (40), budget exhaustion yields labelled partial report (50, single-dispatcher-owned), absolute-deadline settle (60), request-rate limiter (65, DEFER), heartbeat slack validation (82).

### Human / authorization gates

Proposals: 17 (INVESTIGATE), 46 (INVESTIGATE), 61 (ADAPT), 79 (DEFER).

Gap closed: Human gate for ambiguous or irreversible steps: ask-user barrier (17), authorization receipt (46), tiered gate with human ask (61; upstream judge fails open, KRONOS must fail closed), route credential-gated steps to human path (79, DEFER, private-derived, separate operator gate).

### Sandbox / process confinement

Proposals: 12 (INVESTIGATE), 15 (ADAPT), 62 (ADAPT), 75 (INVESTIGATE), 77 (ADAPT).

Gap closed: Contain what tools and children can touch: cross-tool code-path confinement (12, INVESTIGATE, enforcement logic unvendored), capability allow-list sandbox (15), secret scrub from child env (62), process-lineage sweep (75, INVESTIGATE, private-derived), strict-isolation flag for unattended workers (77, private-derived).

**Constraint:** every control-flow proposal here routes through the single deterministic dispatcher as a hard rail (see architectural consequences). G2 yields to G3 and to the signed manifest: none of these may widen scope or relax a validation gate.

## G3 — validation, evidence, abstention

### Evidence grounding

Proposals: 1 (ADAPT), 2 (ADAPT), 8 (ADAPT), 22 (ADAPT), 29 (ADAPT), 33 (ADAPT), 34 (ADAPT), 35 (ADAPT), 36 (ADAPT), 42 (ADAPT), 43 (ADAPT), 48 (DEFER).

Gap closed: Findings must bind to recorded, checkable evidence: exact-quote receipt slices (1), negative results as evidence (2), exploited-vs-blocked proof fields (8), evidence-state ladder (22; prompt-only upstream), model-emitted evidence treated as a claim with verbatim quote (29), counterevidence closure states (33; prompt-only upstream), required counterevidence fields rejected at write (34), cited evidence-ids verified to exist (35; re-express fail-CLOSED), coverage ledger negative space (36), cost-ordered corroboration ladder (42) and external-oracle disagreement rejection (43) re-expressed single-dispatcher-owned, re-run reproduction (48, DEFER).

### Abstention / honest reporting

Proposals: 10 (ADAPT), 24 (ADAPT), 30 (ADAPT), 31 (ADAPT), 80 (ADAPT).

Gap closed: Report what is not known: partial-completion with typed reasons and refusal to invent spend (10), qualification report with Not-qualified verdict (24), audit self-reported productivity against real state delta (30), unrecorded confirmations flagged not guessed (31), strict JSON contract with explicit abstention (80).

### False-positive control rejections

Proposals: 20 (REJECT), 51 (REJECT).

Gap closed: Declined mechanisms that weaken FP control: free-text findings store with model-set confidence (20), keyword-additive static FP score (51). Both REJECT; reaffirm evidence-binding.

## Remaining proposals by Sequence-6 goal tag

Proposals not named in the dispatch groupings above, listed for completeness by their Sequence-6 goal tags (no further gap analysis was adjudicated).

| ID | Decision | Goals (Seq-6) |
|---|---|---|
| 3 | ADAPT | G2, G3 |
| 4 | ADAPT | G2, G3 |
| 5 | ADAPT | G2 |
| 7 | ADOPT | G2, G3 |
| 9 | INVESTIGATE | G3 |
| 18 | REJECT | G2 |
| 19 | ADAPT | G2 |
| 21 | REJECT | G1 |
| 27 | REJECT | G2, G3 |
| 32 | INVESTIGATE | G2 |
| 41 | REJECT | G2 |
| 45 | INVESTIGATE | G3 |
| 47 | REJECT | G2 |
| 49 | DEFER | G2, G3 |
| 52 | REJECT | G3 |
| 53 | ADAPT | G2, G3 |
| 54 | ADAPT | G2 |
| 58 | ADAPT | G3 |
| 59 | ADAPT | G3 |
| 64 | ADAPT | G3 |
| 66 | ADAPT | G2, G3 |
| 67 | REJECT | G3 |
| 68 | REJECT | G1, G2, G3 |
| 69 | DEFER | G2 |
| 71 | ADAPT | G2 |
| 72 | ADAPT | G1, G2 |
| 73 | INVESTIGATE | G1 |
| 74 | ADAPT | G2 |
| 76 | ADAPT | G2 |
| 78 | ADAPT | G1, G3 |
| 81 | ADAPT | G2 |
| 83 | INVESTIGATE | G2 |
| 84 | INVESTIGATE | G1, G2 |
| 85 | REJECT | G3 |

## Architectural consequences

- A **single deterministic dispatcher is the sole graph-writer**; scope_guard, lifecycle, budget and cleanup are hard rails the LLM can never override (RECORD:1642-1646, :777-779). Every control-flow proposal (gates 6, 25, 26, 28; terminal-refused-with-children 37; recovery 39; graph-delta reason-trigger 81; blackboard 84) must route through that one dispatcher as a hard rail. None may introduce a second loop or a sub-agent pool. KRONOS = one orchestrator loop + one independent supervisor; bounded in-loop concurrency only (RECORD:1652-1654).
- **Swarm-origin proposals** (42, 43, 44 oracle corroboration; 49 per-agent signing; 50 scheduler) must be re-expressed as single-dispatcher-owned, not multi-agent swarm.
- **Fail-closed rule:** where an upstream fails open (35 evidence-id check fail-open on proxy timeout; any guardrail), the KRONOS re-expression MUST fail closed.
- **Prompt-only mechanisms** (33, 57, 58, 61, 66, 78 and others) are advisory until bound to a code-owned gate. Adopt the code gate, not the prompt alone.

REJECT set (18, 20, 21, 27, 41, 47, 51, 52, 67, 68, 85) each breaches a named invariant and reaffirms fail-closed + signed allow-list + evidence-binding. Detail in `evidence/sequence8-adjudication-report.md`.

## Totals

84 proposals (ids 1-85, no 70): ADOPT 1, ADAPT 54, INVESTIGATE 13, DEFER 5, REJECT 11.
