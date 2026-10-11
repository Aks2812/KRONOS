# Ancestor-control runbook

Point RedAmon / PentAGI / Shannon (or any other AI-pentest tool without
mobile ingestion) at this same lab, so their score on the **same K=3
chains** charts side-by-side against KRONOS's. This comparison is
SPEC_BRIEF05's single strongest piece of evidence for KRONOS's
differentiation.

## Why the comparison is clean

The API tier (`http://localhost:8091`) is an **ordinary, scannable web
API** — `/health`, `/items/{id}`, and a normal `/openapi.json`/`/docs`
schema. Any of the ancestor tools can point a standard web scanner at it
exactly as they would any target and enumerate those endpoints fine.

What none of them can do is **ingest the mobile APK**
(`cybergym/mobile/cybergym_lab.apk`). Every one of this lab's 3 planted
chains originates there:

- **Chain 1**'s target endpoint (`/internal/v1/admin/export`) is
  deliberately excluded from the OpenAPI schema (`include_in_schema=
  False`) — a web-only scanner has no way to discover its path, and even
  if it stumbled on the path, it has no way to discover the required
  `X-Cybergym-Key` value, which only exists inside the APK.
- **Chains 2 and 3**'s targets are LocalStack S3 buckets behind the
  SigV4 proxy — reachable only with credentials that exist nowhere but
  inside the APK (plaintext/Base64/split, per `ground_truth.yaml`).

So an ancestor tool pointed at `http://localhost:8091` alone should score
**0/3** on this lab's chains — not because the lab is unfair to them, but
because every planted chain is mobile-origin by construction. That 0/3
next to KRONOS's score (if KRONOS's future validation layer finds and
validates all 3) is the delta SPEC_BRIEF05 wants charted.

## Steps

1. Stand the lab up: `cd cybergym && docker compose up -d --build` (see
   `README.md` for full stand-up/tear-down).
2. Point the ancestor tool at `http://localhost:8091` as its target —
   give it exactly what you'd give it for any ordinary API pentest
   target (the base URL; optionally the OpenAPI schema at
   `http://localhost:8091/openapi.json` if the tool accepts a schema
   hint). **Do not** give it the APK, the scope manifest, or
   `ground_truth.yaml` — those are KRONOS-side (and grading-side) inputs
   only.
3. Let it run its normal scan/exploit workflow against that target.
4. Record its findings against `ground_truth.yaml`'s 3 chains. Expected
   result: 0 of the 3 chains are found, because none are reachable from
   the API tier alone — `/items/{id}` and `/health` are real but
   unrelated to any planted chain, and the undocumented endpoint +
   cloud credentials are inside the APK the tool never sees.
5. Report this 0/3 next to KRONOS's own X-score run on the identical
   lab, same scope manifest, same ground truth.

## Safety note

Nothing about running an ancestor tool against this lab changes the
security posture: it's still fully local-only (see "Security posture" in
`README.md`). No additional exposure is introduced by also pointing a
second tool at `localhost:8091` — just don't expose that port beyond
localhost to let a remote ancestor-tool service reach it.
