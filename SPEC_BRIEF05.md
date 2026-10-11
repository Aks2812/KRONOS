# KRONOS — SPEC (Brief #0.5): Seeded Cross-Domain Range (CyberGym X-instrument)

## RUN CONTEXT (local Kali session)
Local Claude Code session on the operator's Kali VM (NOT cloud — needs Docker,
LocalStack, a running API). The KRONOS repo is checked out with Brief #1 + #2
merged to main. Branch off main. This builds a SEPARATE, self-contained
vulnerable-by-design lab used to TEST KRONOS — it is not part of the KRONOS
framework itself. Put it under a top-level `cybergym/` directory (or similar),
clearly separated from `src/kronos/`.

## WHAT THIS BUILDS
A deliberately-vulnerable, fully LOCAL three-tier lab with K known planted
cross-domain attack chains (start K=3), used to measure KRONOS's cross-domain
score (X in CyberGym v1.0): the % of planted mobile → API → cloud chains KRONOS
discovers AND validates end-to-end. Because you plant every chain, the lab is
perfect ground truth and contamination-proof (nothing public).

## SECURITY POSTURE (INVERTED for this brief)
This lab is SUPPOSED to be insecure — that's the point. BUT it must be fully
contained:
- Everything LOCAL only: localhost-bound services, mock cloud (LocalStack or
  equivalent), NO real cloud accounts, NO real credentials, NO internet-facing
  exposure, NO real secrets. Every "secret" is a fake test value.
- Must be trivially stand-up / tear-down (docker-compose up/down) and leave
  nothing running or exposed after teardown.

## DECISIONS ALREADY MADE (locked)
- Purpose: the measurement instrument for CyberGym X-score. The planted chains
  MUST match how KRONOS's graph + (future) validation layer define a validated
  chain: a SECRET confirmed live whose authenticates_to target is an in-scope
  asset, reachable end-to-end via find_paths.
- Contamination-proof: entirely custom/synthetic. No known-vulnerable public app.
- Vary realism across the K chains to stress different extraction paths:
  at least one plaintext secret, one lightly obfuscated (Base64/split), one in a
  non-obvious location (e.g. a resource file vs BuildConfig).

## ESCALATION CONTRACT (Balanced)
Proceed on all lab-construction details autonomously; log in DECISIONS.md. STOP
(FORK format) only if: a planted chain can't be made to match KRONOS's
validated-chain definition; a dependency (LocalStack, Android build tooling)
can't be installed; or a design choice would change what the X-score actually
measures.

## WHAT TO BUILD — three tiers + K chains
1. MOBILE tier: a minimal, debuggable Android APK (source included, reproducibly
   built — commit the build script, no mystery blob; reuse the Brief #2 fixture
   approach). Plant, across the K chains: a hardcoded API key, a hardcoded
   internal/undocumented base URL + endpoint, and a reference to a cloud resource.
   Vary obfuscation/location per chain as above.
2. API tier: a small backend (FastAPI/Flask) with endpoints the APK's planted keys
   actually authenticate to — including at least one UNDOCUMENTED endpoint only
   discoverable from the app. The API must actually ACCEPT the planted key and
   REJECT a wrong one (so liveness validation has something real to test).
3. CLOUD tier: LocalStack with resources (e.g. an S3 bucket, an over-privileged
   IAM role) that ONE of the planted keys actually unlocks — and that a wrong
   key does not. Again, real accept/reject behavior.
Each chain must be a genuinely traversable path:
   SECRET-in-APK --authenticates_to--> API_ENDPOINT or CLOUD_RESOURCE (in-scope),
   live and verifiable.

## GROUND TRUTH (the grading key)
Ship `ground_truth.yaml` listing every planted chain: the secret (and its
location + obfuscation level), its live target, the full expected path, and how
to verify it's live. This is what CyberGym grades KRONOS's X-score against.
Also ship the matching SIGNED scope manifest (Brief #1 format) that puts the
whole lab in-scope — so KRONOS can be pointed at it legally under its own rules.

## ALSO SHIP — the ancestor-control runbook
A short runbook for pointing RedAmon / PentAGI / Shannon at the SAME lab, so
their ~0 score on the mobile-origin chains (they can't ingest the APK) charts
side-by-side against KRONOS. This side-by-side is the single strongest evidence
of KRONOS's differentiation — design the lab so that comparison is clean (the
web/API tier should be something the ancestors CAN scan, so the delta is purely
the mobile-origin chains).

## DELIVERABLES
docker-compose lab (3 tiers), the planted APK + reproducible build script, the
API, the LocalStack config, ground_truth.yaml, the in-scope signed manifest, the
ancestor-control runbook, a self-test that stands the lab up and verifies each
planted chain is actually live (key works, wrong key fails), DECISIONS.md, and a
README (stand-up / tear-down, safety notes).

## DO NOT
Expose anything beyond localhost. Use any real cloud account or real credential.
Build KRONOS-side validation logic (that's Brief #3 — this is only the TARGET).
Make any chain that doesn't match KRONOS's validated-chain definition.

## FINISH
Branch off main, commit in logical steps, push, open a PR: the plan, what was
built, the K planted chains summarized, the self-test result (all chains live),
and stand-up/tear-down instructions.
