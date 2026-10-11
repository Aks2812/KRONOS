# KRONOS — SPEC (Brief #1): Findings Graph Core + Validation Lifecycle

## RUN CONTEXT (cloud session)
You are running as a Claude Code cloud session on an isolated VM. The project
repo is already cloned. Build into this repo. When finished, push your work to a
new branch and open a PR — that is how the operator receives the result. Do not
expect access to any local machine, Kali tools, or network targets; this brief
is pure Python and needs none of them. `kuzu` and `pytest` are installed via the
environment setup script; if an import is missing, add it to requirements and note it.

## HOW TO BUILD THIS (skills + workflow)
- Turn this SPEC into a step-by-step plan first (use a planning skill). Show the
  plan in the PR description or an early commit before large code lands.
- Do a dedicated design pass on the Kùzu schema and query interface before
  implementing — it is the foundation everything queries; changing it later is costly.
- Write the INVARIANT tests (listed under Deliverables) FIRST, before the code
  they test. These are safety invariants, not coverage theater — a test that
  passes while the invariant is broken is a failure.
- Review the scope_guard and validation-lifecycle code with a SECURITY lens:
  assume an attacker tries to get an out-of-scope target or an unproven finding through.
- Use subagents for reading large amounts of code and returning conclusions, to
  keep context lean. Give each a self-contained task.
- Write a short README per module (future-maintainer level; single-operator tool).

## DECISIONS ALREADY MADE (do NOT re-ask — locked)
- KRONOS = single-operator, autonomous pentest framework for AUTHORIZED
  external-client engagements. Differentiator = CROSS-DOMAIN correlation with
  MOBILE as a first-class source domain (mobile → API → infra → cloud chains),
  which no existing tool does.
- Graph store = Kùzu (embedded, Cypher-compatible, single file). One DB file PER
  ENGAGEMENT, fully isolated. No server. Do not propose Neo4j or SQLite — settled.
- Scope binding is enforced in CODE at the data/tool boundary, never via prompt
  wording. The signed scope manifest is the only authorization object.
- Autonomy scales with reversibility (not exercised in this brief — no live actions here).
- Mobile is static-first in v1; the dynamic/Frida stream is a pre-wired schema
  slot (source='dynamic') to fill later with NO schema change.
- The SECRET node is the cross-domain linchpin. Validation lifecycle + evidence-
  gated confidence are mandatory. "No evidence, no report."
- LLM/agents NEVER ingest raw tool output; they query the graph. (No LLM calls in this brief.)

## ESCALATION CONTRACT (Balanced autonomy)
Default: PROCEED on your own judgment for anything reversible and below the
architecture/safety line. Log every non-trivial autonomous decision in a
DECISIONS.md file in the repo. Do NOT stop for naming, file layout, property
details, or library choices — decide, log, move on.

STOP and escalate (leave it as an open question in the PR description) ONLY when:
  1. A choice changes the schema's core shape, the query-interface contract, or a safety invariant.
  2. An ambiguity where guessing wrong wastes substantial work.
  3. A security-critical tradeoff in the scope guard or validation lifecycle.
  4. A required dependency cannot be installed in this environment.
When you stop, record it in this exact form in the PR:
  FORK: <the decision>
  OPTIONS: <2-3 options, one line each>
  RECOMMENDATION: <your pick + one-clause why>
  DEFAULT IF NO ANSWER: <what you'll do>
Keep building everything else meanwhile.

## TECHNOLOGY
Python 3.11+. Kùzu embedded. pytest. No network calls in this module.

## SCOPE MANIFEST FORMAT (the authorization object — implement exactly)
A signed YAML file loaded at engagement init:
  engagement:
    id: <slug>
    client: <name>
    authorized_by: <signatory name>
    window_start: <ISO8601>
    window_end: <ISO8601>
    destructive_allowed: <bool, default false>
  scope:
    in_scope:   [ <globs: FQDN, CIDR, URL pattern, mobile bundle id, API host> ]
    excluded:   [ <globs — evaluated FIRST, hard deny> ]
  signature: <detached signature over the canonicalized content above>
At init: verify the signature (reject unsigned/invalid); verify current time is
within [window_start, window_end] (reject if outside).

## NODE TYPES (build all; populate per v1 scope)
ENGAGEMENT, HOST, SERVICE, WEB_ENDPOINT, PARAMETER, API_ENDPOINT, MOBILE_APP,
MOBILE_COMPONENT, SECRET, IDENTITY, CLOUD_RESOURCE, TECHNOLOGY, FINDING, EVIDENCE
Every node: id, in_scope(bool), created_at, source('static'|'dynamic'|'infra'|'web'|null),
+ type-specific props. At minimum:
- ENGAGEMENT: parsed manifest fields + destructive_allowed
- SECRET: value_ref (sha256 pointer — NEVER plaintext inline), kind, status, confidence
- FINDING: title, severity, status, confidence
- EVIDENCE: sha256, blob_path, kind, created_at (immutable, hash-addressed)
Propose sensible props for the rest; log them in DECISIONS.md.

## EDGE TYPES
hosts, exposes, has_param, contains, leaks, references, authenticates_to, grants,
shares_cred_with, depends_on, vulnerable_to, resolves_to, chains_to, evidences.
(leaks / references / authenticates_to / shares_cred_with / chains_to are the
cross-domain edges — model them carefully.)

## VALIDATION LIFECYCLE (the false-positive killer — ENFORCE in code, with tests)
SECRET.status:  extracted -> validated(confirmed live) ->
                reachable(authenticates_to an IN-SCOPE asset) -> dead
FINDING.status: hypothesis -> reachable(source->sink path exists) ->
                exploited(PoC in evidence) -> reported | discarded
Hard rules (enforced, not just documented):
 1. FINDING -> 'reported' ONLY if status==exploited AND it has >=1 EVIDENCE node.
 2. SECRET anchors a reported finding ONLY if status==reachable AND its
    authenticates_to target has in_scope==true.
 3. confidence DERIVED from status, never set freely:
    exploited / reachable+evidence => 9-10 ; validated => 7-8 ;
    hypothesis / extracted => <7 (hard cap). Inflation must be impossible.
 4. A SECRET whose only authenticates_to target is out_of_scope is RECORDED but
    flagged as a note — never actioned, never reported.

## SCOPE GUARD (the only scope mechanism)
scope_guard(target, manifest) stamps in_scope on every node at creation:
excluded globs first (deny), then in_scope globs (allow), default DENY.
Out-of-scope nodes may exist but can never anchor a finding or be an action target.

## INGESTION CONTRACT (define interface; stub parsers)
Define: ingest(raw_tool_output, tool_name, engagement) -> list of node/edge upserts.
Upserts MERGE (dedup) — same host:port updates, never duplicates. Implement ONE
reference ingester (a hardcoded SECRET + its 'leaks' edge from a MOBILE_APP) to
prove the contract. Real parsers = a later brief.

## QUERY INTERFACE (the ONLY way agents read the graph — build these)
- query_graph(filter) -> matching nodes/edges
- get_evidence(hash) -> blob
- find_paths(from_filter, to_filter, max_hops) -> cross-domain chains
  (e.g. SECRET -> * -> CLOUD_RESOURCE where in_scope). The differentiator's core
  query — make it first-class and fast.
- list_findings(status=...) / list_secrets(status=...)

## V1 SCOPE (build vs stub)
FULLY build: ENGAGEMENT, MOBILE_APP, MOBILE_COMPONENT, SECRET, WEB_ENDPOINT,
PARAMETER, API_ENDPOINT, FINDING, EVIDENCE, IDENTITY + their edges + full
validation lifecycle + scope guard + query interface.
STUB (schema defined, minimal writer only): HOST, SERVICE, CLOUD_RESOURCE, TECHNOLOGY.

## DELIVERABLES
1. Kùzu schema (DDL) for all nodes/edges.
2. Python graph layer: per-engagement DB init, manifest load+verify, scope_guard,
   upsert/merge, query interface, lifecycle enforcement.
3. Reference ingester + the worked example (mobile secret -> leaks edge).
4. INVARIANT TESTS (written first): no-evidence finding can't be reported;
   out-of-scope secret can't anchor a finding; confidence can't exceed its status
   cap; expired/unsigned manifest is rejected; find_paths returns a seeded
   mobile->cloud chain.
5. DECISIONS.md (your autonomous calls) + short per-module README.

## DO NOT BUILD YET
Agents, LLM calls, real parsers (beyond the one reference), dynamic/Frida,
reporting, orchestration. Foundation only.

## FINISH
Commit in logical steps. Push to a branch. Open a PR whose description contains:
the plan, a summary of what was built, any FORK items from the escalation contract,
and how to run the tests.
