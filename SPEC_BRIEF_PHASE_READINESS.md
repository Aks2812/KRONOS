# SPEC_BRIEF — PHASE READINESS reporting amendment (contract v1.4.4 → v1.4.5)

Governance: `docs/governance/KRONOS_RND_CONTRACT.md` is canonical and sole-binding.
Authorized by maintainer **GATE-1** this turn: a **reporting-only** contract amendment
adding a mandatory `[PHASE READINESS]` section to every terminal report, persisted in the
contract, the stop-report schema, the integrity manifest, the report-producing command
paths, and the tests. Build → independent review → **draft PR**, stopping at **GATE-2**.
**No product work, no firewall action, no containers, no §6/§8 live execution.**

Baseline: `911812c` (R10EGH merge, PR #69). This brief seals the R10EGH scope window to
`911812c` and opens its own window at base `911812c`.

## §0 Milestone-identity reconciliation (binding on the design; proven from pinned sources)

All four pinned reconciliation sources re-derive on disk at their `KRONOS_DONE.md` pins
(SRC-RESEARCH, SRC-LEDGER, SRC-GAPMAP, SRC-ROADMAP — all sha256 OK this turn). The
authoritative milestone↔gate map (pinned `SRC-ROADMAP` = `docs/roadmap/KRONOS_ROADMAP.md`):

- **R10 == BE-G3-5** (committed evaluation evidence for R9; Goal G3; status MISSING).
- **R12 == BE-G2-6** (live driver/executor on an authorized real run; Goal G2; BLOCKED
  until R9 (BE-G1-7) and R10 (BE-G3-5), per D2/D9).
- **R10 is NEVER equated with BE-G2-6.** Any R10↔BE-G2-6 relabel is unsupported and MUST
  NOT be propagated. The CyberGym sec6/sec8 live run is **R12 / BE-G2-6**, distinct from
  R10 / BE-G3-5.

**Phases defined in the authoritative records:** only **Beta-Entry** (`KRONOS_DONE.md`
DoD-Model "Beta-Entry DoD v1"), whose trigger (D3) is: **R10 (BE-G3-5) AND R12 (BE-G2-6)
satisfied by one authorized, manifest-bounded CyberGym/lab run with committed evidence; no
public-target run required.** **Alpha and GA are NOT DEFINED** in any authoritative source.
**R&D-COMPLETE** maps to the §13.4 Completion Record against the DoD (`KRONOS_DONE.md`).
The amendment MUST therefore render Alpha and GA as `UNDEFINED` (never fabricated), and MUST
render `UNKNOWN` with a reason wherever no defensible numeric basis exists. Never fabricate a
percentage, date, mapping, or phase criterion.

## §1 Permitted files (authorized scope — nothing else)

1. `SPEC_BRIEF_PHASE_READINESS.md` (this file)
2. `docs/governance/KRONOS_RND_CONTRACT.md`
3. `docs/governance/stop_report.schema.json`
4. `docs/governance/contract_manifest.json`
5. `tests/test_rnd_contract.py`
6. `tests/test_commit_authority.py`
7. `docs/loop/phase_readiness_claude_maintainer_patch.diff` (new; the Option-B maintainer
   patch for the `.claude/**` report-producing command paths — a plain artifact, NOT an
   edit to `.claude/**`)

**HARD BOUNDARY — do NOT edit:** `.claude/**`, `.github/**`, `cybergym/**`, `manifest.py`
(signed scope manifest), any KRONOS product code, or any file not listed above. The loop
cannot edit `.claude/**`; the command-path change ships as the Option-B patch artifact in
file 7 for maintainer hand-application. If any required fix needs an unlisted file, STOP and
return NEEDS-DECISION.

## §2 Contract edits — `docs/governance/KRONOS_RND_CONTRACT.md` (v1.4.4 → v1.4.5)

Version-token discipline: flip ONLY the contract's own current-version tokens to `1.4.5`;
PRESERVE every historical enumeration by APPENDING `1.4.5`, never replacing a listed version.

1. **§0 header** `Version: 1.4.4` → `Version: 1.4.5`.
2. **Trailer** `Contract-Version: 1.4.4` → `Contract-Version: 1.4.5`.
3. **§16** the `(1.4.4)` example in the "records the active `contract_version`" clause →
   `(1.4.5)`.
4. **§9** (the version-discrimination paragraph): APPEND `1.4.5` to the strict-version
   enumerations (so the sentence reads "…v1.4.3, v1.4.4, and v1.4.5…" and "exactly `1.4.4`,
   or exactly `1.4.5`"). Add one sentence: "Under contract v1.4.5 the object additionally
   carries `phase_readiness` (see §15); this field is required only for `1.4.5` and is not
   retroactive to `1.4.0`–`1.4.4`." Keep the fail-closed and never-loosened language.
5. **§15 ordered list**: insert a NEW bracket section **immediately after item 4 `[WHEN]`**,
   as new item 5 `[PHASE READINESS]`, and increment every subsequent item number by 1 (old
   5 `[WHAT]` → 6, … old 11 `[NEXT PROMPT]` → 12, old 12 final `RECOMMENDED ORCHESTRATOR
   EFFORT` line → 13). The new item text:

   > 5. `[PHASE READINESS]` — mandatory on every terminal report. It reports, derived only
   > from the pinned authoritative milestone sources (`docs/governance/KRONOS_DONE.md` DoD
   > and the pinned `SRC-ROADMAP`) and live gate evidence: the **current phase**; the
   > **completed and remaining weighted gates**; the **percentage or `UNKNOWN`** with the
   > reason it is `UNKNOWN`; the **critical path**; the **minimum / expected / pessimistic
   > remaining checkpointed loop iterations** (one iteration = one durable checkpointed loop
   > turn, §8); the **assumptions**; the **confidence**; and the **exact next-phase
   > trigger**. The only phase defined in the authoritative records is **Beta-Entry**
   > (`KRONOS_DONE.md` DoD-Model); its trigger is R10 (BE-G3-5) AND R12 (BE-G2-6) satisfied
   > by one authorized, manifest-bounded run with committed evidence. **Alpha and GA are
   > undefined in the authoritative records and render `UNDEFINED`, never an invented
   > criterion**; **R&D-COMPLETE** renders against the §13.4 Completion Record / DoD. The
   > section MUST NOT fabricate a percentage, date, mapping, or phase criterion: where no
   > defensible basis exists it renders `UNKNOWN` (numeric fields) or `UNDEFINED`
   > (undefined phases) with the reason. Its machine form nests under the top-level
   > `phase_readiness` object and is version-discriminated (required only at
   > `contract_version` `1.4.5`).

6. **§15 version clause** (the "machine object remains schema-valid…" paragraph): APPEND
   `1.4.5` to the strict-version list (append, do not replace).
7. **§15 Pre-response self-check** (line beginning "Flat key/value…"/"Pre-response
   self-check"): add a check fragment: "`[PHASE READINESS]` is present with its current
   phase, weighted completed/remaining gates, percentage-or-`UNKNOWN`, critical path,
   minimum/expected/pessimistic remaining iterations, assumptions, confidence, and exact
   next-phase trigger, rendering `UNKNOWN`/`UNDEFINED` with a reason where undefined".

Do not alter §14 decision classes, the five-class set, or any other section's semantics.

## §3 Schema edits — `docs/governance/stop_report.schema.json`

1. `properties.contract_version.enum`: append `"1.4.5"`.
2. `if.properties.contract_version.enum`: append `"1.4.5"` (so 1.4.5 inherits the strict
   `when.milestone`, `how.reference_ledger`, and `effort_justification` requirements). Do
   not change the existing `then` branch otherwise.
3. Add a NEW top-level property `phase_readiness` (object, `additionalProperties: false`),
   with `required`: `current_phase`, `gates_completed`, `gates_remaining`, `percentage`,
   `percentage_basis`, `critical_path`, `remaining_iterations`, `assumptions`, `confidence`,
   `next_phase_trigger`. Field schemas:
   - `current_phase`: string
   - `gates_completed`: array
   - `gates_remaining`: array
   - `percentage`: `anyOf` [ number, `{"const":"UNKNOWN"}` ]
   - `percentage_basis`: string
   - `critical_path`: array
   - `remaining_iterations`: object, `additionalProperties:false`, required
     `minimum`/`expected`/`pessimistic`, each `anyOf` [ integer, `{"const":"UNKNOWN"}` ]
   - `assumptions`: array
   - `confidence`: string
   - `next_phase_trigger`: string
4. Add a NEW conditional to the top-level `allOf` array (alongside the existing
   `{"required":["contract_version"]}`), making `phase_readiness` required ONLY for 1.4.5
   (non-retroactive):
   ```json
   { "if":  { "properties": { "contract_version": { "const": "1.4.5" } },
              "required": ["contract_version"] },
     "then": { "required": ["phase_readiness"] } }
   ```
5. Update the top `$comment` to describe v1.4.5: it additionally requires `phase_readiness`;
   1.4.0–1.4.4 validation is unchanged and never requires `phase_readiness`; 1.4.0–1.4.4
   strict validation is never loosened.

Non-retroactivity is a hard requirement: a `1.4.4` report WITHOUT `phase_readiness` MUST
still validate; a `1.4.5` report WITHOUT `phase_readiness` MUST be rejected.

## §4 Manifest — `docs/governance/contract_manifest.json`

Set `contract_version` to `"1.4.5"`. After the §2/§3 edits are final, recompute and write
the sha256 of `KRONOS_RND_CONTRACT.md` and `stop_report.schema.json`. `KRONOS_DONE.md`'s
entry is unchanged (not edited by this brief). This is the final edit before the suite run.

## §5 Tests — `tests/test_rnd_contract.py`

1. `test_manifest_hashes_match_disk`: `"1.4.4"` → `"1.4.5"`.
2. `test_contract_is_v1_4_4_with_auto_brief`: update assertions to `Version: 1.4.5` /
   `Contract-Version: 1.4.5` (rename the function to `..._v1_4_5_...` for accuracy).
3. `LABELED_SECTIONS`: insert `"[PHASE READINESS]"` between `"[WHEN]"` and `"[WHAT]"` (keeps
   the in-order test correct).
4. `test_schema_v140_structure`: update the `if`-enum assertion to
   `["1.4.0","1.4.1","1.4.2","1.4.3","1.4.4","1.4.5"]`.
5. Add tests:
   - `test_schema_v145_in_version_enum`: `"1.4.5"` in `contract_version.enum`.
   - `test_phase_readiness_property_structure`: `phase_readiness` exists;
     `additionalProperties is False`; `required` set equals the ten field names above;
     `remaining_iterations.required == {minimum,expected,pessimistic}`; `percentage` and
     each iteration field admit the `"UNKNOWN"` const.
   - `test_phase_readiness_required_only_at_v145`: the `allOf` carries a conditional whose
     `if.properties.contract_version.const == "1.4.5"` and `then.required == ["phase_readiness"]`;
     and no base/`then` branch for 1.4.0–1.4.4 lists `phase_readiness` in `required`
     (non-retroactive).
   - `test_section15_has_phase_readiness`: §15 contains `[PHASE READINESS]`,
     `one iteration = one durable checkpointed loop turn` (or the exact phrase used),
     `UNDEFINED`, `next-phase trigger`, and `minimum / expected / pessimistic` (match the
     exact rendered wording).

## §6 Option-B maintainer patch — `docs/loop/phase_readiness_claude_maintainer_patch.diff`

Create a unified-diff artifact (a plain file, NOT applied) for the `.claude/**`
report-producing command path(s): `.claude/commands/kronos-continue.md` (and `.claude/RAILS.md`
if it enumerates the sections). The patch adds `[PHASE READINESS]` to the rendered section
sequence after `[WHEN]`, and updates the "contract v1.4.4 §14–§16" reference to `v1.4.5`.
Head the file with a note: "Option B: maintainer hand-applies; the loop MUST NOT edit
`.claude/**` (contract §5/§10, §16 single-source)." These `.claude/**` files are NOT edited
by this brief; the patch is advisory for GATE-2.

## §7 Scope-seal — `tests/test_commit_authority.py` (§11 seal-tax)

1. Seal the R10EGH window: add `R10EGH_MERGE = "911812c"` beside `R10EGH_BASE`, and change
   the audit line from `{R10EGH_BASE}..HEAD` to `{R10EGH_BASE}..{R10EGH_MERGE}`.
2. Open this brief's window: add `PHR_BASE = "911812c"` and `PHR_SECTION_10 = {` the exact
   seven authorized paths in §1 `}`, and append the audit line
   `assert set(names(f"{PHR_BASE}..HEAD")) <= PHR_SECTION_10, set(names(f"{PHR_BASE}..HEAD")) - PHR_SECTION_10`.

## §8 Acceptance criteria

- Contract is v1.4.5; `[PHASE READINESS]` is section 5 of §15 with the fields, the iteration
  definition, the never-fabricate rule, and the Beta-Entry / UNDEFINED / R&D-COMPLETE
  semantics; the self-check includes it.
- Schema: `1.4.5` in both enums; `phase_readiness` object present and well-formed;
  required only at 1.4.5 (a 1.4.4 report without it validates, a 1.4.5 report without it is
  rejected); strict 1.4.0–1.4.4 validation unchanged.
- Manifest: `contract_version` 1.4.5; contract + schema sha256 match disk.
- Milestone identity encoded exactly as §0 (R10=BE-G3-5, R12=BE-G2-6, never conflated);
  Alpha/GA UNDEFINED; no fabricated criteria or percentages.
- R10EGH window sealed to `911812c`; this brief's window opened at `911812c` and green.
- Full suite 0 failed via the canonical runner.
- Option-B `.claude/**` patch delivered as an artifact; no `.claude/**` file edited.
- Diff touches ONLY the seven §1 paths.

## §9 Out of scope (do NOT do)

No `.claude/**`/`.github/**`/`cybergym/**`/`manifest.py`/product-code edits; no new decision
classes; no firewall, containers, or §6/§8 run; no merge, no ready-for-review, no PR beyond a
draft; no public-target anything.
