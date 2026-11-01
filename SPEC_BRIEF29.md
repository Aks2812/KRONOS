# SPEC_BRIEF29 — Signed Autonomy Envelope: Hermetic G2 Foundation (APPROVED rev3)

> **Status: GATE-1 APPROVED (operator architecture approval, `/home/void/context.md` 2026-10-31;
> Opus self-approved GATE-1 after verifying this brief carries those decisions, introduces no new
> unresolved architecture, and does not expand the allowlist).** Base = `origin/main` @ `55b4b7f`.
> Incorporates D1–D7 + P0/P1 dispositions (SEQ 179) and operator decisions O1/O2/O3 (SEQ 180).
> Representation + pure evaluation only; no runtime, no wiring, no live/§6 execution.

**Claim boundary (binding, read first).** This increment is **representation + pure evaluation only**.
It does **not**: enforce authorization at runtime, deliver tightening to a running dispatcher, stop
execution (no watchdog runtime), classify existing `Intent.kind` values, classify local-vs-target
operations, connect budget charge-time enforcement, or support full amendment chains. Each is a later
increment. No autonomous action becomes possible from this increment — nothing consults the evaluator
at runtime yet.

Policy: binds under `CLAUDE.md` §4 Hard boundaries + the v7 contract (canonical; not restated).
Hermetic, side-effect-free. **`src/kronos/manifest.py` is edited under explicit operator authorization**
(`context.md` 2026-10-31) **limited to** the signed-autonomy schema, canonical parsing/identity
integration, and the verified-manifest boundary below — no unrelated refactor, signing change, scope
expansion, dispatcher wiring, or live behavior.

---

## §1 — Objective and relationship to G2

Establish the **signed representation** of an engagement's autonomy envelope and **one pure
deterministic evaluator** computing effective authorization from it. Foundation rung of **G2 (autonomy
within signed scope)** — the least-mature goal per SEQ 177. G1-before-G2 and G3-gates-both unchanged.
This rung adds representation + evaluation, never action.

## §2 — Verified current-state baseline (origin/main @ 55b4b7f; cited)

- Manifest is the only authority source, pydantic, Ed25519-signed: `manifest.py:29-37` (schema),
  `:54-62` (`canonicalize` = `yaml.safe_dump(sort_keys=True)` over the raw content dict), `:65-70`
  (`sign_manifest`), `:89-125` (`load_and_verify`), window check `:121-123`.
- **No autonomy/mode/beast/calm/unattended/amends/manifest_id field exists** (grep NONE); no computed
  identity field (`engagement_id:str` is operator-supplied).
- **Verified-content canonicalization order** (P1 verified-boundary): `load_and_verify` does
  `yaml.safe_load`→`raw` (`:98`), strips `signature`→`content` (`:109`), `canonicalize(content)`
  (`:110`), `public_key.verify(...)` (`:112`) — **before** `ScopeManifest(**_flatten(content))`
  (`:117`). So the verified signing input is the **raw signature-stripped dict**, pre-`_flatten`,
  pre-pydantic. `_flatten` (`:73-86`) injects defaults only for `destructive_allowed`/`in_scope`/
  `excluded`.
- **Budget reuse + None semantics** (D6/P0-budget): `BudgetLimits` frozen dataclass, 5 dims each
  `…|None` default `None` (`limits.py:29-39`); `BudgetLedger.charge` (`ledger.py:143-146`) only raises
  `if ceiling is not None and new_total > ceiling` — **`None` means UNLIMITED** (`limits.py:4-10`
  docstring confirms). ⇒ an absent/None signed unattended limit must **not** be read as unlimited.
- **Per-authorization matcher is standalone** (D3/P0-target): `_matches(pattern:str, target:str, *,
  is_exclusion:bool, shape:TargetShape|None=None)` (`scope_guard.py:866-933`) is a **pure module-level
  function** — no `self`, no manifest param — callable against one pattern + one target. **It is a
  private (underscore) function; this brief depends on it without changing its semantics** (§4.2,
  regression-pinned in §13). Engagement scope entry is `ScopeGuard.is_in_scope(target, *, node_type,
  target_kind)` (`:943-991`) / `scope_guard(...)` (`:994-1008`). Shape helpers `classify_target`
  (`:262`), `_effective_shape` (`:349`), `_scope_key_shape` (`:369`) are module-level.
- `target_kind` semantics (`:943-991`): `"id"` gates on `NODE_TYPE_SHAPES[node_type]` family then
  matches `in_scope`; `"scope_key"` skips the family filter.
- **Sole live authz check** is one `engagement.scope.is_in_scope(...)` at `dispatcher.py:137-139`;
  `destructive_allowed` stored-but-never-gated (only write `graph.py:90`).
- Abstention/fail-closed precedent: `controls.py:29-36` (`Classification` incl. `"inconclusive"`),
  `runner.py:209-220`, `lifecycle.py:81-93`.
- Opaque secret refs only: `schema.py:67`, `ingest/__init__.py:51` (`"sha256:<hex>"`).
- **No operator-approval artifact exists** (P0-operator): grep `operator_triggered|operator_approval|
  approved_by|human_approval|consent` → NONE. `authorized_by:str` is static metadata; `ReviewVerdict`
  (`reviewer.py:21-25`) is the mock downgrade-only in-product reviewer, not operator approval.
- Tz-aware datetime enforced for manifest windows (`manifest.py:39-51`). No `hypothesis` in repo.

## §3 — Threat model and abuse cases

1. **Mode-as-grant** — `beast` alone grants nothing without a matching signed authorization.
2. **Target confusion** — authorization for X must not cover Y; per-authorization binding (§4.2), not
   mere engagement-scope membership.
3. **Class confusion** — class K authorization never covers class J≠K.
4. **Window replay** — expired/future authorization denied (tz-aware).
5. **Runtime escalation** — runtime requesting broader authority → named `AutonomyError`, never clamp-up.
6. **Destructive inheritance** — destructive needs independent `destructive_allowed` ∧ per-auth
   `destructive`; never from mode/class.
7. **Amendment forgery/downgrade-by-invalidation** — invalid amendment leaves last valid envelope in
   force; increases non-retroactive and gated by the amendment's own `effective_at`.
8. **Canonicalization drift** — identity/signing input from the verified sorted-key canonical content.
9. **Backward-compat grant** — old manifest (no block) → fail-closed Calm, never Beast.
10. **Credential leakage** — only opaque refs; no raw credential in schema.
11. **Malformed/None-as-unlimited** — missing/malformed/None unattended data fails closed (deny),
    never unlimited.
12. **Forged operator approval** — a caller-supplied "operator_triggered" boolean is rejected; no
    trusted operator-approval boundary exists yet, so Calm-mode Class B/C fails closed.
13. **Local-bypass confusion (O2)** — this evaluator governs **target-directed** A/B/C requests only;
    it defines no caller-controlled "local" category that could bypass target authorization. Local-vs-
    target classification is a non-goal here (§11), deferred to the capability-registry/wiring brief.

## §4 — Exact schema proposal (smallest coherent schema; A|B|C only)

Signed, nested in the manifest content so the existing signature covers it. Pydantic submodels on
`ScopeManifest`; snake_case; tz-aware datetimes via the existing validator.

```text
ScopeManifest (existing + two OPTIONAL fields):
    autonomy: AutonomyEnvelope | None = None     # absent ⇒ fail-closed Calm (back-compat)
    amends:   AmendmentRef      | None = None     # absent ⇒ ROOT manifest

AutonomyEnvelope(BaseModel):
    mode_max: Literal["calm", "beast"] = "calm"           # signed CEILING; default calm
    unattended_authorizations: list[UnattendedAuthorization] = []
    max_unattended_duration_seconds: int                  # REQUIRED, finite, > 0 (no None)
    max_unattended_budget: UnattendedBudget               # REQUIRED; every dim explicit (§4.1)
    exfil_simulation: ExfilSimulation | None = None       # None ⇒ not authorized
    watchdog: WatchdogPolicy | None = None                # signable now; NO runtime (§4.4)

UnattendedAuthorization(BaseModel):
    action_class: Literal["A", "B", "C"]                  # EXTERNAL target action classes
    target: str                                           # CONCRETE canonical identifier (§4.2)
    target_node_type: str                                 # required for the scope_guard family check
    valid_from: datetime                                  # tz-aware
    valid_until: datetime                                 # tz-aware; must be > valid_from
    destructive: bool = False                             # + requires manifest.destructive_allowed (§4.3)

UnattendedBudget(BaseModel):                              # explicit finite non-negative per dimension
    validation_attempts: int                              # >= 0, REQUIRED
    tool_invocations:    int                              # >= 0, REQUIRED
    wall_clock_seconds:  float                            # >= 0, REQUIRED
    llm_tokens:          int                              # >= 0, REQUIRED
    llm_cost_usd:        float                            # >= 0, REQUIRED
    # converted to kronos.budget.BudgetLimits at the evaluation boundary (§4.1); NO None permitted here.

ExfilSimulation(BaseModel):
    allowed: bool = False
    byte_budget: int = 0                                  # >= 0
    dataset_marker: str | None = None                     # opaque label ONLY; never raw data

WatchdogPolicy(BaseModel):                                # signed representation only (no runtime)
    may_auto_stop: bool = False                           # safe default false
    confirm_window_seconds: int = 0                       # if may_auto_stop: 1 <= v <= 300 (§4.4, O1)

AmendmentRef(BaseModel):                                  # present ⇒ this is an amendment (§7)
    manifest_id: str                                      # REQUIRED, non-empty (predecessor identity)
    reason: str                                           # REQUIRED, non-empty
    effective_at: datetime                                # REQUIRED, tz-aware (§7 / O3)
```

**Action-class taxonomy is `A | B | C` only (O2).** There is **no `LOCAL` class**. Every target-directed
Class A, B, or C request requires a matching signed `unattended_authorization`. Local graph queries,
evidence analysis, planning, and report drafting are **outside this target-authorization evaluator**
(§11 non-goal); deterministic local-vs-target classification belongs to the later capability-registry/
dispatcher-wiring brief and must **not** become a caller-controlled bypass.

### §4.1 Budget reuse + None-safety (D6 / P0-budget)
`UnattendedBudget` carries all five `BUDGET_DIMENSIONS` (`limits.py:20-25`) as **required, finite,
non-negative** values and is converted to `kronos.budget.BudgetLimits` at the evaluation boundary. The
evaluator **rejects (fail-closed deny) any unattended budget with a missing/None dimension** — because
`BudgetLimits` treats `None` as *unlimited* (`ledger.py:144`, `limits.py:4-10`), an absent signed cap
must never become unlimited autonomy. No second ledger/counter is created; charge-time enforcement
stays `BudgetLedger.charge` (unchanged, unwired this increment).

### §4.2 Per-authorization target binding (D3 / P0-target)
Engagement-scope membership is **not** action authorization. The evaluator establishes **two separate
facts** for every target-directed request:

1. **In engagement scope:** `scope_guard(request.target, manifest, node_type=request.node_type,
   target_kind=…)` is True (`scope_guard.py:994-1008`).
2. **Bound to the specific signed authorization:** `_matches(auth.target, request.target,
   is_exclusion=False, shape=classify_target(request.target))` is True for the **selected**
   `UnattendedAuthorization` (`_matches`, `scope_guard.py:866`), **and** the request's and
   authorization's classified shapes match (no cross-identifier-boundary match).

Both must hold; engagement scope alone never authorizes. **`UnattendedAuthorization.target` is a
concrete canonical identifier** (exact literal, no wildcard) — `_matches` on an exact literal uses
host-exact/literal comparison (`scope_guard.py:915-921`). **Wildcard/glob authorization targets are
rejected (fail-closed) this increment**; controlled-pattern semantics are deferred. **`_matches` is a
private function (D3); this brief depends on its current behavior without modifying it and pins that
behavior with regression tests (§13).** Matcher semantics are not changed in this brief.

### §4.3 Destructive (D4; independent, never inherited)
A destructive request is authorized **only if** `manifest.destructive_allowed is True` **AND** the
selected `UnattendedAuthorization.destructive is True`. Never implied by `mode=="beast"` or
`action_class=="C"`. Reuses the existing `destructive_allowed` field (`manifest.py:35`), newly consulted
by the pure evaluator.

### §4.4 Watchdog (D2; signed only, no runtime — O1)
Validation: `may_auto_stop` default `False` (safe). If `may_auto_stop is True`, `confirm_window_seconds`
must satisfy `1 <= confirm_window_seconds <= WATCHDOG_CONFIRM_WINDOW_MAX`, where
**`WATCHDOG_CONFIRM_WINDOW_MAX = 300` seconds** (O1). The future runtime default is expected to be 30s,
but this increment implements **only signed representation and validation, no watchdog behavior** — the
brief makes **no** claim of watchdog enforcement.

## §5 — Canonical signing implications + verified-manifest boundary (P1)
- The autonomy/amends blocks are nested in the signed content; existing `canonicalize()`
  (`manifest.py:54-62`, `sort_keys=True`) covers them once `_flatten` maps the new nested keys.
  `AmendmentRef.effective_at` is therefore part of the signed canonical content (O3).
- **`compute_manifest_id` derives from the exact verified canonical content** — the raw
  signature-stripped `content` dict (`manifest.py:109`), the same bytes `public_key.verify` checks
  (`:112`), **before** `_flatten`/pydantic defaults. Definition:
  `manifest_id = "sha256:" + sha256(canonicalize(content)).hexdigest()`. This injects no parser default
  into identity (so an old manifest's identity is unchanged).
- **A parsed `ScopeManifest` alone is not proof of verification.** Introduce a `VerifiedManifest` value
  type produced **only** by `load_and_verify`, carrying (a) the verified canonical `content` dict (for
  `compute_manifest_id`) and (b) the parsed `ScopeManifest`. `verify_amendment` and the evaluator
  consume `VerifiedManifest`, never a bare parsed object.
- Regression: a pre-autonomy manifest's canonical bytes + signature verify byte-identically before/after
  this change (optional keys absent ⇒ canonicalization unchanged).

## §6 — Backward-compatibility policy
- New fields Optional with safe defaults; `load_and_verify` parses an older manifest with no block.
- **Absent `autonomy` ⇒ fail-closed Calm**: `mode_max` treated as `"calm"`, zero authorizations, no
  exfil, no watchdog ⇒ **no unattended authority, never Beast**.
- Absent `amends` ⇒ root manifest (valid). Never synthesize Beast for an old manifest.

## §7 — Amendment semantics (D1 bounded single-hop + O3 effective-time + P1 structure)
- **Identity:** `manifest_id` per §5 over verified content.
- **Bounded single-hop contract (D1):**
  - An amendment is valid **only** when its predecessor is a **verified root manifest** (`amends is
    None`). This increment supports **at most `root → one amendment`**.
  - An amendment whose predecessor is itself an amendment (`predecessor.amends is not None`) **fails
    closed** until full-chain validation exists.
  - This is **not** general amendment-chain support. Full multi-hop traversal, trusted predecessor
    resolution, replay protection, fork detection, and persistence must be completed **before**
    amendment chains may control live autonomous execution (later, separately-justified prerequisite).
- **Structure (P1):** if `amends` is absent ⇒ root. If present ⇒ `manifest_id` **required non-empty**,
  `reason` **required non-empty**, `effective_at` **required tz-aware**. An `AmendmentRef` with
  empty/None `manifest_id`, empty `reason`, or missing/malformed/**timezone-naive** `effective_at` is
  **not** a valid amendment (fail closed).
- **`verify_amendment(new: VerifiedManifest, predecessor: VerifiedManifest | None) -> AmendmentDecision`**
  (pure): accepts iff `new.amends.manifest_id == compute_manifest_id(predecessor)`, `predecessor` is a
  verified root (`amends is None`), and both verified. Mismatch/invalid/predecessor-not-root ⇒ reject;
  **last valid envelope (predecessor) stays in force** (downgrade-by-invalidation yields the
  already-verified, not a more-permissive, envelope).
- **Effective time (O3):** the amendment's own authenticated tz-aware `effective_at` (part of the signed
  canonical content, §5) governs when it takes effect. **Permission increases do not apply before
  `effective_at`** (not before per-authorization `valid_from`, which is insufficient for `mode_max`/
  budget/duration/exfil/destructive/watchdog changes). Per-authorization `valid_from` still gates
  individual authorizations after the amendment is effective. An amendment with missing/malformed/naive
  `effective_at` fails closed.
- **Tightening honesty:** immediate tightening is **representation/evaluator behavior only** — it will
  not reach a running dispatcher until runtime cache-invalidation + re-evaluation exist (later
  increment). The brief claims no immediate runtime tightening.
- **Non-retroactivity:** a permission increase authorizes actions only from `effective_at` onward;
  it never legitimizes an earlier action.
- **Amendment direction classification (D3 mixed-reject; maintainer decision, context.md 2026-10-31).**
  Classify a structurally-valid amendment by comparing it to its verified predecessor across **every
  authority axis**: `mode_max`, `max_unattended_duration_seconds`, each `BUDGET_DIMENSIONS` dimension,
  `watchdog`, `exfil_simulation`, the `unattended_authorizations` set, and the manifest-level
  `destructive_allowed` and engagement `in_scope`/`excluded`. An axis is *increased* if the amendment is
  more permissive on it, *tightened* if less permissive, *unchanged* if equal. Then:
  - *tightening-only* (≥1 tightened axis, **no** increased axis) ⇒ effective **immediately** on
    verification (no `effective_at` gate);
  - *increase-only* (≥1 increased axis, **no** tightened axis) ⇒ the predecessor remains in force until
    `effective_at`, the amendment at/after it (§8.1);
  - *mixed* (**both** an increased and a tightened axis) ⇒ **invalid, fail-closed**; the predecessor
    stays in force exactly as for any invalid amendment. Mixed intent MUST be expressed as separate
    single-purpose amendments. A no-op amendment (no changed axis) is valid and effective immediately.

## §8 — Effective-authorization algorithm (one pure function; no distribution)
All authorization logic lives in **one module** (`src/kronos/autonomy.py`) — not spread across
dispatcher/executor/driver/tools. Pure, side-effect-free.

```text
in_force_manifest(predecessor: VerifiedManifest, amendment: VerifiedManifest | None,
                  now: datetime) -> VerifiedManifest          # selects the governing manifest (§8.1)
in_force_effective_envelope(verified: VerifiedManifest,
                  runtime: RuntimeRestrictions | None) -> EffectiveEnvelope  # provenance-bearing (§8.1)
effective_envelope(signed: AutonomyEnvelope | None,
                  runtime: RuntimeRestrictions | None) -> EffectiveEnvelope  # NON-authorizing: no provenance
authorize(effective: EffectiveEnvelope, request: AuthorizationRequest, verified: VerifiedManifest,
          now: datetime) -> AuthorizationResult
```
`authorize`'s `verified` argument MUST be `in_force_manifest(...)` and its `effective` MUST be
`in_force_effective_envelope(verified, ...)`; see §8.1.

**`effective_envelope` (intersection, fail-closed):**
- scalar limits (budget dims, duration): `runtime_limit <= signed_limit` ⇒ effective = runtime (= min,
  allowed restriction); `runtime_limit > signed_limit` ⇒ **raise `AutonomyError("runtime <dim> exceeds
  signed authority")`** (never clamp up).
- `mode_max`: runtime may only lower (beast→calm); runtime beast over signed calm ⇒ `AutonomyError`.
- authorizations: runtime may only remove/narrow; a runtime entry not covered by a signed entry ⇒
  `AutonomyError`.
- destructive/exfil: runtime may only disable; enabling over signed-disabled ⇒ `AutonomyError`.
- any signed unattended budget dimension missing/None ⇒ fail-closed deny (§4.1). Malformed/expired/
  unverifiable signed autonomy ⇒ fail closed.

**`authorize` (per-request; deny by default, allow iff ALL hold). Requests are target-directed A/B/C
only — no LOCAL category (O2):**
```text
mode:   request.mode permitted by effective.mode_max (calm ≤ beast; beast request needs mode_max==beast).
class rule:
  A: ALWAYS requires a matching signed authorization; allowed in calm or beast within limits.
  B: calm ⇒ DENY (fail closed — no trusted operator-approval boundary exists yet, P0);
     beast ⇒ allow iff a matching signed authorization exists.
  C: calm ⇒ DENY (per-action operator authorization deferred to approval brief);
     beast ⇒ allow iff signed manifest EXPLICITLY enumerates (action_class=C, this target, active window).
binding: engagement scope (scope_guard) AND per-authorization _matches(auth.target, request.target)
     with matching shape (§4.2). Non-match ⇒ deny.
window: auth.valid_from <= now <= auth.valid_until (tz-aware). Future/expired ⇒ deny.
amendment gate: the governing manifest is `in_force_manifest` (§8.1) — the predecessor before an
     increase-only amendment's `effective_at` (and for any invalid/mixed amendment), the amendment at/
     after it or immediately for a tightening-only amendment. There is NO blanket deny: a request the
     in-force (predecessor) manifest already grants is ALLOWed during the pending window; a not-yet-
     effective increase is simply absent from the in-force envelope, so it denies on its own terms.
provenance: `authorize` grants ONLY when `effective` carries manifest provenance equal to
     `verified.manifest_id` (§8.1); a non-provenanced envelope (e.g. one from `effective_envelope` over a
     bare `AutonomyEnvelope`) authorizes nothing (fail-closed DENY).
budget: request draw <= effective budget per dimension (reuse BUDGET_DIMENSIONS).
duration: session elapsed <= effective.max_unattended_duration_seconds.
destructive: if request.destructive ⇒ require verified.destructive_allowed AND auth.destructive.
inconclusive: a required evaluation input that is unavailable ⇒ INCONCLUSIVE result (reuse abstention
     precedent controls.py:29-36), surfaced later in the pipeline — never silent allow/skip.
```
No graph/network/model/tool side effects (pure over dataclasses).

### §8.1 — Verified-provenance binding + in-force manifest (maintainer decisions, context.md 2026-10-31)
Three settled rulings govern `authorize`. They change evaluator semantics only; no goal, scope, wiring,
or §10 change, still one pure module.

1. **Verified authority boundary (D1-authority) — a bare envelope never authorizes.** An
   `EffectiveEnvelope` carries manifest **provenance** = the `manifest_id` of the `VerifiedManifest` it
   was derived from. `authorize` grants a request ONLY when `effective`'s provenance is present AND
   equals the `verified: VerifiedManifest` argument's `manifest_id`; otherwise it DENIES fail-closed and
   authorizes nothing. `in_force_effective_envelope(verified, runtime)` is the **sole** producer of a
   provenance-bearing (authorizing) envelope. `effective_envelope(signed: AutonomyEnvelope | None, …)`
   composes a provenance-absent, **non-authorizing** envelope (intersection/composition and tests only).
   A bare `AutonomyEnvelope` thus can never authorize.
2. **In-force manifest selection (D2-pending).** `in_force_manifest(predecessor, amendment, now)` returns
   the **amendment** iff it is valid (§7 single-hop) AND is either *tightening-only* (effective
   immediately on verification) or *increase-only* with `now >= effective_at`; otherwise the
   **predecessor** — i.e. before `effective_at` for an increase-only amendment, and for every invalid,
   mixed, or single-hop-violating amendment. `authorize` evaluates **every** input against this one
   in-force manifest **consistently** — the envelope (mode/authorizations/budgets/duration), the
   manifest-level `destructive_allowed`, and engagement scope (`scope_guard`/`in_scope`). Evaluating the
   envelope against one manifest and `destructive_allowed`/`in_scope` against another is a defect (F-C).
   Because the pre-`effective_at` in-force manifest is the predecessor, a request the predecessor already
   grants is ALLOWed during the pending window (invariant 7); the not-yet-effective increase is absent,
   so it denies without any blanket gate.
3. **Mixed amendments rejected fail-closed (D3).** Classification and the tighten-immediate /
   increase-deferred / mixed-invalid rule are defined in §7; a mixed amendment is invalid and leaves the
   predecessor in force. This supersedes any reading that gated the whole request via a single
   `pending_increase_until` field.

## §9 — Integration boundaries
- **In scope:** schema (§4) on `ScopeManifest`; `VerifiedManifest`; `compute_manifest_id`;
  `verify_amendment` (bounded single-hop); `effective_envelope`; `authorize`; `AutonomyError`; the
  request/restriction/result value types; tests.
- **NOT wired:** the evaluator is **not** called from `dispatcher.py`, `live_executor.py`, any driver,
  or any tool; `dispatcher.py:137-139` is unchanged. Wiring + stop primitive + watchdog = next brief.
- **Sole-writer note:** evaluator is pure and writes nothing; the only sole-writer concern is ensuring
  it cannot mutate graph/manifest — satisfied by purity (returns decisions, performs none).

## §10 — Permitted files (§3 allowlist; binding)
1. `SPEC_BRIEF29.md`
2. `src/kronos/manifest.py` — optional `autonomy`/`amends` submodels; `_flatten` mapping for nested
   keys; `compute_manifest_id`; `VerifiedManifest` + its production in `load_and_verify`. *(operator
   authorized target, narrow: signed-autonomy schema + canonical identity + verified-manifest boundary
   only — no unrelated refactor/signing change/wiring.)*
3. `src/kronos/autonomy.py` — **new**: `effective_envelope`, `authorize`, `verify_amendment`,
   `AutonomyError`, value types. All authorization logic here.
4. `tests/test_autonomy.py` — **new**: unit, decision-table, deterministic generator / property, and
   adversarial tests (§13).
5. `tests/test_manifest.py` — back-compat, schema parse/reject, `manifest_id` stability, canonical-bytes
   regression, `VerifiedManifest` production, `_matches` regression-pin (§13).
6. `tests/conftest.py` — extend `manifest_factory` **additively** (default output unchanged).
7. Test-file seal updates sealing SPEC_BRIEF28's whole-window audit to `55b4b7f`.

**Reuse-only (NOT edited):** `budget/*`, `scope_guard.py`, `agent/*`, `schema.py`, `reconcile/*`,
`.github/`, `cybergym/`, `.claude/`. No dependency added (D5: no `hypothesis`).

## §11 — Explicit non-goals
No supervisor/watchdog runtime (only signed watchdog fields); no operator-stop/cancel; no per-action
operator-approval integration (P0 — Calm B/C fail closed here); **no `LOCAL` action class and no
local-vs-target operation classification (O2 — deferred to the capability-registry/wiring brief; must
never be a caller-controlled bypass)**; no live network; no real provider/LLM transport; no concurrency;
no cloud/API/identity/technology ingestion; no generalized lifecycle; no sole-writer consolidation
beyond evaluator purity; no destructive/externally-observable action; no dispatcher wiring; no
full amendment-chain support (bounded single-hop root→one only); no mapping of existing `Intent.kind`
to A/B/C (D7); no change to `_matches` semantics.

## §12 — Acceptance criteria (tests-as-rules; expected values from §-prose, not observed behavior)
Decide PASS/FAIL from pytest `SUMMARY:` line, never `$?`. All hermetic (socket-raise guard where a
parse path runs).

A. **Back-compat.** Old manifest (no block) loads; `autonomy is None`/`amends is None`; evaluator =
   fail-closed Calm (no unattended authority, not Beast).
B. **Signed schema round-trips** into typed submodels with §4 names/types.
C. **`manifest_id` stability** over verified content; order-independent; any content change changes it.
D. **Canonical-bytes regression** — pre-autonomy manifest verifies byte-identically before/after.
E. **Verified-manifest boundary + provenance binding** — `compute_manifest_id`/`verify_amendment`
   consume `VerifiedManifest`; a bare parsed object is not accepted as verified; `manifest_id` carries no
   `_flatten` defaults. `authorize` grants ONLY when the evaluated `EffectiveEnvelope`'s provenance ==
   the in-force `verified.manifest_id`; an envelope from `effective_envelope` over a bare
   `AutonomyEnvelope` (no provenance) or one whose provenance mismatches `verified` is DENIED
   fail-closed (§8.1(1); rows 32-34; invariant 9).
F. **Intersection / no silent widening** — `min` for restricting runtime; named `AutonomyError` on any
   widening (limit/mode/authorization/destructive/exfil); never clamp up.
G. **Decision table (§13) holds** cell-for-cell from prose.
H. **Destructive independence** — no mode/class combination authorizes destructive without
   `destructive_allowed` AND `auth.destructive`.
I. **Fail-closed** — missing/malformed/expired/unverifiable autonomy, or any **None/absent unattended
   budget dimension**, denies (or INCONCLUSIVE for an unavailable required input) — never allow, never
   unlimited.
J. **No operator-trigger escalation** — Calm-mode Class B and Class C always DENY; no caller-supplied
   operator-approval boolean exists or is honored.
K. **Per-authorization binding** — a request matching engagement scope but NOT the selected
   authorization's concrete target is DENIED; a wildcard authorization target is rejected; shapes must
   match (no cross-identifier match). `_matches` behavior relied upon is pinned (§13).
L. **No LOCAL class (O2)** — the `action_class` schema admits only `A|B|C`; there is no `LOCAL` member,
   no local request category, and no code path authorizes a request without a matching signed
   authorization on grounds of being "local".
M. **Amendment bounded single-hop + direction semantics** — valid root→one amendment accepted;
   amendment-of-amendment fails closed; invalid/mismatched amendment leaves predecessor envelope in
   force; a missing/malformed/timezone-naive `effective_at` fails closed. Direction (§7/§8.1): a
   **mixed** amendment (≥1 increased AND ≥1 tightened axis, over the full axis set incl. manifest-level
   `destructive_allowed` and `in_scope`) is invalid fail-closed; a **tightening-only** amendment applies
   immediately on verification; an **increase-only** amendment leaves the predecessor in force until
   `effective_at` — during that window a request the predecessor already grants is ALLOWed (row 30) and
   only the not-yet-effective increase (incl. a `destructive_allowed`/`in_scope` increase) is withheld
   (rows 25, 31, 33-34). No blanket deny of the whole request while an increase is pending.
N. **Watchdog validation (O1)** — `may_auto_stop=false` default; `may_auto_stop=true` requires
   `1 <= confirm_window_seconds <= 300` (`WATCHDOG_CONFIRM_WINDOW_MAX`); no enforcement claimed.
O. **No side effects** — evaluator touches no graph/network/model/tool (socket-raise guard; no graph
   writes during evaluation).
P. **Secret safety** — no field accepts raw credential; `dataset_marker` opaque; credential refs opaque.
Q. **Scope-audit (whole window) + SPEC_BRIEF28 seal** — `git diff --name-only 55b4b7f..HEAD` ⊆ §10;
   SPEC_BRIEF28 audit sealed to `55b4b7f`.
R. **Suite green** — `0 failed` on final commit; brief22–28 seals untouched/green; totals refreshed last.

## §13 — Test plan (unit · integration · deterministic-generator/property · adversarial · regression)
- **Unit:** each validator (tz-aware windows, `mode_max` literal, `UnattendedBudget` required/non-neg,
  watchdog rule 1..300, amendment-structure required fields incl. tz-aware `effective_at`); `min`
  behavior; `AutonomyError` on widening; `compute_manifest_id` determinism; `VerifiedManifest` production.
- **`_matches` regression-pin (D3):** tests asserting the exact `_matches` behavior this brief depends
  on (exact-literal host match True; non-match False; wildcard/glob target rejected upstream by the
  evaluator), so a future matcher change that would break per-auth binding fails loudly here.
- **Integration (hermetic):** sign → `load_and_verify` → `VerifiedManifest` → `effective_envelope` →
  `authorize` end-to-end on `manifest_factory`, socket-raise guard; `_matches` per-authorization binding
  and `BudgetLimits` conversion exercised through the real functions.
- **Deterministic generators (D5; NOT hypothesis):** bounded/exhaustive generators enumerating
  **combinations** of (mode × class × target-match × window-state × budget-state × destructive-state ×
  envelope-state × amendment-state incl. tightening-only/increase-only/mixed/invalid), asserting the
  nine invariants as explicit properties over the whole generated space — not just the hand-selected
  rows.
- **Adversarial (threat model §3, incl. #12/#13):** one test per abuse case asserting denial/fail-closed.
- **Regression:** canonical-bytes identity (D); back-compat Calm (A); full suite + brief22–28 seals.

### Decision table (every expected verdict derived from §8 prose; A|B|C only)
Legend: verdict ∈ ALLOW / DENY / ERROR / INCONCLUSIVE. "auth" = a matching signed
`unattended_authorization` exists for the request's class+concrete target+active window.

| # | mode | class | matching auth? | target | window | budget | destructive | envelope/amend | Expected |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Calm | A | yes | match | active | within | no | valid | **ALLOW** |
| 2 | Beast | A | yes | match | active | within | no | valid | **ALLOW** |
| 3 | Beast | A | **no** | match(scope only) | active | within | no | valid | **DENY** (no matching auth; scope≠authz) |
| 4 | Calm | B | yes | match | active | within | no | valid | **DENY** (B fails closed in Calm; no operator-approval) |
| 5 | Beast | B | yes | match | active | within | no | valid | **ALLOW** |
| 6 | Beast | B | **no** | match | active | within | no | valid | **DENY** |
| 7 | Calm | C | yes | match | active | within | no | valid | **DENY** (per-action operator authz deferred) |
| 8 | Beast | C | yes (explicit C+target+window) | match | active | within | no | valid | **ALLOW** |
| 9 | Beast | C | **no explicit C** | match | active | within | no | valid | **DENY** |
| 10 | Beast | A | yes | **no-match (binding)** | active | within | no | valid | **DENY** (per-auth binding, §4.2) |
| 11 | Beast | A | yes | **wildcard auth target** | active | within | no | valid | **DENY** (wildcard rejected this increment) |
| 12 | Beast | A | yes | match | **future** | within | no | valid | **DENY** |
| 13 | Beast | A | yes | match | **expired** | within | no | valid | **DENY** |
| 14 | Beast | A | yes | match | active | **over** | no | valid | **DENY** (budget) |
| 15 | Beast | A | yes | match | active | **None dim in signed budget** | no | valid | **DENY** (fail-closed; None≠unlimited) |
| 16 | Beast | C | yes | match | active | within | **yes**, destructive_allowed=T, auth.destructive=T | valid | **ALLOW** |
| 17 | Beast | C | yes | match | active | within | **yes**, destructive_allowed=F | valid | **DENY** |
| 18 | Beast | C | yes | match | active | within | **yes**, destructive_allowed=T, auth.destructive=F | valid | **DENY** (not inherited) |
| 19 | Beast | A | yes | match | active | within | no | **autonomy absent (old manifest)** | **DENY** (fail-closed Calm) |
| 20 | any | A | — | — | — | — | — | **malformed autonomy** | **ERROR**/fail-closed DENY |
| 21 | any | A | — | — | — | — | — | **invalidly-signed manifest** | **ERROR** (ManifestError upstream) |
| 22 | Beast | A | yes | match | active | runtime budget < signed | no | valid | **ALLOW** (runtime restricts; effective=min) |
| 23 | Beast | A | yes | match | active | **runtime budget > signed** | no | valid | **ERROR** (AutonomyError: widening) |
| 24 | Beast | A | yes | match | active | within | no | **valid root→one amendment, now ≥ effective_at** | **ALLOW** |
| 25 | Beast | A | yes (only via amendment increase) | match | active | within | no | **amendment, now < effective_at** | **DENY** (increase not yet effective) |
| 26 | Beast | A | yes | match | active | within | no | **broken amendment (bad sig / id mismatch)** | **DENY** (predecessor envelope in force) |
| 27 | Beast | A | yes | match | active | within | no | **amendment whose predecessor is itself an amendment** | **DENY** (fail closed; single-hop only) |
| 28 | Beast | A | yes | match | active | within | no | **amendment effective_at timezone-naive/missing** | **DENY** (fail closed, O3) |
| 29 | any | A | yes | match | active | within | no | **required eval input unavailable** | **INCONCLUSIVE** |
| 30 | Beast | A | yes (on predecessor) | match | active | within | no | **increase-only amendment pending, now < effective_at; request granted by predecessor envelope** | **ALLOW** (predecessor authoritative pre-effective_at, §8.1(2)) |
| 31 | Beast | A | yes | match | active | within | no | **mixed amendment (one axis increased + one tightened)** | **DENY** (mixed invalid, fail-closed; predecessor in force, §7/§8.1(3)) |
| 32 | Beast | A | yes | match | active | within | no | **effective envelope lacks provenance (bare AutonomyEnvelope) or provenance ≠ verified.manifest_id** | **DENY** (no verified provenance, §8.1(1)) |
| 33 | Beast | C | yes | match | active | within | **yes**; increase-only amendment sets destructive_allowed F→T, now < effective_at | **amendment pending** | **DENY** (predecessor destructive_allowed=F governs, §8.1(2); F-C) |
| 34 | Beast | C | yes | match | active | within | **yes**; same amendment, now ≥ effective_at, auth.destructive=T | **amendment in force** | **ALLOW** (increase now effective) |

### ⓘ Property invariants (explicit test properties over the generated space)
1. Runtime never expands authority (R>S on any scalar ⇒ AutonomyError; nothing allowed under effective
   that S disallows).
2. Beast alone grants nothing (empty authorizations ⇒ no external ALLOW regardless of mode).
3. Target isolation (auth for X never authorizes Y; per-auth `_matches` binding).
4. Class isolation (auth for K never authorizes J≠K).
5. Expiry monotonic (now outside [valid_from, valid_until] ⇒ never ALLOW).
6. Destructive never inherited (needs destructive_allowed ∧ auth.destructive).
7. Invalid, mixed, or single-hop-violating amendment preserves the last valid envelope (effective
   authority = predecessor's, never the increase); an increase-only amendment is inert before
   `effective_at` while the predecessor's own grants remain ALLOWed (§8.1(2)); a tightening-only
   amendment applies immediately.
8. Canonical serialization stable (logically-equal manifests ⇒ equal canonical bytes ⇒ equal
   manifest_id).
9. No authorization without verified provenance — a request is ALLOWed only when the evaluated
   `EffectiveEnvelope` carries provenance equal to the in-force `verified.manifest_id`; a non-provenanced
   or mismatched envelope authorizes nothing (§8.1(1)).

## §14 — Migration risks
- Pydantic required-vs-optional: new top-level `autonomy`/`amends` Optional; **inside** the autonomy
  block, budget/duration are REQUIRED (D6 safety) — intentional, only when an autonomy block is present.
  Old manifests (no block) unaffected (criterion A/D).
- `_flatten` must map **top-level** `autonomy` + top-level `amends` (both top-level `ScopeManifest`
  fields per §4/§5, not nested under `engagement`) or they silently drop (`manifest.py:73-86`) —
  explicit mapping + parse test.
- Canonicalization: additive-only keys; criterion D byte-identity regression.
- Default-Beast leak: default `"calm"`, criteria A/G/J, invariant 2.
- None-as-unlimited leak: criterion I; reject None budget dims at the autonomy boundary.
- Seal tax: seal SPEC_BRIEF28 audit to `55b4b7f` or the suite reds.

## §15 — Rollback strategy
Additive + unwired: one revert removes module, optional fields, tests; no data migration. Signed
manifests are external; old manifests unaffected; new autonomy blocks simply go unconsulted (nothing
reads the evaluator at runtime), so rollback has no live behavioral effect. No Kuzu/schema migration.

## §16 — Operator decisions (RESOLVED; context.md 2026-10-31)
- **O1 — `WATCHDOG_CONFIRM_WINDOW_MAX = 300` seconds.** `may_auto_stop=false` safe default; if true,
  `1 <= confirm_window_seconds <= 300`. Signed representation + validation only; no watchdog runtime.
- **O2 — No `LOCAL` class.** Taxonomy is `A | B | C` only; `LOCAL` schema member + decision-table row
  removed. Local-vs-target classification is a non-goal (§11), deferred to the capability-registry/
  wiring brief; it must never become a caller-controlled bypass.
- **O3 — `AmendmentRef.effective_at`** approved as the signed, tz-aware authenticated effective
  timestamp; covered by the signed canonical content (§5); permission increases cannot apply before it;
  missing/malformed/timezone-naive fails closed. No external timestamping authority required.
- **M1 — Verified authority boundary (rev3; context.md 2026-10-31).** Public authorization REQUIRES a
  `VerifiedManifest`-derived, provenance-bearing `EffectiveEnvelope`; a bare `AutonomyEnvelope` never
  authorizes (§8.1(1); criterion E; invariant 9).
- **M2 — Pending increases (rev3).** Before `effective_at` the verified predecessor is authoritative for
  **all** inputs; at/after, the verified amendment; an invalid amendment never replaces the predecessor
  (§8.1(2); criterion M; rows 25, 30, 33-34).
- **M3 — Mixed amendments (rev3).** Rejected fail-closed; tightening-only is immediate, increase-only is
  deferred to `effective_at`; mixed intent requires separate amendments (§7; §8.1(3); criterion M; row 31).

(D1–D7 and P0/P1 are dispositioned in the review packet; this schema reflects the accepted forms.)
