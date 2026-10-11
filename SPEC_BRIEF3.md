# KRONOS — SPEC (Brief #3): Secret Validation (extracted → validated → reachable)

## RUN CONTEXT (local Kali session)
Local Claude Code session on the operator's Kali VM (NOT cloud — it exercises the
running CyberGym range: localhost API + SigV4-proxied LocalStack S3). KRONOS repo
checked out with Briefs #1/#2/#0.5 merged to main. Branch off main. Push + open a PR
when done.

## WHAT THIS BUILDS — the differentiator, going live
The validation layer that advances a SECRET through its lifecycle by ACTUALLY TESTING it:
  extracted  -> validated   (the secret is confirmed LIVE against a real endpoint)
             -> reachable    (it authenticates_to an IN-SCOPE asset, edge wired + proven)
Until now secrets stop at 'extracted'. This brief makes KRONOS prove a cross-domain
chain end-to-end: a secret pulled from an APK (Brief #2) is tested against an API/cloud
asset, and if it works AND the target is in-scope, the authenticates_to edge is created
and the secret reaches 'reachable'. That is the mobile→API→cloud chain, demonstrated —
and it's exactly what CyberGym's X-score measures.

## DECISIONS ALREADY MADE (locked — do not re-ask)
- The lifecycle, graph schema, and status transitions are FIXED by Brief #1. You call
  the existing advance_secret_status; you do NOT change the state machine or schema.
- A secret reaches 'validated' ONLY on a REAL successful authentication against a live
  endpoint — never on a heuristic, a format match, or an LLM guess. No live proof → it
  stays 'extracted'. (This is the "prove it or drop it" principle; do not weaken it.)
- A secret reaches 'reachable' ONLY when: (a) it is 'validated', AND (b) its
  authenticates_to target is in_scope==true per the scope guard. An out-of-scope target
  → record the edge/note but the secret does NOT become reachable and can never anchor a
  finding (Brief #1 rule 4). Enforce via the existing scope_guard + lifecycle rules.
- Validation is a READ/AUTH-CHECK operation only: confirm a credential works (e.g. an
  authenticated GET, an S3 ListObjects/GetObject, an API call that returns 200 vs 401).
  NO destructive actions, NO writes, NO privilege use beyond proving the credential
  authenticates. (Autonomy-scales-with-reversibility: this is the read side.)
- EVERY validation attempt is scope-gated FIRST: never send a credential to a target
  the scope guard marks out-of-scope. The scope check happens before any network call.
- Evidence: every 'validated' transition stores evidence (the request made + the
  authenticated response proof) via Brief #1's hash-addressed evidence store, wired via
  evidences. No evidence → the transition is invalid.

## VALIDATOR DESIGN
Build a validator registry keyed by SECRET.kind, each validator = a pure
"does this credential authenticate to this target, yes/no + evidence" probe:
- api_key / token / bearer → authenticated HTTP request to the referenced API_ENDPOINT;
  200-class with expected shape = live, 401/403 = not. Use the app-declared base URL +
  endpoint already in the graph (references edge from Brief #2).
- aws / cloud credential pair → boto3 (or SigV4) call against the cloud resource
  (ListObjects/GetObject on the referenced bucket). Success = live. Honors the SigV4
  proxy the CyberGym range uses.
- Extensible: unknown kinds → no validator → secret stays 'extracted', logged, never
  guessed live.
The validator takes (secret, candidate_target) where candidate_target comes from the
graph's existing references/authenticates_to-candidate edges — it does NOT invent targets.

## ESCALATION CONTRACT (Balanced)
Proceed on reversible/below-the-line details; log in DECISIONS.md. STOP (FORK format:
FORK / OPTIONS / RECOMMENDATION / DEFAULT IF NO ANSWER) only for: a change to the
lifecycle/schema/scope contract; a security-critical validator tradeoff (e.g. anything
that would send a credential off-scope, or a "treat as live without proof" shortcut); an
ambiguity where guessing wastes substantial work; or a dependency that can't be installed.

## HOW TO BUILD (skills + workflow)
- Plan first (writing-plans); show the plan before coding.
- Security lens hard here (security-discipline): this is the layer that TRANSMITS
  credentials. The scope-gate-before-send rule and the no-destructive-action rule are the
  two invariants that must hold under adversarial input. Treat a wrong scope decision as a
  critical bug.
- Invariant tests FIRST (testing-with-discernment), run against the CyberGym range:
  * a live, in-scope secret → validated (with evidence) → reachable, authenticates_to edge created
  * a live but OUT-OF-SCOPE target → secret validated at most, NEVER reachable, never anchors a finding, edge flagged as note
  * a dead/wrong secret → stays 'extracted', no edge, no evidence
  * a credential is NEVER sent to an out-of-scope target (assert the scope check blocks the call BEFORE any network attempt — mock/spy the transport to prove no packet leaves for off-scope)
  * confidence after 'reachable' matches the Brief #1 derived cap (no inflation)
- End-to-end proof: run the full CyberGym range and show KRONOS take all 3 planted
  secrets from 'extracted' to their correct terminal state, producing the validated
  cross-domain chains that ground_truth.yaml says exist. THIS is the X-score going live.

## DELIVERABLES
1. Validator registry + the api/cloud validators.
2. Wiring: given the graph post-mobile-ingestion, attempt validation on each extracted
   secret against its candidate targets, scope-gated, advancing status + writing evidence
   + creating authenticates_to edges per the rules.
3. The invariant tests above, green, run against the live CyberGym range.
4. An end-to-end run output showing the 3 planted chains validated (compare to
   ground_truth.yaml) — the first real X-score measurement.
5. DECISIONS.md additions + README for the validation module.

## DO NOT BUILD
Agents / the autonomous loop (that's the agent layer). Reporting. Any destructive or
write action. Any change to Brief #1's lifecycle/schema/scope. Any validator that marks
a secret live without a real successful auth + evidence. Infra/web/cloud INGESTION (this
brief validates secrets that already exist in the graph; it doesn't add new ingestion
sources).

## FINISH
Branch off main, commit in logical steps, push, open a PR whose description has: the
plan, the validator design, the invariant-test results, the end-to-end CyberGym run
(3 chains validated vs ground_truth), any FORK items, and how to run it.
