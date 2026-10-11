# KRONOS — SPEC (Brief #2): Mobile Static Ingestion

## RUN CONTEXT (local Kali session)
You are running as a LOCAL Claude Code session on the operator's Kali Linux VM —
NOT a cloud session. This brief needs tools that live on this machine (MobSF,
apktool/jadx). The KRONOS repo is checked out here with Brief #1 already merged
to main. Branch off main. When done, push the branch and open a PR.

## WHAT THIS BUILDS
The mobile static-analysis ingestion layer: take an APK (and later IPA), run it
through static analysis, and turn the results into real nodes/edges in the KRONOS
findings graph built in Brief #1 — replacing the single hardcoded reference
ingester with real parsers. This is KRONOS's differentiator made real: secrets
and endpoints extracted from a mobile app, written as graph nodes that can chain
to API/infra/cloud.

## HOW TO BUILD THIS (skills + workflow)
- Plan first (writing-plans); show the plan before coding.
- Data-modeling pass is NOT needed — the graph schema and ingestion contract are
  FIXED by Brief #1 (see below). You target the existing contract; you do not
  design a new one.
- Write invariant/behavior tests FIRST per the testing-with-discernment approach:
  tests that fail if extraction misses a planted secret, not coverage padding.
- Security lens on the parser: treat the APK and all MobSF output as UNTRUSTED
  input. A malicious app could contain crafted strings designed to break your
  parser or inject into the graph. The Brief #1 upsert allowlist protects the
  graph, but your parser must not crash or mis-wire on hostile input.
- Log autonomous decisions in DECISIONS.md. Use the FORK format for anything that
  hits the escalation bar.

## DECISIONS ALREADY MADE (locked — do not re-ask)
- The findings graph (Kùzu) and its write API exist and are merged. You import and
  use them; you do NOT modify schema.py's node/edge types or the lifecycle rules.
- The ingestion contract is FIXED (from Brief #1): ingest(raw, tool_name,
  engagement) -> list of NodeUpsert/EdgeUpsert; apply_upserts() writes them,
  MERGE-deduped, resolving edge endpoint types itself. EdgeUpsert carries
  (label, from_id, to_id, props) only. You ADD a new tool_name branch for mobile;
  you do not change the contract's shape.
- upsert_node enforces a props allowlist and scope-stamps via scope_guard. You
  cannot set in_scope/status/confidence through props — that's by design. Extracted
  secrets enter at status='extracted', confidence derived (<7). You do NOT advance
  their status in this brief — validation (is the key live? does it authenticate to
  an in-scope asset?) is a LATER brief. This brief only EXTRACTS and RECORDS.
- Static-first: this brief is static analysis only. No Frida, no emulator, no
  running the app. The dynamic stream is a later brief; leave source='static' on
  every mobile node you write.
- MobSF is the analysis anchor. Prefer orchestrating MobSF (its REST API or CLI)
  over reimplementing decompilation. Supplement with lighter targeted extractors
  (e.g. apkleaks-style secret/endpoint regex) where MobSF's output is thin.

## ESCALATION CONTRACT (Balanced)
Proceed on anything reversible/below the architecture-safety line; log it. STOP
and escalate (FORK format: FORK / OPTIONS / RECOMMENDATION / DEFAULT IF NO ANSWER)
only for: a change to the graph schema or ingestion contract; a security-critical
parser tradeoff; an ambiguity where guessing wastes substantial work; or a tool
(MobSF etc.) that can't be installed/run on this machine.

## TOOL PREFLIGHT (do this first — JOTNAR lesson)
Before building, verify what's actually installed and how it's invoked, and write
it to a TOOLS_mobile.md the parser can rely on: is MobSF present (as a running
server? a Docker container? a local install?) and reachable; is its REST API key
available; are jadx/apktool present. If MobSF is NOT installed, that's a FORK —
present options (install via Docker / install native / proceed with lighter
extractors only) rather than guessing.

## WHAT TO EXTRACT → WHICH NODE/EDGE (the mapping)
From static analysis of an APK, produce these graph writes (all source='static'):
- MOBILE_APP node — the app itself (package name as id, version, etc.).
- MOBILE_COMPONENT nodes — exported activities/services/receivers/providers from
  the manifest, with exported flag. Edge: MOBILE_APP -contains-> MOBILE_COMPONENT.
- SECRET nodes — hardcoded API keys/tokens/credentials found in strings.xml,
  BuildConfig, resources, decompiled code. value_ref = sha256 pointer (NEVER the
  plaintext secret inline — store the blob via the evidence store, matching
  Brief #1's hash-addressed pattern). Edge: MOBILE_APP/MOBILE_COMPONENT -leaks->
  SECRET. status='extracted'.
- API_ENDPOINT nodes — base URLs and API endpoints referenced in the app
  (including undocumented/internal hosts). Edge: MOBILE_APP -references->
  API_ENDPOINT.
- EVIDENCE — for each secret and each notable finding, store the supporting blob
  (the file + location it was found) via the Brief #1 evidence store, hash-addressed.
Do NOT invent node/edge types beyond Brief #1's schema. If something doesn't fit,
that's a FORK, not a freelance schema change.

## DELIVERABLES
1. A mobile ingestion module that orchestrates MobSF (+ light extractors) on an
   APK and emits NodeUpserts/EdgeUpserts through the EXISTING ingest contract.
2. The new tool_name branch wired into ingest().
3. TOOLS_mobile.md (preflight result).
4. Tests: against a KNOWN sample APK with PLANTED artifacts (you create a tiny
   deliberately-leaky test APK, or use a documented known-vulnerable one), prove
   extraction finds the planted secret + endpoint and writes the correct
   mobile->secret / mobile->api edges, deduped on re-run. Include a hostile-input
   test (malformed/crafted strings don't crash or mis-wire).
5. DECISIONS.md additions + a README for the mobile module.

## DO NOT BUILD
Dynamic analysis / Frida / emulator. Secret VALIDATION (liveness, authenticates_to
wiring to real API/cloud assets) — that's a later brief. Reporting. Agent logic.
Any change to Brief #1's schema, lifecycle, or ingestion contract.

## FINISH
Branch off main, commit in logical steps, push, open a PR whose description has:
the plan, what was built, the preflight result (what MobSF setup you used), any
FORK items, and how to run the tests.
