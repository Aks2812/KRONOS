# DECISIONS.md — Brief #1 (Findings Graph Core + Validation Lifecycle)

Every non-trivial autonomous call made while building this brief, per the
escalation contract in `SPEC.md`. The build-time decisions below each
were a naming/property/file-layout/library detail, or a straight bug fix
caught by its own test, with low cost if wrong — none needed a `FORK`
stop. Two `FORK` items *were* raised during the final whole-branch
review (see that section at the end) and are flagged in the PR
description per the escalation contract's format.

Format: **Decision** / **Why** / **Reversibility**.

---

## Manifest (`manifest.py`)

**Canonicalization format.** `canonicalize(data)` is
`yaml.safe_dump(data, sort_keys=True, default_flow_style=False).encode("utf-8")`
over the manifest content with the `signature` key excluded.
**Why:** needs to be deterministic (same logical manifest → same bytes
regardless of dict insertion order) and symmetric between signing and
verifying; sorted-key YAML dump is simple, inspectable, and this module
owns both the signer and the verifier so there's no cross-tool format to
match. **Reversibility:** easy — both sides live in this one module; a
future brief adding a separate signing tool just needs to call
`canonicalize`/`sign_manifest` rather than reimplement the format.

**Public key is passed explicitly, never auto-discovered.**
`load_and_verify(yaml_text, public_key)` takes the verifying key as a
parameter; there is no "look for a `.pub` file next to the manifest"
convention. **Why:** auto-discovery of a trust anchor from the filesystem
next to the thing it's supposed to verify is a classic way to make
signature verification meaningless (an attacker who can place a bad
manifest can usually place a bad "trusted" pubkey beside it too). The
caller — whatever loads the engagement — is responsible for having the
real public key from an out-of-band source. **Reversibility:** easy;
callers could add a discovery convention later without changing this
function's contract.

**Engagement window check uses timezone-aware UTC `now()`.** **Why:**
avoids naive-datetime comparison bugs; SPEC.md's window fields are ISO8601
and pydantic parses them as timezone-aware when the string carries an
offset. **Reversibility:** trivial.

## Scope Guard (`scope_guard.py`)

**CIDR patterns only match bare IP targets, never hostname strings.**
A pattern containing `/` is tried as `ipaddress.ip_network` first; if the
*target* doesn't parse as a bare IP, the CIDR branch is skipped and the
pattern falls through to plain glob matching instead of ever matching a
hostname. **Why:** without this, `10.0.0.0/8` would never accidentally
collide with a URL path containing a slash, and a CIDR scope entry stays
meaningfully distinct from a URL-pattern scope entry. **Reversibility:**
easy, isolated to `_matches`.

**Excluded-first, default-deny, no third state.** Exactly as SPEC.md
states it; there is no "neutral"/"unknown" scope value — every target is
either `True` or `False`. **Reversibility:** this one is load-bearing for
the safety invariant and shouldn't move without re-auditing every caller.

## Schema (`schema.py`)

**`EDGE_PAIRS`: the exact (FROM, TO) node-type pairs per edge label.**
SPEC.md names the 14 edge labels but not their endpoint types; the pairs
in `schema.py` are this module's own design call, chosen to mirror the
mobile→API→infra→cloud attack-chain story the SPEC's "What makes KRONOS
different" section describes (e.g. `leaks` spans
`MOBILE_APP/MOBILE_COMPONENT/API_ENDPOINT/WEB_ENDPOINT -> SECRET` because
a secret can leak from any of those surfaces, not just a mobile app).
**Why these specific pairs and not others:** each pair was chosen to be
the minimum set that lets every node type in SPEC.md's "FULLY build" list
participate in at least one plausible chain without inventing edges SPEC.md
never named. **Reversibility:** moderate cost to change later — `EDGE_PAIRS`
is consumed only by `_rel_table_group_ddl()`, so widening a pair set is a
backward-compatible schema migration (Kuzu's rel groups support adding
pairs), but *narrowing* one after real data exists would need a migration
plan. Full table, for reference:

| Label | Pairs |
|---|---|
| `hosts` | HOST→SERVICE, CLOUD_RESOURCE→HOST, CLOUD_RESOURCE→SERVICE |
| `exposes` | HOST→WEB_ENDPOINT, HOST→API_ENDPOINT, SERVICE→WEB_ENDPOINT, SERVICE→API_ENDPOINT |
| `has_param` | WEB_ENDPOINT→PARAMETER, API_ENDPOINT→PARAMETER |
| `contains` | MOBILE_APP→MOBILE_COMPONENT |
| `leaks` | MOBILE_APP→SECRET, MOBILE_COMPONENT→SECRET, API_ENDPOINT→SECRET, WEB_ENDPOINT→SECRET |
| `references` | MOBILE_APP→API_ENDPOINT, MOBILE_COMPONENT→API_ENDPOINT, WEB_ENDPOINT→API_ENDPOINT, FINDING→SECRET, FINDING→EVIDENCE |
| `authenticates_to` | SECRET→API_ENDPOINT, SECRET→CLOUD_RESOURCE, SECRET→HOST, IDENTITY→API_ENDPOINT, IDENTITY→CLOUD_RESOURCE |
| `grants` | IDENTITY→CLOUD_RESOURCE |
| `shares_cred_with` | SECRET→SECRET |
| `depends_on` | SERVICE→SERVICE, API_ENDPOINT→SERVICE, CLOUD_RESOURCE→CLOUD_RESOURCE |
| `vulnerable_to` | HOST/SERVICE/WEB_ENDPOINT/API_ENDPOINT/CLOUD_RESOURCE/MOBILE_APP/MOBILE_COMPONENT → FINDING |
| `resolves_to` | HOST→HOST, API_ENDPOINT→HOST, WEB_ENDPOINT→HOST |
| `chains_to` | API_ENDPOINT→HOST, API_ENDPOINT→CLOUD_RESOURCE, HOST→CLOUD_RESOURCE, SERVICE→CLOUD_RESOURCE, FINDING→FINDING |
| `evidences` | EVIDENCE→FINDING, EVIDENCE→SECRET |

**`FINDING -[:references]-> SECRET` is the "anchor" edge.** SPEC.md's
validation-lifecycle rule 2 ("SECRET anchors a reported finding only
if...") implies some edge connects a FINDING to the SECRET(s) that
support it, but never names which of the 14 labels that is. Chose
`references` (FINDING→SECRET) over inventing a 15th label, since
"references" already reads naturally as "this finding relies on this
secret." **Reversibility:** moderate — `lifecycle.advance_finding_status`
is the only place that queries this edge, so redirecting it to a
different label later is a one-line change plus a data migration if any
engagement already has `references` edges from an unrelated source.

**`ENGAGEMENT` keeps an `in_scope` column (hardcoded `True`); `EVIDENCE`
has no `in_scope` column at all.** **Why the asymmetry:** `ENGAGEMENT`'s
schema already had to carry manifest-derived fields that look like every
other node's shape, so giving it the column and hardcoding it costs
nothing. `EVIDENCE` was deliberately scoped out of `upsert_node`'s
in-scope handling entirely (see `graph.py`'s `_NO_IN_SCOPE_COLUMN_TYPES`)
because the brief's own Step 3 DDL spec for `EVIDENCE` lists no
`in_scope`/`source` columns — and an evidence blob genuinely isn't a
scope target: it's an artifact attached to a finding/secret, never
independently in or out of scope. **Reversibility:** easy; adding the
column later is a harmless schema addition.

## Graph (`graph.py`)

**`upsert_edge(label, from_id, from_type, to_id, to_type, props=None)` —
5 arguments, endpoint types explicit, not inferred.** Kùzu's rel-table-group
`MERGE` needs to know which of a label's declared `(FROM, TO)` pairs to
use; there is no "any type" wildcard, and guessing a bare id's type by
scanning every node table would be slower and still ambiguous if two
tables ever shared an id scheme. **Reversibility:** this is now the
contract every other module calls; changing it later touches
`lifecycle.py`, `evidence.py`, `ingest.py`, and every test file.

**`upsert_node`'s `confidence` sentinel.** For `SECRET`/`FINDING` nodes,
if the caller's `props` don't include `confidence`, `upsert_node` writes
`0` rather than leaving the column `NULL`. **Why:** a freshly-created
node (before any lifecycle transition) still needs a numeric confidence
for callers that read it immediately — `0` is a lifecycle-agnostic
sentinel, strictly below every status cap in `derive_confidence`'s table,
and `upsert_node` does **not** import `lifecycle.py` to compute the "real"
value — that would invert the Task3→Task4 dependency direction the plan
established. Only `advance_secret_status`/`advance_finding_status` ever
write the actual derived confidence. **Reversibility:** easy, purely a
default-value choice.

## Lifecycle (`lifecycle.py`)

**Strictly linear transitions — no skipping `reachable`/`validated`.**
SPEC.md shows the state machines as linear chains but doesn't explicitly
forbid a shortcut (e.g. `hypothesis -> exploited` directly, if an
automated check somehow proves both reachability and exploitation at
once). This implementation requires every intermediate state to be
visited. **Why:** the whole point of the reachability/validation steps is
that they're each independently checkable preconditions — collapsing them
removes exactly the structure that makes confidence inflation
"structurally impossible" rather than "policy-impossible." **Reversibility:**
moderate — relaxing this later (e.g. allowing a fast-path transition when
a single automated check already proves two conditions at once) is a
transition-table change plus new tests, not a rewrite.

**Confidence table fills two gaps SPEC.md leaves unstated.** SPEC.md pins
`exploited`/`reachable+evidence` (9-10), `validated` (7-8), and
`hypothesis`/`extracted` (<7) explicitly. It says nothing about plain
`reachable` *without* evidence yet, or about `dead`/`discarded`. Filled
as: `reachable` without evidence → 7 (floor of the `validated` bracket —
reachable is a real step up from `validated` even before a PoC exists, but
shouldn't yet claim the 9-10 bracket evidence earns); `dead`/`discarded`
→ 0 (a dead end has no confidence worth reporting). Each status maps to
exactly one fixed value rather than a caller-chosen point within its
bracket, keeping `derive_confidence` a pure, fully-deterministic table.
**Reversibility:** easy to retune the exact numbers later; the *shape*
(derived-from-status, hard-capped) is what's load-bearing.

**`scope_note` is a string reason, not a boolean flag.** SPEC.md rule 4
says an out-of-scope-anchored secret is "recorded but flagged as a note."
Implemented as a human-readable string (`"reachable target(s)
out-of-scope; recorded only, not actionable"`) rather than a boolean,
so a future report-writer (a later brief) has something to show an
operator directly instead of needing a second lookup to explain *why*.
**Reversibility:** easy; `can_anchor_finding` doesn't read `scope_note`
at all (it independently re-derives the same check), so the field is
purely informational and safe to reshape later.

## Query (`query.py`)

**`find_paths` always scope-checks both path endpoints, regardless of
`only_in_scope`.** `only_in_scope` governs whether *intermediate* hops
may leave scope (useful for an operator's own "show me everything, scope
be damned" diagnostic view); the two endpoints of any returned chain are
never allowed to be out-of-scope assets. **Why:** an out-of-scope node
existing in the graph is fine (SPEC.md says so explicitly), but a
differentiator query whose whole purpose is to prove an actionable
cross-domain chain should never hand back a chain anchored on something
that can't legally be acted on — same spirit as the lifecycle's
scope-anchor rule, applied to the read side. **Reversibility:** moderate;
if a future brief wants a true "no filtering at all" diagnostic mode, that's
a new parameter, not a change to this default.

**`nodes(p)`/`rels(p)` returned as raw structs, not list comprehensions.**
Kùzu 0.11.3's binder rejects `[x IN nodes(p) | x.id]`-style comprehensions
in a `RETURN` clause ("Variable x is not in scope"), confirmed by direct
reproduction outside the test suite — `nodes(p)`/`rels(p)` alone work
fine. Worked around by returning the raw structs (each node struct already
carries its own `id` field; each rel struct carries `_label`) and
extracting what's needed in Python after the query returns.
**Reversibility:** trivial — purely a Cypher-syntax workaround with no
behavioral difference; revisit if a later Kùzu version adds the
comprehension syntax.

## Ingestion (`ingest.py`)

**`EdgeUpsert` carries no endpoint types; `apply_upserts` resolves them
by probing every node table.** Kept the dataclass itself minimal
(`label, from_id, to_id, props`) rather than pushing `upsert_edge`'s
5-arg requirement up into the ingestion contract, since a parser
describing "app X leaks secret Y" shouldn't need to also restate each
side's node type when the graph already knows it (the node upserts that
create X and Y are always applied first). `_resolve_node_type` is
O(num_tables) per edge — fine at single-engagement scale, same tradeoff
`query_graph`'s type-less lookup already makes. **Reversibility:** easy;
if this ever matters at scale, `NodeUpsert`/`EdgeUpsert` could carry an
id→type cache instead of re-probing.

## File/module layout

Split as: `manifest.py` + `scope_guard.py` (one trust boundary, two
files since they have genuinely separate responsibilities — signature
verification vs. glob matching); `schema.py` + `graph.py` (DDL vs. the
write API over it); `lifecycle.py` alone (the one module the spec calls
out as "the false-positive killer," deserves to stand alone); `evidence.py`,
`query.py`, `ingest.py` each alone. Per-module READMEs mirror this split
(`README_graph.md` covers both `schema.py` and `graph.py`; `evidence.py`
has no separate README since its own docstring plus `README_ingest.md`'s
coverage of `attach_evidence`'s caller already explain it adequately).
Both `pyproject.toml` (packaging + pytest config) and `requirements.txt`
(flat pin list) exist; `requirements.txt` is what a setup script would
run (`pip install -r requirements.txt`), `pyproject.toml` is what makes
`pip install -e .` and `pytest`'s `pythonpath`/`testpaths` config work
during development. **Reversibility:** trivial either way.

## Test command

**`python3 -m pytest`, not bare `pytest`.** On this VM, the bare `pytest`
CLI resolves to a `uv tool`-installed isolated virtualenv that has none
of this project's dependencies (`kuzu`, `pydantic`, `cryptography`,
`PyYAML`) installed. `python3 -m pytest` uses the system interpreter,
where `pip install -e .`/`pip install -r requirements.txt` actually land.
**Reversibility:** trivial — just the invocation string; documented in
the PR and in this file so it isn't rediscovered the hard way.

---

## Final whole-branch review (two independent passes, both on Opus)

Two fresh reviewer passes (schema/graph/lifecycle/evidence; manifest/
scope/query/ingest/tests) independently confirmed the same root-cause
Critical finding and surfaced several real Important gaps. All
Critical/Important findings were fixed in one pass, each with a test
that failed before the fix and passed after (several verified RED by
reverting the fix momentarily and re-running, not just inferred); two
findings are raised as `FORK`s instead of fixed, since resolving them
properly means changing a contract the escalation rules call out
explicitly. Full test suite: 47 -> 58 (11 new regression/strengthening
tests), all green throughout.

### Fixed

**C1 — `upsert_node`'s `props` loop had no allowlist.** Both passes
independently confirmed a caller could set `in_scope=True` on an
out-of-scope id, `confidence=10` on a `hypothesis` finding, or
`status="reported"` directly — bypassing `scope_guard` and
`lifecycle.py` entirely through the one documented write path (reachable
via `ingest.py`'s `NodeUpsert.props`, i.e. from a future untrusted
parser's output). A second confirmed effect: because the old code wrote
`props` on every `MERGE` (create AND match), re-ingesting the same raw
input reset an already-advanced SECRET/FINDING back to its initial
status/confidence. **Fix:** `schema.py` gained three registries
(`NODE_PROPS_ALWAYS`, `NODE_PROPS_CREATE_ONLY`, `NODE_PROPS_FORBIDDEN`);
`upsert_node` now validates every `props` key against them before
building any Cypher, and splits its `MERGE` into distinct `ON CREATE`/
`ON MATCH` clause sets so `status`/`confidence`/`created_at` are never
rewritten after creation. This also closes the property-*name*
injection vector (an unrecognized key now raises `ValueError` instead of
reaching an f-string). **Reversibility:** this is now load-bearing for
the system's core safety claim; any new node-column needs a registry
entry, not a free-form `props` key.

**C2 (re-graded Critical from the reviewer's "Important") — scope_guard's
CIDR branch didn't recognize "ip:port" targets.** Confirmed: an excluded
`10.0.5.0/24` did not block `10.0.5.10:443` (the colon-suffixed string
fails `ipaddress.ip_address()`, falls through to plain glob matching,
and a separately-present looser in-scope wildcard like `10.0.*` then
matched it). Re-graded to Critical because the escalation contract
explicitly calls for a security lens on `scope_guard`, and SPEC.md's own
dedup convention ("same host:port updates") means ip:port-shaped node
ids are an expected, not exotic, input. **Fix:** `_matches` now also
tries the target with a single trailing `:<port>` suffix stripped before
giving up on the CIDR branch (IPv6 literals, which have more than one
colon, are left untouched). **Reversibility:** easy, isolated to one
helper function.

**Important — three of the five named invariant tests were weaker than
their own names.** `..._expired_or_unsigned_manifest_rejected` never
tested an actually-unsigned manifest (only expired + tampered);
`..._confidence_cannot_exceed_status_cap` only called the pure
`derive_confidence` function directly, so it would have passed even
with C1 present; `..._out_of_scope_secret_cannot_anchor_finding` never
exercised `can_anchor_finding`'s `True` branch at all (`return False`
would have passed every test), and its SECRET had no `scope_key`, so it
was *itself* out of scope — isolating nothing. **Fix:** strengthened all
three (added a truly-unsigned + not-yet-started case; added a
through-the-graph confidence check including a props-injection attempt;
gave the secret an in-scope `scope_key` and added a positive
`can_anchor_finding` case).

**Important — `test_find_paths_only_in_scope_excludes_out_of_scope_hop`
was vacuous.** Both of its seeded endpoints were out of scope under the
default manifest, so it passed via the endpoint-always-checked rule,
not via the `only_in_scope` intermediate-hop filter it claimed to test
— confirmed by temporarily disabling that filter and watching the test
still pass, then it failing once the test was rewritten with in-scope
endpoints and an out-of-scope-only intermediate hop. This also means an
earlier ledger entry (Task 6's ruling) was wrong to claim this test
"holds under the default manifest already" for the right reason.
**Fix:** rewritten with in-scope endpoints; verified by mutation (the
rewritten test does fail when the filter is disabled, confirmed and
reverted).

**Important — `ingest._resolve_node_type` silently picked a table when
an id existed in more than one.** Ids are only unique *within* a table
(a HOST and an API_ENDPOINT can share a hostname); the old code
returned the first match in a fixed table-iteration order, which could
wire an `EdgeUpsert` to the wrong endpoint type with no error.
**Fix:** raises `ValueError` on ambiguity instead.

**Important — a manifest window timestamp with no UTC offset raised a
bare `TypeError`, not `ManifestError`.** A caller catching only
`ManifestError` (this module's whole documented contract) would crash.
**Fix:** a pydantic `field_validator` on `ScopeManifest.window_start`/
`window_end` rejects naive datetimes explicitly, which
`load_and_verify`'s existing `ValidationError` -> `ManifestError`
wrapping already covers.

**Important — `query.py` took `node_type`/filter keys/`find_paths`
endpoint types unvalidated.** Both reviewers confirmed no exploitable
path exists *today* (only internal constants reach these in this
brief), but SPEC.md names this read API as what a future agent will
drive directly. Separately, `find_paths(g, "FINDING", "EVIDENCE")`
crashed with a raw Kùzu binder `RuntimeError` ("Cannot find property
in_scope") since EVIDENCE has no such column. **Fix:** added
`schema.NODE_COLUMNS` (the full read-queryable column set per type,
deliberately separate from the write-oriented `NODE_PROPS_*` registries
— reading `status`/`confidence`/`in_scope` is legitimate, only
*writing* them through `upsert_node` is restricted); `query_graph`
validates `node_type`/filter keys against it, and `find_paths` rejects
`EVIDENCE`/`ENGAGEMENT` endpoints with a clear `ValueError`
(`ENGAGEMENT` never appears in any `EDGE_PAIRS` entry, so it could never
be a real chain participant anyway — letting it through would just
silently return `[]` forever).

**Important — `created_at` wasn't auto-stamped on node creation.**
Contrary to SPEC.md's "every node: id, in_scope, created_at, source."
Closed as a side effect of the C1 fix (created_at now defaults to
`now()` in the `ON CREATE`-only clause) — verified directly, no
additional code needed.

**Important — two READMEs asserted guarantees that didn't hold.**
`README_graph.md` claimed `in_scope` "callers can't pass it at all" and
`README_lifecycle.md` claimed "no generic setter" exists — both were
aspirational at the time, not yet enforced (that's what C1 fixed).
Updated both to describe the actual, now-enforced mechanism, and
`README_lifecycle.md` now explicitly acknowledges `EngagementGraph.execute()`
as the real (if internal-only-by-convention) lower-level primitive
`lifecycle.py` itself uses to write `status`/`confidence`/`scope_note`.

### Declined to fix (not entering the fix pass)

**Minor — evidence not re-verified on read; `_literal` doesn't guard
NaN/Inf; `source` isn't an enforced enum; no transaction around an
`apply_upserts` batch; `find_paths` has no result cap; one test name
doesn't match its body.** Genuinely minor, no safety impact, deferred —
see the PR description's "Deferred minors" list.

### `FORK`s raised (escalation contract items 1 "query-interface contract"
and 3 "security-critical scope-guard tradeoff")

**FORK 1 — the query interface's concrete shapes vs. SPEC.md's
one-liners.** SPEC.md writes `query_graph(filter) -> matching
nodes/edges` and `find_paths(from_filter, to_filter, max_hops) ->
cross-domain chains` without specifying `filter`'s type or whether
`query_graph` can return edges. This brief's plan (reviewed and approved
before implementation) concretized these as `query_graph(graph,
node_type=None, filters: dict|None)` (nodes only) and `find_paths(graph,
from_type, to_type, max_hops, only_in_scope)`. The escalation contract
lists "the query-interface contract" as FORK-worthy, and a reviewer
flagged that this concretization was never explicitly raised as one at
the time — raising it now, retroactively, rather than silently standing
by the plan-time choice.
- OPTIONS: (a) keep the current concrete signatures as-is; (b) widen
  `filter`/`from_filter`/`to_filter` to accept either a bare type-name
  string (current behavior) or a richer predicate (e.g. property
  equality beyond exact-match, so a caller can start `find_paths` from
  a *specific* secret rather than every SECRET); (c) add edge results to
  `query_graph`.
- RECOMMENDATION: (a) for this brief — the next brief that actually
  builds an agent against this interface is better positioned to know
  what shape of `filter` it needs than a guess made now; widening later
  is additive, not breaking, for any caller using today's `node_type=`/
  `filters=` keyword form.
- DEFAULT IF NO ANSWER: keep (a) — already shipped.

**FORK 2 — scope-glob pattern-class ambiguity beyond CIDR/port
normalization.** SPEC.md's scope format lists FQDN, CIDR, URL pattern,
and mobile-bundle-id globs under one untyped list with no tag
distinguishing which kind an entry is. A reviewer confirmed two
concrete collisions beyond the CIDR/port issue already fixed above:
`fnmatch`'s `*` crosses what should be a URL/hostname boundary (a
pattern like `*.acme.example.com` can match a crafted URL path
containing that substring after a scheme/host it was never meant to
authorize), and a mobile-bundle-id glob (`com.acme.*`) can coincidentally
match an unrelated hostname with the same dot-separated shape. Both are
inherent to using one untyped glob mechanism for genuinely different
identifier kinds, which is how SPEC.md itself defines the scope format
— fully resolving it means tagging scope entries by kind (e.g.
`cidr:10.0.0.0/8`, `fqdn:*.example.com`, `bundle:com.acme.*`,
`url:https://...`), which changes the signed manifest's own schema (a
FORK-worthy "schema's core shape" change under the escalation contract,
not a property detail).
- OPTIONS: (a) ship as-is, documented as a known limitation — an
  operator who writes genuinely ambiguous overlapping globs (a loose
  FQDN wildcard that could also parse as a URL-path match, or a bundle-id
  pattern shaped like a possible hostname) accepts that risk, same as
  any glob-based ACL; (b) add typed-prefix scope entries now (schema
  change to the signed manifest format, plus a migration note for any
  already-signed manifest); (c) keep untyped entries but add a stricter
  matcher per declared *context* (i.e. only match an FQDN-style pattern
  against something that parses as a bare hostname, only match a
  URL-style pattern — one containing `://` — against something that
  parses as a URL), without changing the manifest's on-disk format.
- RECOMMENDATION: (c) for a later brief — it closes the actual
  collisions without touching the signed-manifest schema (so no
  migration), by making `scope_guard._matches` dispatch on the
  *target's* apparent shape (bare IP/CIDR, URL, bare hostname/bundle-id)
  the same way it already does for CIDR vs. everything else, just
  extended to URL vs. hostname. Didn't implement this now because it's
  a second, open-ended design pass in its own right, not a bounded bug
  fix like the CIDR/port case.
- DEFAULT IF NO ANSWER: (a) — ship as-is; the CIDR/port fix already
  closes the one bypass confirmed as a genuine exclusion-defeating
  issue (an excluded IP being let back in by an unrelated, separately
  legitimate in-scope wildcard), and the remaining collisions require an
  operator to write genuinely overlapping, ambiguous scope entries in
  the first place.

---

## Human decisions on the two FORKs (architectural review, pre-merge)

**FORK 1 — RESOLVED: option (a), as recommended.** Keep `query_graph`/
`find_paths`'s current concrete signatures (`node_type=None,
filters: dict|None` / `from_type, to_type, max_hops, only_in_scope`).
Explicitly declined to widen `filter` speculatively; a later brief that
actually builds an agent against this interface decides what richer
shape it needs, if any.

**FORK 2 — RESOLVED: option (c) (shape-aware matcher dispatch in
`scope_guard._matches`, no signed-manifest schema change), deferred as
its own follow-up brief rather than folded into this one.** This brief
ships as-is, with the collision documented as a known, accepted
limitation. The follow-up brief implementing (c) is a **hard
prerequisite before KRONOS is used against any live target** — not
optional polish. Tracked as
[Aks2812/KRONOS#2](https://github.com/Aks2812/KRONOS/issues/2) so it
isn't lost between briefs.

---

# Brief #2 (Mobile Static Ingestion)

## Human-authorized Brief #1 schema extension: `MOBILE_COMPONENT.exported`

**This is a schema change, not an autonomous decision.** Brief #2's own
extraction mapping required recording whether a mobile component
(activity/service/receiver/provider) is exported, but Brief #1's locked
schema for `MOBILE_COMPONENT` had no such column, and Brief #1 explicitly
says "you do NOT modify schema.py's node/edge types." Per the escalation
contract this is exactly a FORK (a change to the graph schema), so it was
raised rather than guessed at — see the FORK writeup in the PR description
for the three options considered.

**Resolution (architect's call, lifting the lock for this one change
only):** add `exported BOOLEAN DEFAULT false` to `MOBILE_COMPONENT`.
**Rationale (as given):** exported status is a first-class attack-surface
fact, core to KRONOS's cross-domain chain modeling — it belongs in the
schema itself, not worked around via an encoding hack in `component_type`
or dropped entirely. This is option 1 from the FORK, but done as a
reviewed, deliberate foundation extension rather than a convenience
shortcut.

**Implementation**, exactly as directed:
- `schema.py`: `exported BOOLEAN DEFAULT false` added to the
  `MOBILE_COMPONENT` `CREATE NODE TABLE` DDL.
- `exported` added to `NODE_PROPS_ALWAYS["MOBILE_COMPONENT"]` — registered
  the same way as `component_type`/`name` (a plain descriptive attribute a
  caller CAN set via `props`), **not** the `in_scope`/`status`/`confidence`
  restricted path (those stay caller-forbidden or create-only for their
  own, different reasons).
- `exported` added to `NODE_COLUMNS["MOBILE_COMPONENT"]` so `query.py`'s
  read-side filter validation recognizes it as a legitimate column.
- Schema-level default (`DEFAULT false` in the DDL) covers a node created
  without `exported` in `props` at all — the mobile parser only passes it
  when the manifest states `android:exported="true"` or an intent-filter
  implies it; everything else is non-exported by default, matching "a
  component is non-exported unless the manifest says otherwise."
- New test: `test_mobile_component_exported_flag_round_trips` in
  `test_schema_graph.py` — creates components with `exported=True`,
  `exported=False`, and omitted entirely, asserts all three read back
  correctly (the omitted case defaults to `False`).

**Scope of this authorization:** this is the *only* schema/lifecycle/
contract change authorized for Brief #2. Any other conflict between this
brief's extraction mapping and Brief #1's locked contract is still a FORK
— this entry does not generalize into standing permission to change
anything else in `schema.py`, `graph.py`, or `ingest.py`'s existing
contract shape.

**Reversibility:** easy at the schema level (one nullable-with-default
boolean column; Kùzu's `IF NOT EXISTS` DDL means re-running `init_db` on
an already-initialized engagement DB is still safe) but **not
retroactive** — engagements created before this change have no
`exported` value on existing `MOBILE_COMPONENT` nodes until re-ingested.

## Build-time decisions (below the escalation bar — logged, not asked)

- **`ingest.py` → `ingest/` package.** Adding `kronos.ingest.mobile` as a
  subpackage collided with `kronos/ingest.py` being a plain module (a
  directory and a file of the same name can't coexist). Moved its content
  verbatim into `ingest/__init__.py` — a structural move only; every
  existing `from kronos.ingest import ...` import path is unchanged, and
  Brief #1's ingestion contract itself (`NodeUpsert`/`EdgeUpsert`/`ingest`/
  `apply_upserts`) is untouched.
- **New dependency: `requests==2.32.3`.** Needed for `mobsf_client.py`'s
  REST calls. A plain new pip dependency, not a contract/schema change.
- **`requests` imported at module top level in `mobsf_client.py`, but
  `kronos.ingest.mobile.mobsf_client`'s MobSF-report extraction helpers are
  imported lazily inside `parser.py`'s MobSF branch** — avoids importing
  `requests` at all for callers who never touch the mobile module, and
  keeps `ingest/__init__.py`'s new `mobile_static` dispatch import local to
  avoid a circular import (`mobile/parser.py` imports `NodeUpsert`/
  `EdgeUpsert` from `kronos.ingest`, so a top-level import the other way
  would cycle).
- **MobSF degrades gracefully, never blocks ingestion.** Per SPEC_BRIEF2's
  security lens ("your parser must not crash"), an unreachable MobSF
  (checked via a cheap `is_reachable()` probe before attempting
  upload/scan) or one that errors mid-scan both fall back to light-
  extractor-only results rather than raising — MobSF augments findings, it
  is never a single point of failure for the whole ingestion run.
- **Evidence written through the upsert-list contract, not
  `evidence.attach_evidence`'s direct-graph-write path.** `attach_evidence`
  takes a live graph and writes immediately; this module instead calls
  `evidence.store_evidence` (pure blob-to-disk write, no graph access) and
  appends the resulting `EVIDENCE` `NodeUpsert`/`evidences` `EdgeUpsert`
  to the same list `apply_upserts()` already writes everything else
  through — keeps the whole module's graph-writing on one path.
- **Light extractor obfuscation scope: Base64 only.** Split/concatenated-
  string obfuscation (e.g. `"sk_" + "live_" + "..."` or runtime
  `StringBuilder` assembly) needs real decompiled-code data-flow analysis,
  not a regex pass — explicitly out of scope for this brief per its own
  "DO NOT BUILD" boundaries on parser sophistication. Tracked as a
  follow-up (see `tests/fixtures/README.md`), not silently dropped.
- **Test fixture built from scratch, not from a decoded third-party APK.**
  First attempt reused a sample APK from Kali's `exploitdb-bin-sploits`
  package (GPL-2+) as an `apktool`-decode base to plant artifacts into.
  Switched to building the fixture entirely from an original, hand-written
  `AndroidManifest.xml` + `strings.xml` via `aapt` directly — avoids
  committing any third-party-derived binary into a repo with no stated
  license, and was SPEC_BRIEF2's own first-listed option anyway ("you
  create a tiny deliberately-leaky test APK").

---

# Brief #0.5 (Seeded Cross-Domain Range / CyberGym X-instrument)

## FORK 1 — LocalStack free tier doesn't enforce IAM/S3 access control (RESOLVED)

**Raised because:** the spec requires the cloud tier to have "real
accept/reject behavior" — a wrong key must not unlock a resource. Testing
empirically before writing any lab code: created a real S3 bucket in
LocalStack, then accessed it with totally made-up, unregistered
credentials — it succeeded. Fine-grained per-user S3 authorization is a
LocalStack **Pro** feature; the community tier's IAM calls are
mocked/accepted but never actually checked against resource access. Also
discovered along the way: `localstack/localstack:latest` now requires a
paid Pro license even to **start** basic community services (S3/IAM/STS)
at all — worked around by pinning `:3.0`, the last version confirmed to
start cleanly without a license token (see `cybergym/README.md` "Why
LocalStack is pinned to :3.0").

**Options presented:** (1) pay for LocalStack Pro — not something I can
provide; (2) build a thin SigV4-verification proxy in front of real
LocalStack S3, giving genuine accept/reject while keeping the real S3/IAM
shape; (3) drop the S3/IAM shape entirely, replace the cloud tier with a
custom mock API — loses the realistic shape the spec explicitly wanted.

**Resolution (human, as a "changes what the X-score measures" decision,
not decided silently):** option 2, with two hard requirements: the
signature check must be REAL cryptographic verification (recompute the
expected signature from the known secret, reject on genuine mismatch —
not a presence check), with a dedicated test proving a wrong secret for a
valid access-key-id fails via actual signature mismatch, distinct from a
missing-credentials case; and `ground_truth.yaml`/README must state
explicitly that this is a faithful SigV4 proxy, not a full IAM policy
engine, so the X-score's meaning stays honest.

**Implementation:**
- `cybergym/cloud/sigv4_verify.py` — standalone AWS SigV4 implementation
  (canonical request -> string to sign -> HMAC-chain-derived signing key
  -> signature), reimplemented directly rather than via botocore
  internals, so the verification side has no dependency on the exact
  signing library the client happens to use.
- `cybergym/cloud/known_secrets.py` — the flat access_key_id -> (secret,
  allowed buckets) table; the proxy's only source of truth.
- `cybergym/cloud/sigv4_proxy.py` — the FastAPI reverse proxy: parses
  Authorization, verifies the signature for real, checks bucket
  authorization, forwards authorized requests to real LocalStack
  (unauthorized ones never reach it).
- `cybergym/cloud/test_sigv4_verify.py` — builds REAL boto3-signed
  requests (not hand-crafted headers) and proves: correct secret
  verifies; wrong secret (valid access-key-id) produces a genuine
  signature mismatch; missing/malformed Authorization header is a
  distinct failure mode (fails at parse time, never reaches the
  signature comparison at all).
- Empirically verified end-to-end via `selftest.py`: correct creds
  succeed, wrong secret gets a real `SignatureDoesNotMatch`, and the
  Chain 3 over-privilege boundary is confirmed real (Chain 2's credential
  is denied on Chain 3's bucket, not just "two independent buckets that
  happen to both exist").
- Since the proxy (not LocalStack's own IAM) owns the entire
  authorization decision, `cloud/init_localstack.sh` only creates the two
  buckets — no IAM users/policies are created in LocalStack at all, which
  also sidesteps `create-access-key`'s own limitation (AWS's real IAM API
  always auto-generates random credentials; there's no way to set custom
  ones through it, which would have blocked using fixed, documented
  values as the planted secrets).

## Build-time decisions (below the escalation bar — logged, not asked)

- **Planted secret values deliberately avoid any real vendor's key
  format.** Applied the Brief #2 lesson proactively this time (no
  payment-processor-live-key-shaped or AWS-access-key-shaped strings)
  rather than discovering it via a blocked push. All values are
  `CYBERGYM*`/`cybergym-fixture-*` prefixed and unambiguously
  fixture-shaped.
- **Chain 3's split point:** the combined credential string
  (`access_key_id:secret_access_key`) is split at its exact midpoint
  (`len(full)//2`) across `assets/cfg.dat` (first half) and a string
  resource (second half) — an arbitrary but fixed, documented split
  point; `ground_truth.yaml` states the exact reconstruction method
  (concatenate in that order) so nothing about it is guessable-but-
  undocumented.
- **Manifest window is 100 years (2026-01-01 to 2126-01-01), not a dated
  engagement window.** This is a standing local test lab re-used across
  many future KRONOS runs, not a one-off client engagement — a normal
  Brief #1 dated window would expire and silently break the lab's
  in-scope status. Logged as deliberate, not an oversight.
- **`cybergym/requirements.txt` is separate from KRONOS's own
  `requirements.txt`/`pyproject.toml`**, even though both currently live
  in the same shared `.venv` for local dev convenience — the manifest-
  level separation is what matters (KRONOS's own dependency footprint
  never grows because of this lab's needs), per SPEC_BRIEF05's "clearly
  separated from `src/kronos/`."
- **`cybergym/selftest.py` tears the lab down by default** (`docker
  compose down -v`) after running all checks — matches the spec's
  "leave nothing running or exposed after teardown," with `--no-teardown`
  for manual inspection when that's what's actually wanted.
- **Reused Brief #2's from-scratch `aapt`-based APK-build approach**
  rather than inventing a new one — same reasoning as Brief #2 (no
  third-party base, fully reproducible, no mystery blob), and consistency
  with the established pattern.

## Brief #3: Secret Validation (extracted -> validated -> reachable)

### FORK 1 — resolved: CyberGym enrichment is harness glue, not KRONOS logic

**FORK:** Brief #3 assumes the graph already has complete candidate
targets (full endpoint URLs, `CLOUD_RESOURCE` bucket nodes, reconstructed
split secrets, a cloud-vs-api kind distinction) after mobile ingestion.
Reading the actual code, it doesn't: `light_extractors.py` never reads
`assets/`, never captures a bare path or a bucket-shaped resource name,
never reconstructs a split secret, and tags every secret's `kind` as
`"api_key"`/`"api_key_obfuscated"` regardless of shape.

**OPTIONS presented:**
1. CyberGym-side enrichment script — keep `src/kronos/validate/` fully
   generic (dispatch by decoded-value shape, discover candidates from
   edges any ingester writes), add a small e2e proof script under
   `cybergym/` that completes the graph for this one fixture via the
   same scope-gated `apply_upserts()` path, then hands it to the real
   validator.
2. Extend Brief #2's extractor itself (read `assets/`, broaden regex,
   add shape-based kind classification) — reusable, but touches a
   previously-merged, reviewed brief and risks overfitting its regex to
   this fixture's exact resource-naming scheme.
3. Accept partial coverage and report honestly — build against what
   Brief #2 produces today, unmodified; the e2e run may land under 3/3.

**RESOLUTION (user-selected): Option 1, with a hard guardrail added by
the user before building:** the enrichment step may ONLY add target
nodes/edges and reconstruct secrets per `ground_truth.yaml`'s
documented method. It may NEVER pre-set, hint, or shortcut a secret
toward `validated`/`reachable` — every secret it writes is created at
`status="extracted"`, exactly what any ingester's initial value always
is, and the real validation pass (`kronos.validate.run_validation_pass`,
the exact same generic function any other engagement would use) is what
actually advances it. `cybergym/kronos_validation_run.py`'s
`_assert_enrichment_did_not_shortcut_anyone` enforces this mechanically,
not just by convention — it checks every enrichment-created secret is
still `"extracted"` right after enrichment and before the validation
call runs, so a future regression here fails loudly instead of quietly
producing a lying X-score.

**Two additional, independently-discovered Brief #2 gaps, same
resolution applied without re-asking (same class of allowance, found
empirically running the real e2e proof, not anticipated in the
original FORK):**
- `kronos_chain2_creds_enc`'s resource name contains `"creds"`, not
  `"credential"` — `light_extractors._SECRET_NAME_RE` doesn't match the
  abbreviation, so chain 2's secret was never captured as a `SECRET`
  node at all (Brief #2 ingestion silently missed it, not a crash).
  Enrichment decodes it the same documented way (base64) ground_truth
  already specifies.
- `scope_manifest.yaml`'s `"localhost*"`/`"127.0.0.1*"` globs never
  match an `API_ENDPOINT` node id, which is always a full URL with
  scheme (`"http://localhost:8091"`) — `fnmatch` has no substring
  matching, only a literal-prefix match. Without `"http://localhost*"`/
  `"http://127.0.0.1*"` added to the manifest (re-signed with the
  existing key, re-verified via `kronos.manifest.load_and_verify`),
  chain 1's every candidate was *correctly* scope-gated out by a
  manifest that simply never declared its own API tier's URL scheme in
  scope — not a `scope_guard` bug.

### Build-time decisions (below the escalation bar — logged, not asked)

- **Validator dispatch is keyed by decoded secret-VALUE shape, never by
  the stored `SECRET.kind` column.** Brief #2 never distinguishes a
  cloud-credential pair from a bearer token in `kind`
  (`classify_validator_kind` in `src/kronos/validate/registry.py`): a
  `left:right` split where the left side is >=8 chars and the right is
  >=6 chars classifies as `"cloud_credential_pair"`; anything else
  non-empty is `"api_token"`; empty is `"unknown"` (no validator, stays
  `extracted`, never guessed live).
- **`find_candidate_targets_for_secret` returns EVERY `CLOUD_RESOURCE`
  node in the engagement, unfiltered by any edge** — there is no
  schema-legal edge type connecting a mobile app/secret to a cloud
  resource before it's proven live (`authenticates_to` is the
  validator's own OUTPUT, not a valid input here), and trying every
  known cloud resource is exactly what proves a credential's real
  (possibly over-broad) privilege — CyberGym's chain 3 authenticating to
  two buckets is the proof this design exists to make possible, not an
  accident of a looser filter.
- **The runner must filter candidates to the target TYPE the dispatched
  validator expects before calling it** — caught running the real e2e
  proof: an `api_token`-classified secret was being attempted against
  `CLOUD_RESOURCE` candidates too (since candidate discovery returns
  both kinds for every secret) and crashed on the wrong calling
  convention. Fixed in `runner.py`; regression test added
  (`test_api_token_secret_never_dispatched_to_the_cloud_validator_even_with_cloud_candidates`).
- **`registry.get_validator` does a late (call-time) attribute lookup
  on each validator module rather than binding a dict of function
  references once at import time** — purely so tests can
  `@patch("kronos.validate.http_validator.validate_api_token")` /
  `cloud_validator.validate_cloud_credential` directly and have the
  runner actually observe the patch; no behavioral difference otherwise.
- **`http_hints` (per-endpoint `{"method":..., "header_name":...}`
  overrides) is a plain parameter on `run_validation_pass`, not
  anything stored on the graph.** CyberGym's chain 1 needs a
  non-standard header (`X-Cybergym-Key`) and `POST`, which
  `API_ENDPOINT`'s locked schema has no column for; the caller (the
  CyberGym e2e script, which knows this from the fixture's own
  documentation) supplies it explicitly, same category of
  "operator-supplied recon knowledge" as knowing which header a real
  target expects from reading its client integration code.
- **The HTTP validator's default (no explicit `header_name`) tries
  `Authorization: Bearer <value>` then `X-Api-Key: <value>`, first 2xx
  wins** — a small, bounded, documented set of conventional
  credential-transmission methods, not an open-ended guess; any
  transport error counts as not-live, never a crash.
- **`run_validation_pass` snapshots every `"extracted"` SECRET once at
  pass start**, not re-queried per candidate — a secret that reaches
  `reachable` partway through the loop still has its *remaining*
  candidates tried, which is what lets chain 3 prove authenticating to
  BOTH buckets in one pass rather than stopping at the first success.
- **Added `boto3==1.43.111` to root `requirements.txt`/`pyproject.toml`**
  — it's now a real `src/kronos/validate/cloud_validator.py` dependency,
  not just `cybergym/`'s own (it was already in the shared `.venv` from
  Brief #0.5's cybergym-only install, but the KRONOS package's own
  declared dependencies hadn't caught up).

## Brief #4 (Reconciliation / Dedup Pass)

New module `src/kronos/reconcile/` (`canonical.py`, `merge.py`,
`runner.py`), wired into `cybergym/kronos_validation_run.py` at both
pipeline slots SPEC_BRIEF4 §2 specifies: `ingest -> reconcile -> enrich ->
reconcile -> _assert_enrichment_did_not_shortcut_anyone -> validate`.

### Schema touch: `merged_into` (not a FORK — a necessary consequence of FORK-A's own DEFAULT)

**This is a schema change, flagged explicitly per SPEC_BRIEF4's own
instruction to call out any schema touch.** FORK-A (§5) was pre-resolved
to its DEFAULT — tombstone losers, never hard-delete — but implementing
that DEFAULT requires *somewhere* to record "this node was merged into
that one," and `schema.py` had no such column on any node type before
this brief. `SECRET`/`FINDING` already had a `status` column (so
`status="merged"` was at least expressible, just not wired to anything);
`HOST`, `API_ENDPOINT`, `MOBILE_APP` — the other three node types
SPEC_BRIEF4 §3.1 names as mergeable — have **no** `status` column at all.
Without adding something, FORK-A's chosen DEFAULT is simply not buildable
for 3 of the 5 mergeable types.

**Resolution (treated as a necessary consequence of the already-resolved
FORK-A, not a new fork to escalate):** added `merged_into STRING`
(nullable, no default needed — Kùzu nullable columns default to `NULL`)
to exactly the five mergeable node types: `HOST`, `API_ENDPOINT`,
`MOBILE_APP`, `SECRET`, `FINDING`. Minimal and uniform: `merged_into
IS NOT NULL` is the one tombstone predicate every mergeable type shares,
queryable via `query.query_graph` (SPEC_BRIEF4 §4 test 7). `SECRET`/
`FINDING` additionally get `status="merged"` on tombstone, matching
FORK-A's literal wording for the two types that already had a `status`
column to set; `HOST`/`API_ENDPOINT`/`MOBILE_APP` do **not** gain a new
`status` column (that would be a larger, unnecessary surface change) —
`merged_into` alone is their tombstone signal.

**Why this isn't itself escalated as a third fork:** SPEC_BRIEF4 already
pre-resolved FORK-A with an explicit DEFAULT the brief says to take if
unattended; this column is the only way to actually build that DEFAULT,
not a new, independent design choice. Same class of precedent as Brief
#2's `exported` column — a locked-schema addition, scoped, documented,
and the *only* schema change this brief makes to any already-existing
node type.

`merged_into` is registered in `schema.NODE_PROPS_FORBIDDEN` (global, like
`in_scope`/`confidence`) — no ingester/caller can ever set it via
`upsert_node`; only `kronos.reconcile.merge`'s tombstone write touches it.
**Reversibility:** easy; nullable column additions are backward
compatible, same caveat as Brief #2's `exported` column — not
retroactive to an already-initialized engagement DB's existing rows
(`init_db`'s `CREATE ... IF NOT EXISTS` is a no-op against an
already-created table).

**`resolves_to` needed no schema touch at all.** It was already in
`EDGE_PAIRS` (`HOST->HOST`, `API_ENDPOINT->HOST`, `WEB_ENDPOINT->HOST`)
from Brief #1. SPEC_BRIEF4 §3.3 explicitly allows skipping the edge
assertion itself ("if in doubt, skip the edge for now and note it — the
merge discipline is what matters here") — taken here, and noted:
no ingester in this codebase produces DNS-resolution evidence (an
FQDN actually resolving to a given IP) today, so there is nothing to
honestly assert the edge FROM. SPEC_BRIEF4 §4 test 3 ("not merged;
`resolves_to` asserted (or skipped-and-noted)") is satisfied by the
"not merged, both nodes still present" half; the edge itself is the
skipped half, by the brief's own stated allowance.

### FORK-B — resolved exactly per the brief's own DEFAULT

Option 1: `lifecycle.py` gained `recompute_status_from_evidence` (pure —
no graph parameter at all) and `set_secret_status_from_evidence` (the
actual write, called only by `kronos.reconcile.merge`, after it has
already carried every loser's edges — including `evidences` — onto the
survivor). The second function is necessary because `SECRET.status` can
only ever change through `lifecycle.py` by this module's own documented
contract ("the ONLY place `SECRET.status`... change[s] after a node's
initial creation") — reconciliation cannot write it via a bare Cypher
`SET` from `merge.py` without breaking that contract. It is explicitly
**not** a forward mutator: it never consults `SECRET_TRANSITIONS`, and
may legitimately move status *backward* (an evidenceless `reachable`
label collapsing to `extracted` on merge) — which `advance_secret_status`
would reject outright. `advance_secret_status` remains the *only*
function that advances a SECRET forward, and remains called only by
`kronos.validate.runner` (verified by a grep-assert test, §4 test 8:
`test_advance_secret_status_still_called_only_by_the_validation_runner`;
reconciliation never calling it is covered by a second, dedicated test).
The small scope-note computation `advance_secret_status` already had was
extracted into a shared private helper (`_scope_note_if_reachable`) so
both functions derive it identically — a pure refactor, zero behavior
change, verified by the full existing `test_lifecycle.py`/
`test_validate_runner.py` suite staying green throughout.

### FORK-A — resolved exactly per the brief's own DEFAULT

Tombstone, never hard-delete (see the schema-touch writeup above for
what building this DEFAULT actually required).

### Guardrail 1 — `scope_guard.py` zero-line diff

Confirmed by `git diff --stat` throughout this brief's work, and pinned
by a test (`test_scope_guard_has_zero_line_diff`) against a `sha256sum`
of the file captured before any of this brief's edits began. FORK-2
(Aks2812/KRONOS#2) stays open, untouched, exactly as instructed.

### FINDING canonical key: implemented, currently always inert

`canonical.canonical_key_for_finding(finding_class, affected_asset_id,
location_sig)` is fully implemented per SPEC_BRIEF4 §3.1's exact formula
and wired into `runner.py`'s grouping pass — but `FINDING`'s locked
schema has no `location_sig` column and no ingester in this codebase
populates one, so `location_sig` is always `None` in practice today and
the function always returns `None` for every FINDING currently in any
graph. This is the guardrail-6-safe default ("a node that can't produce
a confident key... is never merged"), not a bug, and not a reason to
leave the function unwritten — wiring it in now means a future ingester
that adds real location data gets correct FINDING dedup for free.

### CyberGym live confirmation

Ran the real, live, docker-backed `cybergym/kronos_validation_run.py`
end to end with reconciliation wired into both pipeline slots: **X-score
3/3**, unchanged from the pre-reconciliation baseline. Both reconciliation
passes (`post_ingest`, `post_enrich`) reported **0 duplicates** — this
specific fixture's ingestion + enrichment never produces two different
node IDs for the same real entity today (chain 2/3's enrichment-
reconstructed secrets have no ingestion-side twin, since Brief #2's
light extractor never captured them at all — see the existing Brief #3
FORK writeup), so this run demonstrates reconciliation is a safe,
behavior-preserving no-op on CyberGym's current fixture. Every merge
*scenario* the brief requires (dedup, template-merge, cross-shape
non-merge, idempotency, the three laundering cases, audit) is instead
exercised directly and deterministically in `tests/test_reconcile.py`,
which does not depend on live docker services.

### Build-time decisions (below the escalation bar — logged, not asked)

- **Survivor selection: lexicographic `min()` of the group's member
  ids.** SPEC_BRIEF4 §3.2 asks for "lowest/oldest ID, so merges are
  reproducible" without specifying a total order; plain string `min()`
  is deterministic, needs no extra data (no second `created_at` lookup),
  and is reproducible regardless of insertion order — exactly what the
  brief asks for, nothing more.
- **Edge carry-over walks `schema.EDGE_PAIRS` directly** (one typed
  Cypher query per `(label, from_type, to_type)` the merging node type
  participates in, either end) rather than a single untyped `MATCH
  (a)-[r]->(b)` over the loser — keeps every carried-over edge write
  going through the exact same `graph.upsert_edge(label, from_id,
  from_type, to_id, to_type)` 5-argument contract every other module
  uses (`graph.py`'s own documented contract, per its README), and reuses
  its existing `MERGE`-based de-dup rather than inventing a second one.
- **`run_reconciliation_pass` takes `engagement_dir`** (like
  `run_validation_pass` already does) purely to decode SECRET evidence
  blobs for canonical-key material — `value_ref` never carries the raw
  secret inline on the node (Brief #2's own design), so computing
  `canonical_key_for_secret` needs the same evidence-store read
  `validate.runner._decode_secret_value` already does. Duplicated as a
  small private helper rather than imported, for the same reason
  `validate.runner`'s version is private: it's a 6-line, module-local
  decode-with-graceful-degradation helper, not a shared contract.
- **`_group_findings` is wired in but currently always empty** (see the
  FINDING canonical key writeup above) — kept rather than omitted so
  wiring a future `location_sig` source doesn't need a second brief
  touching `runner.py`.
- **`kronos_validation_run.py`'s chain-id lookups now resolve through
  `_survivor_of` (follows `merged_into`) before the final chain checks.**
  Without this, a chain's secret ID could get tombstoned by the
  post-enrich reconcile pass (merged into a differently-IDed survivor),
  and the existing `_check_chain(graph, ..., secret_id, ...)` calls — which
  look the node up by its ORIGINAL id — would see a `"merged"` tombstone
  instead of the real `"reachable"` status. Not exercised on this
  fixture today (0 duplicates found, see above) but necessary for
  correctness the moment a second mobile-ingestion source starts
  overlapping with enrichment's reconstructed secrets, which is exactly
  the scenario this brief exists to make safe.

## Brief #4.1 (Reconciliation fixes — amends PR #6, pre-merge)

Review of Brief #4 found the dedup mechanics were only half-wired: the
live CyberGym 3/3 was a no-op proof (that fixture has no real
duplicates, so `merge_group` never actually ran), and two latent defects
would have activated the moment a genuine duplicate appeared. Both are
closed here, additive on the same branch/PR — nothing from Brief #4 is
reverted.

### Fix #1 — tombstoned losers are now genuinely inert (FORK-C)

**Problem:** `_carry_over_edges` *copied* a loser's edges onto the
survivor but never removed them. The loser stayed fully live in the
graph with all its original edges — `find_paths` and any non-SECRET
candidate enumeration would still traverse straight through it. A real
duplicate was being added as a superset survivor, not removed.

**FORK-C — resolved exactly per the brief's own DEFAULT: option 1,
move-don't-copy.** Confirmed empirically before committing to this path
(per the brief's own instruction to verify Kùzu can delete relationships
by pattern before taking the DEFAULT): `MATCH (a)-[r:label]->(b) DELETE r`
removes the matched relationship without touching either node — tested
directly against this exact Kùzu build. `merge.py` gained
`_delete_loser_edges`, called after `_carry_over_edges` (and, for
SECRET, after `set_secret_status_from_evidence` — deleting the loser's
edges afterward doesn't change what the survivor already carries, but
the brief pins this order regardless) and before `_tombstone`. Same
`EDGE_PAIRS` walk as the carry-over, both directions, localized entirely
to `merge.py` — no `merged_into` filter was added to `find_paths`,
candidate enumeration, or anywhere else, which is the point: every
current and future reader is protected without needing its own
filtering discipline.

**Ordering detail not spelled out in the brief but required for
correctness:** carry-over for ALL losers in a group happens before
deletion for ANY of them (two separate loops, not interleaved
per-loser). A 3+-way merge can have an edge between two losers; carrying
every loser's edges over first — even if that transiently creates a
spurious survivor<->loser edge along the way — guarantees every real
external edge reaches the survivor exactly once, and the deletion pass
afterward cleans up anything left dangling on any loser regardless of
processing order. Interleaving carry-over and deletion per loser would
make the result order-dependent.

### Fix #2 — FINDING merge path refuses rather than half-activates

**Problem:** `merge_group` collected `carried_statuses` for FINDING but
never recomputed a survivor status from evidence (only SECRET did,
`carried_statuses` was dead data for FINDING). Unreachable today only
because `canonical_key_for_finding` always returns `None` — but
`canonical.py` is deliberately pre-wired to switch on "for free" the
moment a future ingester populates `location_sig`, at which point a real
FINDING merge would silently keep the arbitrary min-id survivor's status
unrecomputed: a false-negative (a real `exploited` finding quietly
downgraded) that nobody would be looking at `merge.py` to catch.

**Fix:** `merge_group` now raises `NotImplementedError` immediately for
any FINDING group of size >=2, naming SPEC_BRIEF4.1 §3 in the message.
The dead `carried_statuses` collection for FINDING was removed (the
condition narrowed from `node_type in _STATUS_BEARING_TYPES` to
`node_type == "SECRET"`); SECRET's collection is unchanged.
`canonical_key_for_finding` and `runner._group_findings` are left in
place exactly as instructed — they correctly yield nothing today, and
are the backstop's trigger for the day they don't. Full FINDING
reconciliation (its own `exploited`->`reported` evidence-gating rules,
which differ from SECRET's) belongs in whichever later brief actually
produces FINDING nodes.

### The missing test — turning the no-op proof into a real one

`tests/test_reconcile.py` gained three tests (13 -> 16 in this file; 107
passed project-wide, 1 pre-existing skip, 0 failed):

- **SECRET, real duplicate:** two distinct-id secrets, same material,
  each with its own edges (one evidence-backed + an `authenticates_to` a
  cloud resource, one only `leaks`-linked from an app). Proves: the
  survivor holds the union of both; the loser has **zero** relationships
  post-merge (the actual Fix #1 proof, via a helper that walks every
  `EDGE_PAIRS` label/pair the node type can participate in — not just
  the couple of edges the test happens to set up); `find_paths` returns
  the survivor only, never the loser; the survivor's status is
  `recompute_status_from_evidence` of the merged evidence; and a second
  pass on this now-non-empty, already-tombstoned graph is still a true
  no-op.
- **API_ENDPOINT, real duplicate:** `/users/123` and `/users/456` merge
  on their shared template, `/admin/1` stays separate; the loser is
  edgeless; `find_paths(HOST, API_ENDPOINT)` returns the survivor and
  the genuinely-distinct third endpoint, never the loser.
- **FINDING guard:** calls `merge_group` directly with a 2-member
  FINDING group (bypassing the always-`None` canonical-key runner path)
  and asserts it raises `NotImplementedError` — proves Fix #2's backstop
  actually fires, not just that it's unreachable today.

All 13 of Brief #4's original tests stayed green throughout, unmodified.

### Live CyberGym re-confirmation

Re-ran the full live, docker-backed `cybergym/kronos_validation_run.py`
after both fixes: **X-score still 3/3**, both reconciliation passes
still report 0 duplicates (unchanged — this fixture still has no genuine
duplicate, exactly as Brief #4's run found). The fixes change nothing
about this fixture's outcome by design; what they change is proven by
the new unit/graph tests above, which inject real duplicates
deliberately.

### Unchanged (confirmed, not re-litigated)

`scope_guard.py` zero-line diff (re-confirmed via the existing sha256
test, unchanged from Brief #4); `advance_secret_status` still the only
forward mutator, called only by the validation runner (existing
grep-assert tests, unmodified, still pass); the SECRET
evidence-recompute rule; the conservative canonical keys; the
`merged_into`-forbidden-in-upsert lock; the post-enrichment
`_survivor_of`-based re-assertion of `_assert_enrichment_did_not_shortcut_anyone`.
None of this was touched.

## Brief #5 — Per-engagement budget governance

New module `src/kronos/budget/`: `limits.py` (the frozen `BudgetLimits`
dataclass and the conservative `DEFAULT_BUDGET_LIMITS`), `config.py`
(`load_budget_limits(engagement_dir)`, reading `budget.yaml`),
`ledger.py` (`BudgetLedger` — the chokepoint — plus `BudgetExceeded`,
`BudgetSnapshot`, `write_ledger_snapshot`, `stopped_early_marker`).
Wired into `kronos.validate.runner.run_validation_pass` (a new optional
`budget: BudgetLedger | None` kwarg; omitted, it builds its own ledger
from `DEFAULT_BUDGET_LIMITS` rather than running unmetered) and into
`cybergym/kronos_validation_run.py` (one ledger per run, a generous
`budget.yaml` written into the engagement dir, `check_wall_clock()`
calls between pipeline phases, a `BudgetExceeded` catch around the
whole pipeline for a clean, non-crash wind-down).

### Guardrail confirmation

- **`scope_guard.py`: zero-line diff** — re-confirmed via `git diff
  --stat` (empty) and the existing sha256-pinned test (now duplicated,
  deliberately, as `test_budget.py::test_scope_guard_still_has_zero_line_diff`,
  per SPEC_BRIEF5 §4 test 8's explicit ask to re-verify this brief by
  brief, not just trust an earlier pin). FORK-2 (#2) stays untouched.
- **`advance_secret_status` remains the only forward mutator, called
  only by the validation runner** — unchanged; `test_reconcile.py`'s
  whole-tree grep test now also covers `src/kronos/budget/` for free
  (it walks the entire `src/kronos` tree), and
  `test_budget.py::test_budget_module_never_calls_advance_secret_status`
  adds a budget-scoped version of the same proof. Budget enforcement
  charges at exactly one point in `validate/runner.py` — immediately
  before the validator call, strictly before `_advance_through`/
  `attach_evidence`/the `authenticates_to` edge write — so it wraps
  *around* validation and never reaches into guardrail 2's territory.
- **Fail-closed, never fail-open** — `BudgetLedger.charge` checks the
  ceiling BEFORE recording anything; a charge that would cross it
  raises `BudgetExceeded` and the action it would have paid for is
  never started. Nothing in `kronos.validate` or `kronos.budget`
  catches `BudgetExceeded` internally — every raise propagates to the
  one orchestrator-level catch site (`cybergym/kronos_validation_run.py`
  has it; a future CLI entry point gets its own), which is where
  "stopped early" wind-down actually happens.
- **Deterministic only** — no LLM, no heuristic, in `charge`/
  `check_wall_clock`. `test_budget.py`'s determinism test runs the same
  graph shape through the same budget twice and asserts the identical
  stop point and entry log (clock-based readings aside, same caveat as
  timestamps).
- **Single chokepoint** — `BudgetLedger.charge` is the only API any
  caller spends through; no second counting mechanism exists anywhere
  in the codebase.

### FORKs — both taken as their pre-resolved DEFAULT

- **FORK-D (where budget limits live): DEFAULT taken — a separate
  `budget.yaml`** in the engagement dir, outside the signed Ed25519
  manifest. `config.py`'s loader fills any dimension a *valid* file
  omits from `DEFAULT_BUDGET_LIMITS` rather than leaving it `None` — a
  run is never unlimited by accident just because an operator's file
  didn't mention every dimension; only an explicit `null` produces a
  genuinely unlimited dimension.
- **FORK-E (behavior at the moment a ceiling is crossed): DEFAULT
  taken — finish the in-flight atomic action, then stop before the
  next.** No special code was needed to build this: every caller
  charges strictly BEFORE performing its action, and every action
  KRONOS runs today completes synchronously before the next one's
  charge is even attempted, so an action whose own charge raises was
  simply never started, and any action that already passed its charge
  runs to its normal completion. The charge-before-start calling
  convention makes the DEFAULT fall out for free — see
  `src/kronos/budget/README.md`'s "Why FORK-E's DEFAULT needs no
  special code" section for the full reasoning.

### Test results

**125 passed, 1 skipped** (pre-existing, unrelated: MobSF not
configured), **0 failed**. 18 new tests in `tests/test_budget.py`
covering every §4 acceptance test: fail-closed enforcement stopping
exactly at a tiny `validation_attempts` cap with the over-cap attempt
proven never to have run; never-fails-open with a pre-exhausted budget;
determinism across two independent identically-built runs; a
deterministic-fake-clock wall-clock cap test (no real `sleep`, no
flakiness); six config-fallback tests (missing file, invalid YAML,
non-mapping YAML, unknown dimension, non-numeric value, negative value,
a valid-but-partial file, and an explicit `null`); a mocked
ingest-reconcile-validate pipeline proving a generous budget is a pure
passthrough with real, non-zero, below-ceiling consumption; an
audit-trail test proving the snapshot file is written, parseable, and
only ever grows; and the two guardrail tests above. All 107 pre-existing
tests stayed green, unmodified.

### Live CyberGym confirmation

Stood up the real, live, docker-backed range and ran
`cybergym/kronos_validation_run.py` end to end with a generous
`budget.yaml` (`validation_attempts: 100`, `tool_invocations: 100`,
`wall_clock_seconds: 900`, `llm_tokens: 0`, `llm_cost_usd: 0`) written
into the engagement dir before the pipeline starts — exercising
FORK-D's real file-loading path live, not just the in-memory default:

```
X-SCORE: 3/3 chains validated end-to-end
BUDGET: config_source=file
  validation_attempts: 10.0 / 100
  tool_invocations: 10.0 / 100
  wall_clock_seconds: 5.424388996999937 / 900
  llm_tokens: 0 / 0
  llm_cost_usd: 0 / 0
```

**X-score: 3/3, unchanged from the pre-budget baseline.** Every
dimension's consumption is comfortably below its ceiling — this run
demonstrates the budget is a safe no-op at generous limits, exactly as
SPEC_BRIEF5 §4 test 6 asks; the acceptance tests that actually trip the
ceiling (tests 1, 2, 4) are the dedicated, deterministic unit tests in
`tests/test_budget.py`, which need no live docker. `llm_tokens`/
`llm_cost_usd` both read `0/0` — nothing charges either dimension yet,
confirming they exist and are chargeable (proven directly in
`test_budget.py`'s API-level tests) without ever being spent by
anything in this codebase today.

### Unchanged (confirmed, not re-litigated)

Everything from Brief #4/#4.1's reconciliation pass — tombstoning,
move-don't-copy edge deletion, the FINDING guard, the SECRET
evidence-recompute rule — is untouched; this brief only adds a new,
optional `budget` parameter to `run_validation_pass` and a new,
unrelated module. No schema touch was needed or made — budget state
lives entirely in `budget.yaml`/the in-memory ledger/the JSON snapshot
file, never in the Kùzu graph itself.

## Brief #6 — Engagement cleanup / teardown registry

New module `src/kronos/cleanup/`: `registry.py` (`CleanupRegistry` —
the chokepoint, `TeardownItem`/`TeardownReport`, `write_teardown_report`)
and `kinds.py` (idempotent teardown-callable factories: `remove_container`
/`remove_network`/`remove_volume` via raw `docker rm -f`/`network rm`/
`volume rm` tolerating "no such object"; `compose_down` wrapping an
existing `compose(*args)` helper as one teardown callable for a whole
range stack; `remove_file`/`remove_dir`; `shred_credential_file`
(overwrite-then-unlink — removed from disk, not just logged);
`terminate_process`, pre-wired for the agent layer). Wired into
`cybergym/kronos_validation_run.py`, replacing the old ad-hoc
`finally: compose("down", "-v")` with a single `CleanupRegistry`
entered before the range comes up and wrapping the whole pipeline; the
resulting `TeardownReport` is written to the engagement dir alongside
the budget ledger snapshot.

### Guardrail confirmation

- **`scope_guard.py`: zero-line diff** — re-confirmed via `git diff
  --stat` (empty) and `test_cleanup.py::test_scope_guard_still_has_zero_line_diff`
  (the same sha256 pin re-verified by this brief, per its own §4 test 8).
  FORK-2 (#2) stays untouched.
- **`advance_secret_status` remains the only forward mutator** — this
  brief's module never calls it; `test_cleanup.py::test_cleanup_module_never_calls_advance_secret_status`
  greps the whole `src/kronos/cleanup/` tree for the call, mirroring the
  budget brief's own guardrail test. `src/kronos/lifecycle.py` and
  `src/kronos/reconcile/` have a zero-line diff from main.
- **Teardown is mechanically budget-exempt (guardrail 3 / FORK-F's
  DEFAULT)** — `test_cleanup.py::test_cleanup_module_is_budget_exempt_mechanically`
  walks every file under `src/kronos/cleanup/` and asserts none of them
  has a real `import kronos.budget`/`from kronos.budget` line or a
  `.charge(...)` call. `src/kronos/budget/` itself has a zero-line diff
  from main — this brief only reads `BudgetExceeded` in its own test
  file to prove teardown survives it, never inside the cleanup module.
- **The key cross-module test:**
  `test_cleanup.py::test_teardown_runs_even_when_budget_is_exhausted`
  registers artifacts, charges a zero-ceiling `BudgetLedger` inside a
  `with CleanupRegistry() as registry:` body (raising `BudgetExceeded`
  mid-body), and asserts every registered artifact was torn down in LIFO
  order and the `TeardownReport` written — before the exception is even
  caught. The `CleanupRegistry` context manager has no knowledge of
  `BudgetExceeded` at all; it just treats it as "the body raised,"
  which is exactly what makes this guardrail mechanically true rather
  than merely a policy.

### FORKs — both taken as their pre-resolved DEFAULT

- **FORK-F (does teardown charge the budget?): DEFAULT taken — exempt.**
  Nothing in `kronos.cleanup` imports `kronos.budget` or can raise/catch
  `BudgetExceeded`; cleanup cannot depend on spare budget to run.
- **FORK-G (crash-safety mechanism): DEFAULT taken — a context manager
  owned by the orchestrator**, not `atexit`/signal handlers.
  `CleanupRegistry.__exit__` always calls `teardown_all()` — on a clean
  return, on `BudgetExceeded`, or on any other exception — then lets the
  original exception (if any) propagate unchanged. Deterministic and
  directly testable without needing to kill the interpreter.

### Test results

**140 passed, 1 skipped** (pre-existing, unrelated: MobSF not
configured), **0 failed**. 15 new tests in `tests/test_cleanup.py`
covering every §4 acceptance test: LIFO teardown order; teardown on an
exception with the exception still propagating; teardown surviving a
real `BudgetExceeded` (the key cross-module test, see above);
idempotence (`teardown_all()` called twice, an already-gone artifact
reported `already_gone`, not `failed`); a partial-failure test (one
callable raises, the other two still run, the failure is recorded, and
`teardown_all()` itself never raises); a temp credential file genuinely
removed from disk (plus its already-missing-file variant); the
`docker`-kind teardown-callable unit tests (`remove_container`
success/failure/already-gone, `compose_down` wrapping); a
`TeardownReport` JSON round-trip; and the three guardrail tests above.
All 125 pre-existing tests (18 of them Brief #5's) stayed green,
unmodified.

### Live CyberGym confirmation

Stood up the real, live, docker-backed range via the now-registry-based
`cybergym/kronos_validation_run.py` and ran it end to end (happy path):

```
X-SCORE: 3/3 chains validated end-to-end
BUDGET: config_source=file
  validation_attempts: 10.0 / 100
  tool_invocations: 10.0 / 100
  wall_clock_seconds: 5.790974900999913 / 900
  llm_tokens: 0 / 0
  llm_cost_usd: 0 / 0
TEARDOWN: all clear
  [ok] docker 'docker compose down -v (CyberGym range)' -> done
```

Exit code `0`. `docker ps -a`, `docker network ls`, and `docker volume
ls` immediately after the run show zero leftover KRONOS/CyberGym
containers, networks, or volumes — only Docker's own built-in
`bridge`/`host`/`none` networks remain.

Also forced an early stop against the SAME live range (a temporary
`validation_attempts: 0` ceiling, applied only for this confirmation
run, never committed) to exercise guardrail 3 for real, not just in the
unit test:

```
BUDGET EXCEEDED: budget exceeded: validation_attempts would reach 1.0 > ceiling 0
  stopped early: budget validation_attempts exhausted
X-SCORE: incomplete — run stopped early by budget enforcement, not evaluated
TEARDOWN: all clear
  [ok] docker 'docker compose down -v (CyberGym range)' -> done
```

Exit code `3` (the existing `BudgetExceeded` wind-down code from Brief
#5 — unchanged). Teardown ran in full even though the engagement's
budget was fully exhausted mid-run against still-live containers; a
post-run check again showed zero leftover containers, networks, or
volumes. The `TeardownReport.to_dict()` shape, matching both runs'
single docker-stack item:

```json
{
  "all_ok": true,
  "items": [
    {
      "detail": "docker compose down -v (CyberGym range)",
      "error": null,
      "kind": "docker",
      "outcome": "done",
      "timestamp": "2026-10-12T05:52:42.201065+00:00"
    }
  ]
}
```

### Unchanged (confirmed, not re-litigated)

Brief #5's budget governance — the ledger, the config loader, the
`validate/runner.py` charge points — is untouched; this brief adds no
new `budget` parameter and no new charge call anywhere. The old
ad-hoc `finally: compose("down", "-v")` in
`cybergym/kronos_validation_run.py` is gone — there is exactly one
teardown path left in that script now, the `CleanupRegistry`.

## Brief #7 — CyberGym denial fidelity

Fixture-only brief: the real `cybergym/cloud/sigv4_proxy.py`, driven across
six arms, was found to flatten all four denial conditions to identical
`403 AccessDenied`, differing only in free-text `Message`. Real AWS S3
returns distinct `Error.Code` values for these conditions, so a validator
tuned against the flattened behaviour would not transfer to a real
target — and fixing `src/kronos/validate/` first would have baked in
prose-matching against fixture text. This brief fixes only the range,
emitting the AWS-faithful codes real S3 returns, before the next brief
(the negative-control validator) is written against it.

### Implemented matrix (compare against SPEC_BRIEF7 §3.1 line by line)

| Condition | HTTP | S3 `Error.Code` |
|---|---|---|
| No `Authorization` header at all | 403 | `AccessDenied` |
| `Authorization` header present but unparseable (case M1 only, §3.1a) | 400 | `AuthorizationHeaderMalformed` |
| Well-formed header, unknown access key | 403 | `InvalidAccessKeyId` |
| Known access key, signature mismatch | 403 | `SignatureDoesNotMatch` |
| Valid signature, bucket not in `allowed_buckets` | 403 | `AccessDenied` |
| Authorized | upstream status | — (forwarded, unchanged) |

`cybergym/cloud/sigv4_proxy.py`: the `Authorization` header is now checked
in three stages before any lookup — absent (403 `AccessDenied`), case-M1
malformed (400 `AuthorizationHeaderMalformed`, via the new
`sigv4_verify.is_case_m1_malformed`), then the existing
`parse_authorization_header`/`MalformedAuthHeader` path for every other
malformed shape (unchanged). Unknown access key now reports
`InvalidAccessKeyId`; signature mismatch now reports
`SignatureDoesNotMatch`. Bucket-not-allowed and the forwarded success path
are byte-for-byte unchanged.

### The deliberate ambiguity (not a bug)

`no_auth` and `bucket_not_allowed` both yield `(403, AccessDenied)`. This
is faithful to real AWS — anonymous access to a private resource looks
identical to a valid-but-unauthorized credential — and is harmless because
a validator always knows which arm it sent. Documented in
`cybergym/README.md` "Denial matrix" so a later reader does not "fix" it.

### Case M1 scope (§3.1a) — not a general rule

`is_case_m1_malformed` matches only the one specified shape: the
`AWS4-HMAC-SHA256` algorithm token and a `Credential=` component present,
`SignedHeaders=`/`Signature=` absent. No test asserts or implies a general
"any unparseable header is 400" rule; every other malformed shape (a
different auth scheme entirely, other partial shapes) falls through to
the pre-existing `MalformedAuthHeader` handling, unchanged from before
this brief — nothing else needed changing, so nothing else was touched.

### FORK-H — DEFAULT taken: AWS-faithful codes only, no custom header

No `x-cybergym-deny-reason` (or any other fixture-only discriminator)
header was added. Rationale (unchanged from the brief): the whole point
is that the signal the next brief's validator reads must transfer to a
real target; a lab-only header would be the lazy path that passes this
benchmark and fails in production. The anti-leak guard test exists and
passes regardless:
`cybergym/cloud/test_denial_matrix.py::test_src_kronos_never_references_the_fixture_only_discriminator_header`
walks every file under `src/kronos/` and asserts none contains the string
`x-cybergym-deny-reason` (case-insensitive).

### Guardrail confirmation

- **`src/kronos/` zero-line diff** — confirmed via `git diff --stat main
  -- src/kronos/` (empty) at every point during this brief. Only files
  inside SPEC_BRIEF7 §2's allowlist changed:
  `cybergym/cloud/sigv4_proxy.py`, `cybergym/cloud/sigv4_verify.py`,
  `cybergym/ground_truth.yaml`, `cybergym/selftest.py`, the new
  `cybergym/cloud/test_denial_matrix.py`, `cybergym/README.md`, and this
  file. `cybergym/cloud/sigv4_verify.py` was touched only because
  distinguishing case M1 from every other malformed shape needed new
  parsing-domain logic (`is_case_m1_malformed`) — exactly the "only if
  splitting absent from malformed requires it" allowance in §2.
- **`known_secrets.py` unchanged** — zero-line diff; same keys, same
  secrets, same `allowed_buckets`. Only the representation of a denial
  changed.
- **Authorized-path behaviour unchanged** —
  `test_row_authorized_request_is_forwarded_unchanged` proves a signed,
  authorized request still reaches the (stubbed) upstream and returns its
  status/body untouched.
- **No test asserts on `Message` text** — every denial-matrix assertion,
  hermetic and live, compares only `(HTTP status, Error.Code)`.
- **No new runtime dependencies, egress, or exposed ports** —
  `cybergym/requirements.txt` and `docker-compose.yml` are untouched;
  `is_case_m1_malformed` is pure-Python regex matching on data already in
  hand.

### Ground truth / self-test consistency (§3.3)

`cybergym/ground_truth.yaml` gains a `cloud_denial_matrix` list (one entry
per §3.1 row, `id`/`condition`/`http_status`/`error_code`).
`cybergym/selftest.py`'s new `check_cloud_denial_matrix()` loads that list
and exercises the **real running proxy** against every row — two raw
`requests` calls for the header-shape rows (absent, case-M1), three
`boto3` calls (asserting the structured `ClientError.response["Error"]["Code"]`
and `ResponseMetadata["HTTPStatusCode"]`, not a string-matched exception)
for the credential/bucket rows — so the declared matrix and the proxy's
actual behaviour cannot drift apart silently, the same discipline
`known_secrets.py` already gets against `ground_truth.yaml`. The
pre-existing chain-2 wrong-secret check was updated to assert
`SignatureDoesNotMatch` (previously asserted the now-obsolete flattened
`AccessDenied` substring); the chain-3 boundary check (bucket-not-allowed)
needed no change since that row's code is unchanged.

### Test results

**Hermetic (`cybergym/cloud/`): 16 passed** — the 4 pre-existing
`test_sigv4_verify.py` tests (unmodified, still green: no regression on
well-formed-header parsing or the existing malformed/wrong-secret
distinctions) plus 12 new in `cybergym/cloud/test_denial_matrix.py`: one
parsing-regression test, one absent-vs-malformed-now-diverge test, six
one-per-row matrix tests (asserting `(HTTP status, Error.Code)` only),
three parametrized determinism tests (same arm repeated twice yields the
same pair), and the anti-leak guard test. All run via FastAPI's
`TestClient` against the real `sigv4_proxy.app` with the upstream
`requests.request` call stubbed (§3.4) — no Docker, no network.

**KRONOS's own suite (`tests/`, scoped by `pyproject.toml`'s
`testpaths`): unchanged at 140 passed, 1 skipped, 0 failed** — expected,
since `src/kronos/` has a zero-line diff.

### Live docker-backed run — BLOCKED / INCOMPLETE

The live run and X-score 3/3 criterion is **unverified**. `docker compose
up -d --build` (invoked by both `cybergym/selftest.py` and
`cybergym/kronos_validation_run.py`) fails during the `sigv4-proxy` and
`init-buckets` image builds:

```
RUN pip install --no-cache-dir -r /app/requirements.txt
...
WARNING: Retrying ... after connection broken by 'SSLError(SSLCertVerificationError(1,
  '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate
  in certificate chain (_ssl.c:1010)'))': /simple/fastapi/
...
Could not fetch URL https://pypi.org/simple/fastapi/: ...
ERROR: Could not find a version that satisfies the requirement fastapi==0.143.0
ERROR: process "/bin/sh -c pip install --no-cache-dir -r /app/requirements.txt" did not
  complete successfully: exit code: 1
target sigv4-proxy: failed to solve: process "/bin/sh -c pip install --no-cache-dir
  -r /app/requirements.txt" did not complete successfully: exit code: 1
```

**Blocker:** this build environment's outbound HTTPS is intercepted by a
policy-enforcing egress proxy whose CA is trusted on the host (host-level
`pip install -r cybergym/requirements.txt` succeeds — confirmed) but is
**not** trusted inside the Docker build's network namespace, so `pip`
inside the `sigv4-proxy`/`init-buckets` build steps gets a self-signed
certificate it cannot verify and every PyPI fetch fails. Confirmed this is
not an invocation-flag problem: `docker build --network host` and
`DOCKER_BUILDKIT=0` (legacy builder) were both tried as read-only
diagnostics (no file changes) against `cloud/Dockerfile` directly and hit
the identical SSL error. The documented fix (`/root/.ccr/README.md`,
"docker build / docker run") is to copy the proxy's CA bundle into the
build context and install it in an early image layer — which requires
editing `cybergym/cloud/Dockerfile` / `cybergym/cloud/init.Dockerfile` /
`cybergym/api/Dockerfile`, none of which are in SPEC_BRIEF7 §2's
allowlist. Per the brief's own instruction, this is reported as
**BLOCKED / INCOMPLETE** rather than substituting the hermetic result or
relaxing the criterion. Diagnostic commands run, for the record:

```
docker compose up -d --build                      # the real command; fails as above
docker build --network host -f cloud/Dockerfile .  # diagnostic only, same SSL error
DOCKER_BUILDKIT=0 docker build --network host \
  -f cloud/Dockerfile .                            # diagnostic only, same SSL error
```

All diagnostic images/containers were removed afterward;
`docker ps -a` / `docker network ls` / `docker volume ls` show nothing
left behind beyond Docker's own built-in `bridge`/`host`/`none` networks.
**The X-score and the live denial-matrix-against-the-running-range
criterion (§4/§5.5) are therefore unverified by this PR.** The hermetic
tests above do not and cannot stand in for them. The PR is left open and
marked incomplete pending either a build-environment fix outside this
brief's scope, or an explicit go-ahead to widen scope to the Dockerfiles
(which would itself need to go back through the FORK process, since §2
does not list them).

### Unchanged (confirmed, not re-litigated)

Brief #6's `CleanupRegistry`/`TeardownReport` machinery is untouched —
this brief adds no cleanup-registered resource and no new teardown path;
the one `docker compose down -v` registration in
`kronos_validation_run.py` is exactly as Brief #6 left it. Brief #5's
budget governance is likewise untouched.

## Brief #8 — Negative-control validation (two-armed proof)

### Why

Brief #3's validators each trusted a SINGLE arm: `http_validator.py`
treated the first `2xx` as proof; `cloud_validator.py` collapsed every
`ClientError` to `live=False`. Hole 1 is real and reproducible against
this exact range: CyberGym's `GET /health` returns `200 {"status": "ok"}`
with no auth required, so pointing the old validator at it with a
garbage secret reported the secret live. Hole 2 meant the validator could
never turn Brief #7's AWS-faithful `AccessDenied` into the positive
evidence it actually is (a signed request that gets `AccessDenied` proves
the signature verified). Both validators now run a differential — the
real secret plus one or two derived, guaranteed-invalid negative
controls — and hand it to `kronos.validate.controls.run_differential`,
the one chokepoint that decides whether the target actually
discriminates before any claim is trusted.

### Classification matrix as implemented, next to Brief #7's declared matrix

Brief #7 declared five S3 denial codes for a *single* signed request.
Brief #8 reads those same codes across THREE arms (A canonical, B
bad-secret, C unknown-key) and classifies the differential:

| Brief #7 single-arm code (for reference) | Brief #8 three-arm pattern (A / B / C) | `classification` implemented |
|---|---|---|
| (A succeeds) | A success / B denied / C denied | `live_discriminated` (`live=True`) |
| `AccessDenied` (no-auth or bucket-not-allowed) | A `AccessDenied` / B `SignatureDoesNotMatch` / C `InvalidAccessKeyId` | `authenticated_not_authorized` (FORK-M: `validated` only, no edge) |
| `AccessDenied` | A `AccessDenied` / B `AccessDenied` (identical) | `inconclusive` (target doesn't discriminate between real/fake signature) |
| (any code, A also succeeds) | A success / B **also** success | `indiscriminate_target` (the `/health` case) |
| `AuthorizationHeaderMalformed` (§3.1a, case M1) | **any** arm returns it | `self_request_malformed` (our own request, never a target signal) |
| `InvalidAccessKeyId` / `SignatureDoesNotMatch` (A itself) | A denied, none of the above patterns match | `not_live` |

HTTP's two-arm table collapses to the same four non-cloud-specific rows:
`live_discriminated`, `indiscriminate_target`, `not_live`,
`inconclusive` (both arms transport-error) — there is no
`authenticated_not_authorized`/`self_request_malformed` concept on the
HTTP side, since there is no S3-style structured error code to read.

Implemented exactly in `kronos.validate.controls.run_differential` — see
`src/kronos/validate/controls.py`.

### FORK choices (all DEFAULT; no escalation needed)

- **FORK-I (where the arm logic lives):** DEFAULT (1) — one shared
  `controls.py`. Same reasoning as `scope_guard`: a classification rule
  duplicated per validator is a rule that rots per validator.
- **FORK-J (budget metering of arms):** DEFAULT (1) — charge all arms up
  front, differential atomic. `runner.py` charges `validation_attempts`
  (still 1/candidate) and `tool_invocations` (now the arm count) together,
  before the validator call that runs the whole differential — so a
  `BudgetExceeded` can only land *between* candidates, never mid-arm-set
  (`tests/test_negative_controls.py::test_budget_exceeded_between_candidates_never_mid_differential`
  proves this with a ledger sized for exactly one candidate's 3 arms).
- **FORK-K (control arm also succeeds):** DEFAULT (1) — abstain:
  `live=False`, `classification="indiscriminate_target"`, secret stays
  `extracted`, no FINDING. The secret is not disproven; the target is
  uninformative.
- **FORK-L (control derivation):** DEFAULT (1) — HMAC-derived,
  shape-preserving, fixed `KRONOS-NEGATIVE-CONTROL` domain-separation
  label. `derive_negative_control` forces every digit/upper/lower
  character position to differ from the original (not just "probably,
  by hash"), so it is structurally, not just probabilistically,
  guaranteed never to equal the real value for any realistic secret
  shape; a defensive `RuntimeError` fail-closed guard covers the
  degenerate case of a value with no digit/letter characters at all.
- **FORK-M (cloud `authenticated_not_authorized`):** DEFAULT (1) —
  advance to `validated`, no edge, not `reachable` via that candidate.
  Discarding this signal would be a false negative on exactly the
  over-privilege evidence Brief #7 §0 named.

### Guardrail confirmation

- `src/kronos/scope_guard.py`: zero-line diff (confirmed via
  `git diff --stat main -- src/kronos/scope_guard.py`, empty).
- `src/kronos/lifecycle.py`: untouched (not in this PR's diff at all).
  `advance_secret_status` remains the only forward status mutator,
  called only from `runner.py`'s existing `_advance_through` and the new
  `_advance_to_validated_only` — both call it, neither reimplements it.
- No `FINDING` nodes created anywhere in this brief's code.
- No secret value in any evidence blob, log line, or `detail` string —
  `ArmResult` structurally carries only labels/success/status/error-code,
  never a credential value; `tests/test_negative_controls.py`'s
  `test_cloud_validator_evidence_and_control_outcome_never_contain_a_secret_value`
  and each validator test file's assertions check this directly.
- `known_secrets.py` / `scope_guard.py` authorization semantics
  unchanged; no new dependency, no new egress target, no new exposed
  port — this brief is pure Python logic plus one new live `selftest.py`
  check against ports the range already exposes.

### §5.1.8 — NOT implemented: allowlist conflict (stop-and-report)

SPEC_BRIEF8.md §5.1.8 explicitly instructs: "(a) add `assert scanned > 0`
non-vacuity to the anti-leak guard in `cybergym/cloud/test_denial_matrix.py`;
(b) add a negative test that a non-M1 malformed Authorization header does
not return 400." But the SAME brief's §2 "Must NOT change" list includes
`cybergym/cloud/*`, which covers that exact file, and §2 says: "If you
believe one is required, stop and report." This is a direct contradiction
within the brief, not a judgment call — §5.1.8 names the file to edit,
§2 forbids editing it. Per the brief's own binding instruction ("stay
inside the §2 allowlist... stop and report instead of changing it"), this
sub-item was **not implemented**. Everything else in §5.1/§5.2/§5.3 was
implemented and is green. This needs the brief author/reviewer to resolve
(either §2 should carve out an explicit exception for this one file, or
§5.1.8 should move its target to a file Brief #8 may touch) before it can
land.

### Test results

**`tests/` (KRONOS's own suite): 306 passed, 1 skipped** (baseline before
this brief: 140 passed, 1 skipped). The net growth is the new
`tests/test_negative_controls.py` (header/cloud classification-matrix
parametrizations sweep every combination in `controls.ArmResult`'s space,
not just one case per §5.1.3) plus additive fixes to existing call sites
that construct `ValidationOutcome(live=True, ...)` directly
(`tests/test_http_validator.py`, `tests/test_cloud_validator.py`,
`tests/test_validate_runner.py`, and — made necessary by the new
structural invariant in `types.py`, not by anything specific to
validation — `tests/test_budget.py` and `tests/test_reconcile.py`, which
each had one such construction in a budget/reconciliation scenario that
happens to use the validate module).

**`cybergym/cloud/` (hermetic, Brief #7): unchanged at 16 passed** — this
brief does not touch `cybergym/cloud/*` (see §5.1.8 above).

### Live, Docker-backed run (§5.3) — BLOCKED / INCOMPLETE

Same environment blocker as Brief #7, reproduced independently rather
than assumed: `docker compose up -d --build` fails inside the
`sigv4-proxy`/`init-buckets`/`api` image builds with
`SSLCertVerificationError: self-signed certificate in certificate chain`
against PyPI — this cloud container's egress proxy CA is trusted on the
host but not inside the Docker build's network namespace. The fix
(installing the CA bundle into an image layer) requires editing
Dockerfiles, which are explicitly out of §2's allowlist for this brief
too.

The §5.3 checks (`check_negative_control_differential` in
`cybergym/selftest.py`, wired into `main()` right after
`check_cloud_denial_matrix`) are **written and ready to run** on a host
with unproxied egress (per the brief's own explicit instruction: "Still
WRITE the §5.3 selftest.py check so it can be run on the local host"),
but have not themselves been executed against the live range from this
container. **X-score and the live negative-control-differential
criterion are therefore unverified by this PR.** The hermetic suite
above does not and cannot stand in for them.

### One-line cost statement

Validation now costs **2× `tool_invocations` per HTTP candidate, 3× per
cloud candidate** (`validation_attempts` is unchanged at 1 per
candidate) — `_ARM_COUNT_BY_KIND` in `src/kronos/validate/runner.py`.

## Brief #9 — Ingestion contract, canonical keys, owned event stream (S2)

### Schema prerequisite done first, per FORK-P's DEFAULT

Added `merged_into STRING` to `WEB_ENDPOINT`, `PARAMETER`, `SERVICE` and
their `NODE_COLUMNS` entries — nothing else. `NODE_PROPS_FORBIDDEN`
already forbade `merged_into` globally (Brief #4), so the column stays
reconcile-only without any further change. Without this, the three new
canonical-key functions would be completely inert (Brief #4's exact
defect, knowingly avoidable here).

### Two entry points for the mobile ingester, not one

SPEC_BRIEF9 §3 asks for a conforming source to return an `IngestPlan`.
Changing `ingest_mobile_static`'s own return type to that would break
`cybergym/kronos_validation_run.py`'s `ingest(APK_PATH, "mobile_static",
graph)` -> `apply_upserts(graph, upserts)` call, expecting a bare
`list[NodeUpsert | EdgeUpsert]` — and `cybergym/` is explicitly out of
this brief's §2 allowlist. Resolution: one shared extraction core
(`_ingest_mobile_static_core`, logic byte-for-byte unchanged from Brief
#2 except for declined-tracking/event-emission plumbing), two thin
public faces — `ingest_mobile_static` (legacy bare-list, used by
`ingest()`/cybergym, untouched signature and return shape) and
`ingest_mobile_static_plan` (the new `IngestionSource`-conforming
entry point). This is the brief's own anticipated shape of "stop and
report rather than restructure" applied narrowly: the *external*
contract for the one caller outside the allowlist doesn't change; the
*internal* plumbing is adapted, not rewritten, and both faces share one
implementation so there is nothing to keep in sync.

`apply_plan` (in `contract.py`) and `apply_upserts` (in `__init__.py`,
pre-existing) are jointly the sole graph-writing chokepoint under
`ingest/` for the same reason — `apply_plan` delegates to
`apply_upserts` rather than duplicating its write logic, so there is
still exactly one place `upsert_node`/`upsert_edge` are called from,
just reached via two names (the guard in `test_ingest_contract.py`
exempts `__init__.py` specifically, documenting why).

### `host_key`/`parent_key` are raw ids, not re-derived canonical keys

§4.2/§4.3 describe `PARAMETER`/`SERVICE`'s compound keys as embedding
"the parent endpoint's own canonical key" / "the host's own canonical
key." Implemented literally, this makes §5's ordering rule
**unenforceable and untestable**: `canonical_key_for_host`,
`canonical_key_for_web_endpoint`, and `canonical_key_for_api_endpoint`
are all pure functions of a node's own text (id, or method+url) —
nothing about computing them depends on whether a merge has run. Two
genuine parent-level duplicates always produce the identical canonical
key regardless of merge order, by construction (that's literally the
criterion that made them duplicates). Using those functions here would
mean the reverse merge order can never actually produce a wrong answer
to test against.

Resolution (not one of FORK-N/O/P/Q/R, a narrower in-flight call,
logged here per the Balanced autonomy contract): `runner.py`'s
`_group_services`/`_group_parameters` pass the parent's RAW node id
(whichever `HOST`/`WEB_ENDPOINT`/`API_ENDPOINT` the current edge names)
into the compound key functions, not a freshly recomputed canonical
key. This only converges to one shared value across two SERVICE/
PARAMETER duplicates' parent edges once the parent-type merge has
actually run and re-pointed those edges onto the survivor — making the
ordering rule genuinely load-bearing, and
`test_service_merge_requires_host_merged_first_fails_under_reverse_order`
an honest proof rather than a vacuous one (verified by temporarily
reverting to the canonical-key design and confirming that test's
"reverse order fails" assertion itself fails against it — i.e. the
vacuous design merges correctly regardless of order, so a test that
only ever observes correct behavior would not have caught the defect
class §5 exists to prevent).

### `reconcile_skipped_uncertain_key` scope

Emitted once per active node (of any mergeable type) whose canonical
key resolves to `None` — not per merge-group, and not throttled or
sampled. This can be verbose on a graph with many non-duplicate nodes
(most nodes never have a duplicate at all), but SPEC_BRIEF9 §8 test 9
only requires the event exist with the right fields and never carry
secret/raw-output material, not that it be sparse; a future brief can
add filtering if the volume becomes an operational problem.

### FORK choices taken (all DEFAULT, per the brief's own resolution)

- **FORK-N** (DEFAULT: no path templating for `WEB_ENDPOINT`) — taken
  as specified; `canonical_key_for_web_endpoint` never templates a
  path segment.
- **FORK-O** (DEFAULT: `None` parent/host propagates to `None` child
  key) — taken as specified for both `PARAMETER` and `SERVICE`.
- **FORK-P** (DEFAULT: schema addition done in this brief, first) —
  taken; see "Schema prerequisite" above.
- **FORK-Q** (DEFAULT: append-only JSONL file, not a Kùzu table) —
  taken; `src/kronos/events.py`'s `emit(stream, kind, **fields)`.
- **FORK-R** (DEFAULT: wire the new types into the reconcile runner now,
  with real-duplicate tests required) — taken; see
  `tests/test_reconcile.py`'s `WEB_ENDPOINT`/`PARAMETER`/`SERVICE`
  real-duplicate tests.

## Brief #10 (FORK-2) — shape-aware `scope_guard` matcher

### Why

`src/kronos/scope_guard.py` used one untyped `fnmatch` mechanism for
genuinely different identifier kinds (FQDN, CIDR, URL, `host:port`,
mobile bundle id) drawn from one flat pattern list with no tag saying
which kind an entry is. This measurably **under-matched exclusions**
(F1: excluded `10.0.0.5/32` did not deny `https://10.0.0.5/admin`; F2:
same for a bare-IP exclusion; F3: same for an IPv6 CIDR exclusion
against a bracketed `[addr]:port` target) and **over-matched allows**
(F4: `*acme.com*` authorized `https://evil.net/?next=acme.com/x`; F5:
`com.acme.*` authorized `com.acme.evil.attacker.net`) — and separately
produced **false denials** that then caused the over-matching, because
an operator who cannot get a legitimate subdomain or standard-port
endpoint into scope reaches for a looser glob to make the engagement
run at all (F6/F6b/F6c/F7′/F7″: `*.acme.com` denied
`https://api.acme.com/v1/users`, the `http` equivalent, the
explicit-443 form, and the bare `host:443`/`host:80` forms — all of
which §1.1 says must be allowed; F8: an explicit `api.acme.com:8443`
entry did not cover its own URL form).

### §1.1 — scope intent (operator-ratified, governing; verbatim)

> `*.acme.com` authorizes DNS **subdomains** of `acme.com`, but **not
> the apex** `acme.com`. Equivalent URL forms on those matching hosts
> inherit scope for **HTTP/HTTPS on their standard ports**, regardless
> of path or query. **Nonstandard ports require explicit scope
> entries.** A redirect or URL parameter naming a different hostname
> does **not** inherit authorization, and **exclusions win across
> every equivalent representation.**
>
> 1. Subdomain, not apex. `*.acme.com` matches `api.acme.com` and
>    `a.b.acme.com` (any depth), and does not match `acme.com`. An
>    operator wanting the apex adds it as its own entry.
> 2. Standard ports are 80 for `http` and 443 for `https`. A hostname
>    entry authorizes the bare host, the host with a standard port
>    (`host:80`, `host:443`), and `http`/`https` URLs on those ports —
>    whether the port is implicit or written out.
> 3. Path and query are irrelevant to authorization. Once the host is
>    authorized, any path or query on it is in scope. Scope is
>    host-level, not path-level.
> 4. Nonstandard ports need an explicit entry. `*.acme.com` does not
>    authorize `api.acme.com:8443` or `https://api.acme.com:8443/x`.
>    An entry naming the port (`api.acme.com:8443`) authorizes both the
>    bare `host:port` and its URL forms (F8).
> 5. No authorization transfer via URL content. A hostname appearing in
>    a path, query, fragment or redirect target never authorizes
>    anything. Only the URL's host component is consulted.
> 6. Allow is narrow; deny is broad. This asymmetry is deliberate and
>    must not be "harmonized": an allow entry for a host covers
>    standard ports only, while an exclusion for a host excludes it on
>    every port, scheme, path and representation. When in doubt, deny.
> 7. A CIDR or bare-IP entry authorizes ALL ports on a matching address
>    — operator-ratified, 2026-10-16, resolving §8.5. `10.0.5.0/24`
>    authorizes `10.0.5.10`, `10.0.5.10:443`, `10.0.5.10:8443`,
>    `10.0.5.10:22` and `https://10.0.5.10/x` alike. Rationale: an IP
>    range in a signed SOW expresses network-level authorization — the
>    host itself, not merely its web tier — whereas a hostname entry
>    expresses web-tier intent and keeps rule 4's standard-port limit.
>    Allow semantics therefore differ by pattern shape, deliberately.
>    An address-shaped entry is port-blind; a hostname-shaped entry is
>    port-limited. Do not unify these. Rule 6 is unaffected: exclusions
>    remain port-blind for every shape.

Implemented exactly as specified, in `scope_guard.py` and documented
in `src/kronos/README_scope.md`. Confirmed with a dedicated test
(`test_5_5b_cross_shape_asymmetry_pinned_in_one_call`) pinning both
halves of the asymmetry — `10.0.5.10:8443` ALLOW next to
`api.acme.com:8443` DENY — in the same `is_in_scope` call, so a later
"cleanup" that unifies address- and hostname-shaped allow semantics
breaks a named test, not just a row in a matrix nobody re-reads.

### FORK-S — what a URL target may authorize from

**DEFAULT (1) taken:** only the URL's host component and effective
port are consulted; path, query, fragment, and userinfo never
authorize. This is F4's actual fix and the general principle behind
every §5.6 row: a pattern that is not itself URL-shaped (no `"://"`)
is evaluated only against the target's host identity when the target
is a URL, never against the raw URL string. The one carve-out is a
URL-*shaped* pattern (the operator wrote `"://"` themselves, e.g. the
pre-existing `test_url_pattern_glob` lock, or CyberGym's own
`http://localhost*` covering its nonstandard port) — that pattern
still matches the full raw target string, because the operator opted
into literal path-aware matching explicitly. This does not reopen F4:
F4's pattern (`*acme.com*`) is not URL-shaped, so it never gets that
carve-out.

### FORK-T — bundle id vs. hostname disambiguation

**DEFAULT (1) taken, resolved on the *pattern* side, not the target
side** — see §8.2 below for why target-side classification was
rejected outright rather than approximated. A trailing-`.*` pattern
(one literal wildcard, at the end, no leading `*.`) may only have its
wildcard consume a single further label (no embedded dot). This closes
F5 (`com.acme.*` must not authorize `com.acme.evil.attacker.net`)
while leaving the existing `com.acme.mobileapp` match (and the new
`com.acme.mobile` lock) intact, and only engages when the target is
bare (`host`-shaped) — never reached for the pre-existing, unrelated
`"10.0.*"` glob tested against an `ip_port` target in
`test_cidr_excluded_still_blocks_ip_port_target`, which keeps its old,
unrestricted raw-string match.

### §8 — open uncertainties, answered with evidence

**§8.1 — `scope_key` call sites.** Enumerated every `scope_key` value
and every bare `id` fallback actually reaching `is_in_scope`
(`graph.py:140`, `scope_key or id`) across `src/kronos/` and
`cybergym/`:

- Bundle ids (`com.kronos.demo`, `com.kronos.cybergym.lab`, test
  fixtures like `com.acme.app`) — `host`-shaped, §4's taxonomy covers
  these (folded into `host`; see §8.2).
- Full URLs (`API_ENDPOINT` ids / `CHAIN1_FULL_URL`) — `url`-shaped,
  covered.
- Bare hostnames (`api.acme.example.com`) — `host`-shaped, covered.
- **ARNs** (`arn:aws:s3:::{bucket}`, from
  `cybergym/kronos_validation_run.py`'s enrichment step, matched
  against `cybergym/scope_manifest.yaml`'s
  `arn:aws:s3:::kronos-cybergym-*` pattern) — **a shape §4's taxonomy
  does not name.** Per the binding instruction, this is reported
  rather than silently extended: `classify_target` does **not** grow
  an `"arn"` member. An ARN has no netloc (`urlsplit` parses it as
  `scheme="arn", netloc=""`), is not an IP, and is not
  colon-single-port-shaped, so it falls into the `host` catch-all by
  elimination — exactly where it already lived before this brief. Its
  matching is unchanged: `_matches_generic_pattern` still does a plain
  case-insensitive `fnmatch` of the pattern against the raw target
  string, which is what let it match before and is confirmed still
  matching now (`cybergym/cloud/` stays at 17 passed; the live-run
  script's CLOUD_RESOURCE scoping is unaffected).
- Bare test-fixture ids with no real-world shape (`s1`, `h1`, `cr:x`)
  — never match any real pattern in production manifests; `host`
  catch-all, harmless.

No shape was found that needed escalation beyond "fold it into `host`
and change nothing about how it already matched."

**§8.2 — bundle id vs. hostname is not cleanly decidable.** Confirmed,
not assumed: CyberGym's own real bundle id
(`com.kronos.cybergym.lab`) contains nothing — no underscore, no
unusual character — that a cheap, dependency-free syntactic check could
use to rule out "this could be a hostname." **The honest answer is
that it cannot be decided safely from the target string alone**, and
this brief does not try — `classify_target` never returns `bundle_id`.
The required `com.acme.*` behavior (§5.7) is achieved entirely on the
pattern side instead (FORK-T above), which is decidable and does not
risk ever authorizing a hostname by guesswork.

**§8.4 — IPv6 forms.** All three named forms were probed directly, not
assumed:
- **Zone indices** (`fe80::1%eth0`): `ipaddress.ip_address` already
  accepts these natively (Python 3.9+); no special handling was
  needed and `test_8_4_zone_index_does_not_bypass_exclusion` confirms
  a zoned target is still caught by a plain exclusion on the
  zone-free form.
- **IPv4-mapped** (`::ffff:10.0.0.5`): confirmed this is a **real,
  silent F1-class bypass risk** if left alone —
  `ipaddress.ip_address('::ffff:10.0.0.5') in ipaddress.ip_network('10.0.0.0/24')`
  is `False` (different `ipaddress` types; the `in` operator does not
  raise, it just silently returns `False`). Closed by
  `_address_in_network`'s explicit `.ipv4_mapped` normalization, tried
  in both directions; `test_8_4_ipv4_mapped_exclusion_is_not_a_bypass`
  pins it.
- **Compressed vs. expanded** (`2001:db8::1` vs.
  `2001:0db8:...:0001`): not a bypass risk at all, because every
  comparison in this module goes through `ipaddress.ip_address()`
  first and compares the resulting objects, never the input strings —
  the two literal forms produce an identical object.
  `test_8_4_compressed_vs_expanded_ipv6_are_equivalent` pins it.

**§8.5 — RESOLVED, not reopened.** Implemented as §1.1 rule 7 exactly
(CIDR/bare-IP allow is port-blind); see the §5.5b matrix and the
cross-shape pinning test above.

**§8.6 — URL userinfo / host-confusion forms.** Probed directly:
`urlsplit('https://api.acme.com@evil.net/x').hostname == 'evil.net'`
(and `.username == 'api.acme.com'`) — confirmed. This is exactly what
a real HTTP client connects to (the host following the last
unescaped `@` in the authority, never the userinfo before it), so
`urlsplit().hostname` agrees with reality here; no parser/client
disagreement was found for any of the §5.6 userinfo rows.
`test_5_6_no_transfer_via_userinfo_host_confusion_form` pins it.

### F1–F8 — RED before / GREEN after (TDD, as the brief requires)

A dedicated probe file reproduced every named finding against the
**unmodified** `scope_guard.py` first; all eleven assertions (F1, F2,
F3, F4, F5, F6, F6b, F6c, F7′, F7″, F8) failed for the expected reason
(wrong boolean, not an error) before a single line of the matcher was
touched. After the rewrite, the same eleven passed; they were then
folded verbatim into `tests/test_scope_guard.py`'s permanent §5
matrix (the scratch probe file was deleted once its job — proving the
RED state — was done; the transcript lives here instead):

| Finding | RED (before) | GREEN (after) |
|---|---|---|
| F1 (CIDR/32 exclusion vs. URL) | FAIL — `True`, expected `False` | PASS |
| F2 (bare-IP exclusion vs. URL) | FAIL — `True`, expected `False` | PASS |
| F3 (IPv6 CIDR exclusion vs. bracket:port) | FAIL — `True`, expected `False` | PASS |
| F4 (`*acme.com*` via query string) | FAIL — `True`, expected `False` | PASS |
| F5 (`com.acme.*` via multi-label suffix) | FAIL — `True`, expected `False` | PASS |
| F6 (https subdomain, implicit standard port) | FAIL — `False`, expected `True` | PASS |
| F6b (http subdomain, implicit standard port) | FAIL — `False`, expected `True` | PASS |
| F6c (https subdomain, explicit standard port) | FAIL — `False`, expected `True` | PASS |
| F7′ (bare host:443) | FAIL — `False`, expected `True` | PASS |
| F7″ (bare host:80) | FAIL — `False`, expected `True` | PASS |
| F8 (explicit port entry covers its URL form) | FAIL — `False`, expected `True` | PASS |

### Guardrail confirmations

1. `src/kronos/manifest.py` — **zero-line diff** (`git diff --stat
   origin/main -- src/kronos/manifest.py` is empty). A manifest signed
   before this brief still verifies — proven with a literal,
   independently pre-captured signed-YAML fixture (signature included)
   loaded through the unmodified `load_and_verify`
   (`test_9_1_a_manifest_signed_before_this_brief_still_verifies`).
2. Excluded-first, default-deny — unchanged control flow in
   `ScopeGuard.is_in_scope`; no new branch returns allow before
   exclusions are fully evaluated.
3. Exclusions are evaluated against every equivalent representation —
   `_address_candidates` extracts the IP literal out of every shape
   (bare IP, bracketed IPv6, URL-embedded, `host:port`-embedded) before
   an exclusion check ever runs; §5.1/§5.2's full matrix (plus the
   §8.4 IPv4-mapped/zone/compressed rows) proves it.
4. No §5 row marked DENY was loosened — every `(lock)` row in the
   matrix below is asserted unchanged.
5. `scope_key` is not touched — `graph.py` is a zero-line diff too (not
   just `manifest.py`); the fix lives entirely in `scope_guard.py`.
6. Stdlib only — `ipaddress`, `fnmatch`, `re`, `urllib.parse`; no new
   dependency.
7. `_ALWAYS_IN_SCOPE_TYPES`/`_NO_IN_SCOPE_COLUMN_TYPES` — untouched,
   out of scope for this brief, confirmed by `graph.py`'s zero-line
   diff.
8. No existing test weakened or deleted. Three **pre-existing**
   sentinel tests
   (`tests/test_budget.py::test_scope_guard_still_has_zero_line_diff`,
   `tests/test_cleanup.py::test_scope_guard_still_has_zero_line_diff`,
   `tests/test_reconcile.py::test_scope_guard_has_zero_line_diff`)
   hash-pin `scope_guard.py`'s exact bytes specifically so that an
   **earlier** brief could prove it left FORK-2 alone — their own
   comments say so verbatim ("FORK-2 ... stays open and is not this
   brief's to resolve"). SPEC_BRIEF10's own guardrail 1 says this is
   the brief where that streak **is meant to end**, so the three
   hashes were re-pinned to `scope_guard.py`'s new content (one
   constant each, logic and messages otherwise untouched) rather than
   left to fail forever. This is flagged here explicitly rather than
   silently folded in: none of those three files is in §3's "May
   change" list, but leaving them failing was not an option either
   (guardrail 8), and the only line that changed in each is the
   expected hash plus a one-line note explaining why. Reviewer: if this
   call is wrong, the fix is a one-line revert of each hash, not a
   revisit of the matcher.

### Not implemented / escalated

Nothing in §5 was left unimplemented. The one judgment call beyond the
literal matrix: **rule 6's "deny is broad" was also applied to an
explicit `host:port` pattern used as an exclusion** (not directly
tested by §5 — the only exclusion-with-explicit-port case in the
matrix, §5.2's last row, uses a *bare*-hostname exclusion) — i.e. an
excluded `"api.acme.com:8443"` denies `api.acme.com` at **any** port,
not just 8443. This reads rule 6 ("an exclusion for a host excludes it
on every port... This asymmetry is deliberate") literally rather than
narrowly, consistent with "when in doubt, deny." Flagged for reviewer
sign-off since it is this brief's one interpretation beyond a named
row, not a guess outside §1.1's stated rules.

### Suite totals

- `tests/`: **550 passed, 1 skipped** (baseline 475/1; +75 net new —
  83 in the expanded `test_scope_guard.py`, 8 of which were already
  there, minus the 3 re-pinned sentinel lines counted as modified, not
  new, in the diff stat).
- `cybergym/cloud/`: **unchanged at 17 passed.**

### Live-use gate (§6, verbatim, for issue #2)

> KRONOS may be pointed at a live client target, or run in Beast mode,
> only when all hold:
> 1. This brief's PR is merged to `main` after reviewer diff approval.
> 2. Every §5 case is green, including §5.1 in full.
> 3. The live CyberGym run earns X-score 3/3, exit 0, at the merge
>    commit on an unproxied host.
> 4. `manifest.py` carries a zero-line diff, so previously signed
>    manifests still verify.
> 5. GitHub issue #2 is closed with a link to the merge commit, not
>    closed as stale.
>
> Until all five hold, KRONOS stays confined to CyberGym and other
> non-live engagements, and S3 does not start.

Status at PR time: (1) not yet — PR open, unmerged, by design. (2) met
— full §5 matrix green, including §5.1 in full. (3) **BLOCKED /
INCOMPLETE** — this is a proxied cloud container; the live Docker build
fails at PyPI with a self-signed-certificate TLS error identical to the
one independently reproduced for Briefs #7 and #8 (environment
limitation, not a code defect; no Dockerfile/requirements.txt edit was
made to work around it). (4) met. (5) not yet — gated on (1) and (3).
**None of this brief's hermetic-test totals are presented as
satisfying criterion 3.**

## Brief #10.1 (amends PR #12, pre-merge) — trailing-glob boundary rule

### Why

Reviewer probing of PR #12 (Brief #10) at branch head `fa6285f` found
that a trailing `*` on a host-shaped pattern (`api.acme.com*`,
`localhost*`, a `host*` inside a literal URL pattern) was still matched
by raw character prefix: `api.acme.com*` authorized the
attacker-registerable `api.acme.com.attacker.net`. This is the one
pattern shape CyberGym's own signed manifest actually uses
(`localhost*`/`127.0.0.1*`/`http://localhost*`, to cover its
nonstandard 8091/4566 ports without a manifest edit) — the shape most
likely to be hand-written by a real operator too — and the live gate
would **not** have caught it: running PR #12's matcher against
CyberGym's real `in_scope` list, all nine range targets passed, so
X-score would have held at 3/3 while the leak sat in the exact path
the range depends on. SPEC_BRIEF10's own §5 matrix never covered a
*trailing* glob, so this was a gap in the brief as much as in the
code.

### §1.1 — the boundary rule (operator-ratified, governing; verbatim)

> A trailing `*` on a host-shaped pattern expands only at a delimiter
> boundary. The permitted boundaries are `:` (port), `/` (path), and
> end-of-string. It must never expand across a `.` into another DNS
> label, and never mid-label. So `api.acme.com*` covers `api.acme.com`,
> `api.acme.com:<port>`, `https://api.acme.com/...` and
> `https://api.acme.com:<port>/...` — and nothing else.
> `api.acme.com.attacker.net` crosses a label; `api.acme.com-evil.net`
> expands mid-label. Both deny.

### §1.2 — port semantics (Option A, operator-ratified DEFAULT)

**The conflict.** `api.acme.com*` (and `localhost*`) must admit
nonstandard ports — CyberGym's API is on 8091, LocalStack on 4566 —
while SPEC_BRIEF10 §1.1 rule 4 says a *bare* hostname entry authorizes
standard ports only. Both cannot be true of the same pattern unless
the trailing `*` itself carries meaning.

**Option A (taken):** a trailing `*` after a complete host means "this
host, any port, any path." Preserves every CyberGym target with no
manifest edit and no re-signing; makes all-ports authorization an
explicit operator act (you get it by typing `*`, never by accident);
bounded by §1.1 to one host's ports, never another host's. Cost: an
operator writing `api.acme.com*` meaning "the website" also authorizes
`:22`/`:3389`/`:5432` — a real, now-documented widening
(`README_scope.md`).

**Option B (rejected):** a trailing `*` stays standard-port-only too,
like a bare host. Tighter, but breaks the range —
`localhost*`/`127.0.0.1*` stop matching `:8091`/`:4566`, X-score falls
to 0/3, and recovering it needs `generate_scope_manifest.py` edited and
the manifest re-signed, both off-limits in this brief's §3 file list
anyway.

### §1.3 — buckets and ARNs stay distinct from hostnames

`kronos-cybergym-*` must keep matching
`kronos-cybergym-general-secrets` (mid-label expansion — correct for a
bucket name, forbidden for a hostname) while `kronos-cybergym-*` must
never authorize `kronos-cybergym-x.attacker.net` (G6). Resolved by
selecting the boundary rule on the **target's** shape
(`classify_target`), never the pattern's text: a hostname/URL/IP-shaped
target gets §1.1's boundary rule; a `bucket_name`/`arn`-shaped target
keeps free glob expansion, as before this amendment.
`classify_target` gained two new explicit shapes to make this concrete
— `arn` (a string starting with the literal `"arn:"`) and
`bucket_name` (a bare token with no `.` anywhere at all).

**Judgment call, not a FORK:** this "no dot anywhere" signal is also
applied to the host *extracted from a url-shaped target*, not only to
a bare target's own top-level shape. `classify_target` only ever
returns `"url"` for a scheme+netloc string, never `"bucket_name"` — so
without this, a dot-free embedded host (e.g. a bare test endpoint
`http://ep-0`) would always take the boundary path even though the
identical bare text `ep-0` on its own gets `bucket_name`'s free
expansion. Checked empirically: this single alignment is what fixed
every real-suite regression this brief's first pass introduced
(`tests/test_budget.py`'s `http://ep-*` fixture, several
`http://localhost:8091*`-shaped fixtures across `tests/test_budget.py`,
`tests/test_validate_runner.py`, `tests/test_negative_controls.py`,
`tests/test_validate_candidates.py`) without weakening or deleting any
of them. The second category — a pattern with an **explicit port**
before the trailing star (`http://host:8091*`) — is deliberately left
on the pre-existing literal-whole-string `_matches_url_pattern` path
entirely unchanged, rather than taught the new boundary rule: an
operator who already wrote the port out is unambiguous, that shape
isn't in SPEC_BRIEF10.1's G1-G6 list, and extending the boundary rule
to it was guessing past what's written here (the brief's own
instruction: "stop and report rather than guessing").

### FORK-U — a pattern with wildcards at both ends

`*.acme.com*`. **DEFAULT (1) taken:** PR #12's existing verdict is
pinned unchanged — it already denies `api.acme.com:8443` (the
`*.`-prefix path's suffix check requires a literal trailing `*`
character inside a real hostname, which never occurs, so it always
falls through to deny), and such a pattern is not treated as a host
pattern for trailing-glob purposes; §1.2's "any port" rule does not
apply to it. Option (2) — harmonizing it with §1.2 — was rejected as a
widening with no demonstrated need.

### Files changed

Exactly SPEC_BRIEF10.1 §3's permitted list: `src/kronos/scope_guard.py`,
`tests/test_scope_guard.py`, `src/kronos/README_scope.md`,
`DECISIONS.md` (this entry), and the three `_SCOPE_GUARD_SHA256`
re-pins (constant + comment only) in `tests/test_budget.py`,
`tests/test_cleanup.py`, `tests/test_reconcile.py`. `manifest.py`:
zero-line diff (confirmed via `git diff`). `cybergym/`: zero-line diff
(confirmed via `git diff`, including `generate_scope_manifest.py`).

### Totals

- `tests/`: **591 passed, 1 skipped** (branch baseline 551/1 + 40 net
  new in `test_scope_guard.py`).
- `cybergym/cloud/`: **unchanged at 17 passed.**

### Live-use gate (§6, unchanged from SPEC_BRIEF10, restated)

Same five conditions as Brief #10's entry above, now reading "this
brief's PR (#12, including this amendment)" for condition 1. Status at
push time: PR #12 remains open and unmerged by design; this brief's
own §5 (G1-G6, §5.2-§5.7) is green in full; the live CyberGym run on
this local, unproxied Kali host earned the required X-score (reported
separately in the PR); `manifest.py` zero-line diff holds; issue #2
stays open pending merge + reviewer sign-off.

## Brief #10.2 (amends PR #12, pre-merge) — explicit-port URL patterns

### Why

Brief #10.1's `_simple_trailing_host_glob_in_url_pattern` deliberately
excluded any pattern whose host part carried a colon (an explicit
port), leaving `scheme://host:port*` (e.g. CyberGym's own
`http://localhost:8091*`-shaped operator habit) on
`_matches_url_pattern`'s literal whole-string `fnmatch` — matching by
raw character prefix. Measured on `d0e5232` with
`in_scope = ['http://localhost:8091*']`, four targets were wrongly in
scope:

| # | target | real host | why the literal prefix matched |
|---|---|---|---|
| H1a | `http://localhost:8091@evil.net/x` | `evil.net` | `localhost:8091` is userinfo, not host |
| H1b | `http://localhost:8091.attacker.net/x` | `localhost` | the "port" is `8091.attacker.net` |
| H1c | `http://localhost:80915/x` | `localhost` | port 80915, not 8091 — shares the leading digits |
| H1d | `http://localhost:8091evil.net/x` | `localhost` | the "port" is `8091evil.net` |

Blast radius was measured and found contained: CyberGym's signed
manifest uses `http://localhost*`/`http://127.0.0.1*` with no port
(already boundary-rule-protected by Brief #10.1), so the live X-score
was never at risk — this was a latent defect in a pattern shape
operators and the test suite both write, not a break of the range.

### The fix

A `scheme://host:port*` pattern means that scheme, that host, that
**exact** port, any path/query/fragment — compared structurally,
never by raw string prefix. `_matches_explicit_port_pattern` (Brief
#10) already did exactly this structured comparison for the non-URL
`host:port` pattern shape, via `_host_port_scheme`'s
`urlsplit().hostname` (resolves userinfo to the real host) and
`urlsplit().port` (an unparseable "port" string raises `ValueError`,
caught and treated as no port at all — never a match). The fix adds
`_simple_explicit_port_host_glob_in_url_pattern` (detects the pattern
shape, mirroring `_host_port_pattern`'s own parsing) and
`_matches_explicit_port_url_pattern` (the comparison itself, adding a
scheme check `_matches_explicit_port_pattern` didn't need since that
function never saw a scheme at all), and routes `scheme://host:port*`
through it on **both** the allow and the exclusion side — unlike
Brief #10.1's bare-trailing-star case, the exclusion side needed
fixing too: the old literal-fnmatch exclusion path required an exact
port match even to deny, which is backwards (§1.1 rule 6: deny is
broad, port-blind). The new exclusion comparison is host-only,
ignoring port and scheme entirely.

**Verified, not assumed** (per the brief's own instruction): the nine
pre-existing tests using `http://localhost:8091*`
(`tests/test_negative_controls.py` ×2, `tests/test_validate_candidates.py`
×1, `tests/test_validate_runner.py` ×6) all target exactly
`http://localhost:8091` or a path under it — host/port/scheme all
match the pattern exactly — and all nine pass completely unmodified.

### H2 — explicitly out of scope

The dot-free-host `bucket_name` classification (every single-label
hostname, not only a genuine bucket name, gets free-glob semantics —
SPEC_BRIEF10.1's own `classify_target` change) is a separate, broader
defect that needs `graph.py` in its file allowlist to fix properly and
was not attempted here. **FORK-2 remains incomplete and GitHub issue
#2 stays open** until H2's own brief also lands.

### Files changed

Exactly SPEC_BRIEF10.2 §4's permitted list: `src/kronos/scope_guard.py`,
`tests/test_scope_guard.py`, `src/kronos/README_scope.md`,
`DECISIONS.md` (this entry), and the three `_SCOPE_GUARD_SHA256`
re-pins (constant + comment only, guards/messages intact) in
`tests/test_budget.py`, `tests/test_cleanup.py`,
`tests/test_reconcile.py`. `manifest.py`: zero-line diff. `cybergym/`:
zero-line diff. `graph.py`, `lifecycle.py`, `schema.py`, `validate/`,
`reconcile/`, `ingest/`, `budget/`, `cleanup/`, `events.py`: all
zero-diff (confirmed via `git diff`).

### Totals

- `tests/`: **620 passed, 1 skipped** (branch baseline 591/1 + 29 net
  new in `test_scope_guard.py`).
- `cybergym/cloud/`: **unchanged at 17 passed.**
- The nine pre-existing explicit-port tests: unmodified, all pass.

### Live-use gate (§6, unchanged, restated)

Same five conditions as Brief #10/#10.1's entries, now reading "PR #12
(including this amendment)" for condition 1. Status at push time: PR
#12 remains open and unmerged by design; G1-G6 and every Brief
#10/#10.1 matrix section stay green; the live CyberGym run on this
local, unproxied Kali host earned the required X-score (reported
separately in the PR); `manifest.py` zero-line diff holds; issue #2
stays open — not only pending merge, but explicitly because H2 has not
yet closed.

## Brief #10.3 (FORK-2's final piece) — node-type-aware scope dispatch

### Why

Two defects remained after #10.2, both tracing to the same root cause
as every prior round in this series (§0.3 of the brief itself, "the
method defect"): `classify_target` only ever has the target *string*
to go on, and a dot-free bare token is genuinely ambiguous from the
string alone. `localhost*` wrongly authorized `localhostevil` and
`localhost-evil` (**H2**) — not a `localhost`-specific bug; any
internal single-label hostname (`jenkins`, `intranet`, `dc01`) has the
same exposure, and S3 (infra ingestion) is exactly where those arrive.
Separately, `excluded = ["http://localhost:8091*"]` denied the URL
form of a host but not its bare `localhost:8091`/`localhost` forms
(**H3**) — Brief #10 §1.1 rule 6's "every port, scheme, path, *and
representation*" was under-implemented across shape boundaries, not
just within one shape.

### The fix (H2): `node_type` becomes a required argument

`ScopeGuard.is_in_scope` and the module-level `scope_guard` both gained
a required keyword-only `node_type` parameter — no default, no
permissive fallback, so no call site can forget it (a permissive
default is exactly how H2 happened). `graph.py:140` passes the `type`
it already has at the `upsert_node` call site; this is the one
approved change to that file (§2.3), one line.

`NODE_TYPE_SHAPES` (owned by `scope_guard.py`) maps each of the 12
scope-gated node types to its permitted target-shape family —
`src/kronos/README_scope.md`'s own table has the full list with
evidence. The critical row: **`CLOUD_RESOURCE` is the only type with
free mid-token glob expansion** — `_effective_shape(target, node_type)`
corrects `classify_target`'s raw `"bucket_name"` shape back to
`"host"` for every other type, which is what lets `kronos-cybergym-*`
keep matching `kronos-cybergym-general-secrets` under `CLOUD_RESOURCE`
while `localhost*`/`jenkins*` stop over-matching under `HOST` — the
exact two cases H2 could not separate from the string alone. The type
gate runs **before any pattern is even consulted**: an unrecognised,
empty, or `None` `node_type` denies unconditionally
(`NODE_TYPE_SHAPES.get(node_type)` falsy), and so does a recognised
type whose family doesn't include the target's effective shape (e.g. a
bucket glob under `HOST` — tested explicitly, SPEC_BRIEF10.3 §5.1's
last row).

### The fix (H3): exclusions cross shape boundaries too

`_matches_explicit_port_url_pattern` and `_matches_trailing_host_glob`'s
`scheme://host*` case both had a hard `shape != "url": return False`
gate — correct for the allow side (an explicit scheme genuinely
requires a URL to compare against), but wrong for exclusion, which
must be port-, scheme-, *and representation*-blind. Both now accept
any host-ish shape on the exclusion path and compare host identity
alone. A second gap surfaced only once the §5.4 generated matrix was
run end to end (see below): `excluded = ["http://localhost:8091*"]`
still failed to deny the bare `localhost` form, because on the
exclusion path `shape` is always the *raw*, node-type-independent
`classify_target` result — `"bucket_name"` for a dot-free bare token,
never `"host"` — and the exclusion-side comparisons didn't recognise
that shape at all. Fixed by teaching `_host_port_scheme` to treat
`"bucket_name"` as a plain host text (exclusion-only in practice: the
allow side never sees `"bucket_name"` as `shape`, since
`_effective_shape` has already corrected it by the time `_matches` is
called) and widening the two gates' accepted-shapes tuple
(`_HOST_SHAPES_FOR_EXCLUSION`) to include it.

### §5.4 — the generated matrix, and what it caught

The brief's own method-fix: 13 pattern shapes × 14 target shapes,
declared as a literal data table (not computed from `scope_guard.py`),
run once for the allow side under `node_type="HOST"` and once for the
exclusion side (type-independent, via `_matches(..., is_exclusion=True)`
directly — `is_in_scope`'s own type gate would otherwise confound an
"excluded" `True` with a "denied by type mismatch" `True` for the
url/arn/bucket_name target columns, which a HOST-typed allow check can
never tell apart). 364 cells total (182 × 2), every one present —
`dict[pattern][target]` indexing with no `.get()` default, so an
undeclared cell raises `KeyError` and fails the test rather than
silently passing. **This is exactly what caught the second H3 gap
above** — the `localhost` exclusion cell failed on the first run,
before the `_host_port_scheme`/`_HOST_SHAPES_FOR_EXCLUSION` fix. Scope
decision, reported rather than silently reduced: the allow grid runs
once, under `node_type="HOST"`, not once per node type — `CLOUD_RESOURCE`'s
bucket/ARN pattern families are exercised by the dedicated H2/G6 lock
tests instead of a second full 182-cell grid, which would mostly
duplicate the same structural coverage at this scale.

### FORK-V — module-level `scope_guard` helper

DEFAULT (1) taken: `node_type` is a required kwarg here too, matching
`is_in_scope` — a second, permissive-by-omission path is exactly how
H2 happened. This is a **documented conflict with SPEC.md**, whose
"SCOPE GUARD" section still reads `scope_guard(target, manifest)` (two
positional arguments, no type); SPEC.md is outside this brief's file
list, so the conflict is reported here, not resolved by editing it.

### FORK-W — SECRET/IDENTITY/TECHNOLOGY/FINDING

Checked against this branch's actual source, not assigned by analogy.
`SECRET`: every real ingester (`ingest/__init__.py:56`,
`ingest/mobile/parser.py:253`) sets `scope_key=bundle_id`
unconditionally, so its effective shape family is identical to
`MOBILE_APP`'s (`{"host"}`) — real evidence, DEFAULT (1).
`IDENTITY`/`TECHNOLOGY`/`FINDING`: grep-verified zero production
`upsert_node` call sites for all three anywhere in `src/` or
`cybergym/`, and no id convention has ever been established for any
of them (`FINDING`'s one documented formula,
`canonical_key_for_finding`, is itself unreachable today per
`reconcile/canonical.py`'s own docstring — no ingester populates
`finding_class`/`location_sig`). Option (2) taken for all three: deny
unconditionally rather than guess a family with no evidence behind it.
If any of the three ever gets a real ingester, `NODE_TYPE_SHAPES` is
the place to revisit with that evidence.

### PARAMETER (§1.4)

Empty permitted-shape family: never allow-authorized by any pattern,
regardless of the target's apparent shape. It has no production
ingester either; it inherits scope in practice via its parent
endpoint's own stamp at enrichment time, a separate mechanism from
this gate.

### Out-of-§3 test regressions — reported, not edited

Six pre-existing tests, all outside this brief's file list, broke
under the correct, newly-added type gate because their fixtures used a
non-representative id/scope_key shape for their node type — a bare
hostname standing in for a URL on `API_ENDPOINT`/`WEB_ENDPOINT`
(`"api.acme.example.com"`, `"web:1"`/`"web:2"`), or a hostname string
standing in for a bucket name/ARN on `CLOUD_RESOURCE`'s `scope_key`
(`"api.acme.example.com"`). Per the brief's own guardrail ("stop and
report rather than broaden"), none of the six were edited:

- `tests/test_schema_graph.py::test_upsert_node_stamps_in_scope_via_scope_guard`
- `tests/test_invariants.py::test_invariant_out_of_scope_secret_cannot_anchor_finding`
- `tests/test_invariants.py::test_invariant_find_paths_returns_seeded_mobile_to_cloud_chain`
- `tests/test_query.py::test_find_paths_returns_seeded_mobile_to_cloud_chain`
- `tests/test_query.py::test_find_paths_only_in_scope_excludes_out_of_scope_hop`
- `tests/test_reconcile.py::test_web_endpoint_real_duplicate_merges_and_tombstones`

### Files changed

Exactly SPEC_BRIEF10.3 §3's permitted list: `src/kronos/scope_guard.py`,
`src/kronos/graph.py` (one line, §2.3's limit — the `node_type=type`
passthrough only), `tests/test_scope_guard.py`, `src/kronos/README_scope.md`,
`DECISIONS.md` (this entry), and the three `_SCOPE_GUARD_SHA256`
re-pins (constant + comment only) in `tests/test_budget.py`,
`tests/test_cleanup.py`, `tests/test_reconcile.py`. `manifest.py`:
zero-line diff. `cybergym/`: zero-line diff. `lifecycle.py`,
`schema.py`, `validate/`, `reconcile/`, `ingest/`, `budget/`,
`cleanup/`, `events.py`: all zero-diff (confirmed via `git diff`).

### Totals

- `tests/`: **1023 passed, 1 skipped**, plus the 6 reported (not
  fixed) pre-existing failures above (branch baseline 620/1 + the
  §5.4 generated matrix's 364 new cases + the rest of this brief's own
  tests).
- `cybergym/cloud/`: **unchanged at 17 passed.**

### Live-use gate (§6, verbatim, restated in `README_scope.md` too)

Status at PR time: PR open and unmerged, by design. Every case from
Briefs #10/#10.1/#10.2 and this brief is green, including §5.4's
generated product with zero undeclared cells (364/364). Live CyberGym
X-score reported separately in the PR. `manifest.py` zero-line diff
holds; a pre-Brief-#10 signed manifest still verifies
(`test_9_1_a_manifest_signed_before_this_brief_still_verifies`). Issue
#2 may close once this PR merges with reviewer approval and the merge
commit is linked — H2 is now closed, which was the last open item
blocking it.

## Brief #10.4 (FORK-2's closing piece) — scope_key dispatch, evidence-only shape families, path-blind exclusions

### Why

seq 5 independent review of 10.3's PR (#13) returned FAIL: 6 regressions
in `tests/`, traced to two real defects in 10.3's own §1.2 table (D1/D2),
plus one deny-side gap 10.3's own §1.3 fix left half-implemented.

**D1 — the id-shape table was applied to a string that isn't an id.**
`graph.py:140` gates `scope_key or id`. §1.2's table is, by its own
prose, about how a type's **id** is actually produced. When a
`scope_key` is present, it is that string (not the id) that gets
gated, and the table does not describe it. 10.3's builder saw this and
worked around it one row at a time: `SECRET`'s row was assigned
`{"host"}` *because* every production SECRET call site sets
`scope_key=bundle_id`, so a family was chosen to fit the scope_key
rather than the id — a per-row patch, not a fix for the structural
problem.

**D2 — one row was assigned by analogy.** `WEB_ENDPOINT`'s row
(`{"url"}`) was fitted to API_ENDPOINT's real URL evidence — FORK-W's
exact violation. Measured: there is no production `WEB_ENDPOINT`
ingester anywhere in `src/` or `cybergym/`; its only documented key,
`canonical_key_for_web_endpoint`, is a *merge* key consumed by
`reconcile/runner.py:84`, never a node id; and that key's own shape
classifies as `"unknown"`, not `"url"`. So `{"url"}` described a shape
nothing produces, and would deny the real canonical key anyway.

### The fix (§1.1): `scope_key` is gated by its own shape

`ScopeGuard.is_in_scope` and the module-level `scope_guard` both gained
a second required keyword-only parameter, `target_kind` (`"id"` or
`"scope_key"`) — no default, same reasoning as 10.3's `node_type`
requirement: a permissive-by-omission path is exactly how H2 happened.
`graph.py:140` now passes whichever of `scope_key`/`id` it resolved,
tagged with which one it is; the `scope_key or id` precedence itself
is unchanged (§1.5's one-kwarg limit). When `target_kind="scope_key"`,
`NODE_TYPE_SHAPES`'s id-shape family filter is never consulted at all
— the scope_key is gated purely on its own shape, via a new
`_scope_key_shape` function. `_scope_key_shape` differs from
`_effective_shape` in exactly one place: with no `node_type` signal at
all to consult, a dot-free string's ambiguous `"bucket_name"` reading
always resolves to `"host"` (never `CLOUD_RESOURCE`'s free mid-token
expansion) — narrower, never looser (guardrail §9), matching the
brief's own worked example: a `CLOUD_RESOURCE` whose `scope_key` is
`localhost` is governed by the host boundary rule, not the bucket-glob
treatment the identical string gets on the id path. Fail-closed is
unaffected either way: an unrecognised/empty/`None` `node_type` still
denies before any pattern is consulted, scope_key or not.

### The fix (§1.2): `NODE_TYPE_SHAPES` becomes evidence-only, no exceptions

10.3's own FORK-W rule (already applied to
`IDENTITY`/`TECHNOLOGY`/`FINDING`) is generalised into the table's
construction rule, with no exception: every row is cited to a
verified producing call site; a canonical/merge key is never citable
evidence for an id; a type with no production producer and no
established id convention gets `frozenset()`. `WEB_ENDPOINT` becomes
`frozenset()` (D2, above). `SECRET` also becomes `frozenset()`: once
`is_in_scope` can tell id and scope_key apart (§1.1), the
scope_key-fitting justification for its old `{"host"}` row is gone,
and its real id (sha256-derived) matches no shape family this module
has — denying nothing in production, since every real call site sets
`scope_key` regardless (FORK-Y, DEFAULT taken).

### The fix (§1.3): exclusions become path-blind too, closing 10.3's own H3 fix

10.3's H3 fix widened the exclusion-side cross-shape comparison for
the *simple* explicit-port and trailing-glob pattern shapes, but a URL
exclusion pattern that itself carries a path
(`http://localhost:8091/internal/*`) still fell through to
`_matches_url_pattern`'s literal, path-aware `fnmatch`. Measured: that
pattern let `localhost`, `localhost:8091`, and
`http://localhost:8091/other` all through, even though the path-free
`http://localhost:8091*` already denied every one of them — a *more*
specific exclusion pattern produced a *narrower* deny, the exact
under-match class H3 exists to eliminate. Fixed by reducing such a
pattern, on the exclusion side only, to its host/address identity via
`urlsplit().hostname` (FORK-Z, DEFAULT yes: query/fragment discarded
too, which required no extra code — `urlsplit().hostname` never
included them) and comparing it against any host-ish identity the
target carries, exactly like every other exclusion shape. The allow
side is completely unchanged: `_matches_url_pattern`'s literal,
path-aware behaviour still governs an explicit allow entry that spells
a path out.

### FORK-X / FORK-Y / FORK-Z

- **FORK-X (DEFAULT, taken):** the id/scope_key distinction is a new
  required kwarg, `target_kind`, with no default.
- **FORK-Y (DEFAULT, taken):** `SECRET`'s row is re-derived to
  `frozenset()` rather than kept at `{"host"}` — see "the fix (§1.2)"
  above.
- **FORK-Z (DEFAULT yes, taken):** the exclusion-side host-identity
  comparison also discards a URL pattern's query/fragment.

### §5.4's generated matrix — the third axis

10.3's own 364-cell generated matrix (13 patterns × 14 targets × 2
sides) is extended, not replaced: its two path-bearing URL pattern
rows (`https://api.acme.com/v1/*`, `https://api.acme.com:8443/v1/*`)
were declared `[False] * 14` on the exclusion side under 10.3 — the
exact Finding-A gap, now corrected to match the host-only exclusion
rule's other rows. A second, explicitly declared 9-row table adds the
id/scope_key axis, one representative `(node_type, pattern, target)`
triple per node type reachable via a scope_key in real production
evidence, each cell's expected id-path and scope_key-path verdicts
cited to the rule that determines it (e.g. `CLOUD_RESOURCE`'s row is
the direct id-vs-scope_key contrast from §1.1's worked example, above;
`WEB_ENDPOINT`/`SECRET`'s rows are the direct demonstration that §1.1
is what lets a node with an empty id family still reach "in scope" via
an authorized scope_key). Total declared cells: 364 (corrected) + 9
(new axis, run twice each = 18 assertions) = 373 generated-matrix
cells, all declared, zero undeclared (confirmed via the dedicated cell
count tests). The individual §5.1/§5.2/§5.3 case tests are additional,
not part of this count.

### §5.6 — three different remedies for six pre-existing failures

- **(a) Four `API_ENDPOINT` id corrections (§1.4):** a bare host
  (`"api.acme.example.com"`) was corrected to a full URL
  (`"https://api.acme.example.com"`) in
  `tests/test_invariants.py::test_invariant_out_of_scope_secret_cannot_anchor_finding`,
  `tests/test_invariants.py::test_invariant_find_paths_returns_seeded_mobile_to_cloud_chain`,
  `tests/test_query.py::test_find_paths_returns_seeded_mobile_to_cloud_chain`, and
  `tests/test_schema_graph.py::test_upsert_node_stamps_in_scope_via_scope_guard`.
  The deliberately out-of-scope control, `api.evil.com`, was left
  untouched in every one — it was never broken by this correction (a
  bare-host `API_ENDPOINT` id failed the url-shape family filter
  before and after this brief).
- **(b) One scope_key correction:**
  `tests/test_reconcile.py::test_web_endpoint_real_duplicate_merges_and_tombstones`
  gave its two `WEB_ENDPOINT` nodes (`"web:1"`/`"web:2"`, canonical
  merge keys, never ids) a `scope_key="acme.example.com"` — §1.1 is
  what lets this test's subject (WEB_ENDPOINT dedup/merge) reach "in
  scope" at all, since WEB_ENDPOINT's id family is now `frozenset()`.
- **(c) Restored by §1.1 alone, no edit:**
  `tests/test_query.py::test_find_paths_only_in_scope_excludes_out_of_scope_hop`
  constructs a `CLOUD_RESOURCE` with `scope_key="api.acme.example.com"`
  (host-shaped, not bucket/ARN-shaped) — 10.3's bug applied the
  CLOUD_RESOURCE id-shape family to that scope_key and denied it; §1.1
  alone fixes it, with zero changes to the test file. Verified green,
  unedited, by diffing `tests/test_query.py` against the pre-this-brief
  head.

### Out-of-§3 test regression — reported, not edited

Implementing §1.2 correctly (SECRET's id family -> `frozenset()`,
FORK-Y) exposes a **seventh** failure, not one of the six 10.3 left
and not named anywhere in this brief's §5.6:
`tests/test_reconcile.py::test_secret_real_duplicate_moves_edges_recomputes_status_loser_is_edgeless_and_idempotent`.
Its `_secret_with_material` fixture calls `g.upsert_node("SECRET", ...)`
with no `scope_key` at all (unlike every real SECRET ingester, which
always sets `scope_key=bundle_id` unconditionally — the very fact
FORK-Y's reasoning relies on), so the SECRET nodes it creates now
reach the id path with an empty family and deny, breaking the
`find_paths(g, "MOBILE_APP", "CLOUD_RESOURCE")` assertion later in the
same test. This brief's §3 permits exactly two edits to
`tests/test_reconcile.py` (the one named `WEB_ENDPOINT` scope_key
correction, (b) above, and the `_SCOPE_GUARD_SHA256` pin) — this
fixture is neither, so it is reported here rather than edited, per the
brief's own guardrail ("any test outside §3's permitted edits needing
a change: reported, not edited"). The correct fix, if authorized in a
future brief, is the same shape as (b): give `_secret_with_material`'s
callers a `scope_key`, matching real production SECRET ingestion.
`tests/`: **1 failed** (this one), not the 0 this brief's §8.7
otherwise requires — see the builder's report for the full accounting.

### Files changed

Exactly SPEC_BRIEF10.4 §3's permitted list: `src/kronos/scope_guard.py`,
`src/kronos/graph.py` (§1.5's one-kwarg limit only), `tests/test_scope_guard.py`,
`src/kronos/README_scope.md`, `DECISIONS.md` (this entry), the five
§5.6(a)/(b) test corrections in `tests/test_invariants.py` (2),
`tests/test_query.py` (1), `tests/test_schema_graph.py` (1), and
`tests/test_reconcile.py` (1), and the three `_SCOPE_GUARD_SHA256`
re-pins (constant + comment only) in `tests/test_budget.py`,
`tests/test_cleanup.py`, `tests/test_reconcile.py`. `manifest.py`:
zero-line diff. `cybergym/`: zero-line diff (confirmed via `git diff
--stat d2ad51e -- src/kronos/manifest.py cybergym/`).

### Totals

- `tests/`: **1068 passed, 0 failed, 1 skipped** at `2a676a8` (re-measured in
  SPEC_BRIEF10.5; the earlier "1067 passed, 1 failed" figure was stale -- the
  `_secret_with_material` fixture was repaired at `2a676a8`). Branch baseline
  620/1 at `dcbdba9`.
- `cybergym/cloud/`: **unchanged at 17 passed.**

### Live-use gate (§6, verbatim, restated in `README_scope.md` too)

<!-- BEGIN SPEC_BRIEF10.5 §6 GATE (byte-verbatim; tests/test_scope_guard.py compares) -->
FORK-2 is complete, and issue #2 may close, when **all** hold:

1. This PR is merged to `main` after independent reviewer diff approval.
2. Every case from Briefs #10, #10.1, #10.2, #10.3, #10.4 and this brief is green, including
   §5.4's generated product with zero undeclared cells and every cell prose-referenced.
3. Live CyberGym X-score 3/3, exit 0, at the merge commit, on an unproxied host.
4. `manifest.py` zero-line diff; a pre-Brief-#10 signed manifest still verifies.
5. Issue #2 closed **with a link to the merge commit**.
6. `README_scope.md` documents the node-type dispatch, the allow/deny asymmetry, the id/scope_key
   distinction, rule 5 and its citation discipline, the address-shaped exclusion rule, and that
   `CLOUD_RESOURCE` is the only type with free mid-token expansion.
7. The `httpx2` environment gap is closed by the maintainer, or explicitly accepted in writing.

Only then may KRONOS be pointed at a live client target or run in Beast mode, and only then does
**S3** start.

**§6 is the live-use gate. It is not the acceptance criteria. §8 is.** Conditions 1, 3 and 5 are
unmeasurable before a merge exists; condition 7 is a maintainer action.
<!-- END SPEC_BRIEF10.5 §6 GATE -->

Status at PR time: PR open and unmerged, by design. `manifest.py`
zero-line diff holds; a pre-Brief-#10 signed manifest still verifies.
Live CyberGym X-score reported separately in the PR/builder report —
this run did not execute the live CyberGym suite (no network beyond
pushing the feature branch, per this brief's own restriction); the
`httpx2`/`httpcore2`/`truststore` environment gap (§5.5) remains open,
a maintainer action this loop cannot perform, reported rather than
papered over by adding those pins to `cybergym/requirements.txt`
(forbidden regardless, §2.2). Issue #2 may close once this PR merges
with reviewer approval, the merge commit is linked, **and** the
out-of-§3 regression above is resolved (by a follow-up brief
authorizing the `test_secret_real_duplicate_*` fixture's scope_key
correction, or by an explicit, written acceptance that it is not
blocking).

### SPEC_BRIEF10.5 FORK-AB — HOST narrowing proposed and REJECTED

§1.1 originally derived `HOST`'s family as `{host, ip}` under rule 5, reasoning from
`schema.py:223`, where `NODE_COLUMNS["HOST"]` carries no `port` column.

**Measured result: 21 tests failed.** Fourteen were ratified cases — `test_5_5_lock_*`,
`test_5_5b_lock_*`, `test_b101_5_2_trailing_glob_locks`, four
`test_b103_5_4_generated_allow_matrix_host` cells, and
`test_b103_h2[HOST-localhost*-localhost:8091-True]`, which **is** Brief #10.3's own H2 table row.
One was `test_9_1_a_manifest_signed_before_this_brief_still_verifies`, guardrail §2.1's
signed-manifest proof.

**Disposition: rejected, and rule 5's precedence corrected.** Brief #10.3 §1.2's prose table
already assigns `HOST` `host, ip, host_port, ip_port` with "boundary rule applies", reviewer-
verified. A ratified predecessor-brief prose decision is rule-1 evidence, so rule 5 — which governs
only where neither a producer nor a ratified prose decision exists — is never reached for `HOST`.
The absence of a port *column* does not forbid a port-bearing *id*; `SERVICE` stores a port
separately **and** carries one in its id.

Retyping the 20 lock tests to `SERVICE` was considered and rejected: it would overwrite decisions an
independent reviewer already approved, on the strength of an inference those decisions contradict.

### SPEC_BRIEF10.5 FORK-AC — allow side does NOT learn address identities from path-bearing URL patterns (DECLINED)

Question: should an *allow* pattern such as `http://10.0.0.5/admin/*` also authorize the bare
address `10.0.0.5` (as §1.2 now makes the *exclusion* side deny it)?

**Disposition: declined (DEFAULT, taken).** That would widen the allow side -- a path-bearing URL
pattern would start authorizing targets (bare IPs, other ports) it never named -- and guardrail §9
forbids widening the allow side anywhere. The asymmetry is deliberate (Brief #10 §1.1 rule 6: allow
narrow, deny broad). The allow side keeps `_matches_url_pattern`'s literal, path-aware behaviour and
the existing `_matches_address_pattern` route for CIDR/bare-IP entries, unchanged; this is proven by
the standing differential test (`test_b105_5_5_differential_allow_side_unchanged_exclusion_only_tightens`:
0 allow-side differences over 340 pattern x target pairs at `dcbdba9`, `2a676a8` and head).

### SPEC_BRIEF10.5 — totals (measured at the head that carries this entry)

- `tests/`: **3445 passed, 0 failed, 1 skipped** (baseline 1083/0/1 at `72fb71d`; the increase is
  the rebuilt §5.4 grid -- 2366 declared cells, 2359 asserted -- plus the byte-verbatim and
  differential tests).
- `cybergym/cloud/`: **17 passed.**
- Rebuilt §5.4 grid: 12 node types x 13 patterns x 14 targets (allow) + 13 x 14 (exclusion) = 2366
  cells, 0 undeclared, every cell clause-referenced. 11 cells are PAUSE-DECISION (unfilled, unasserted):
  `_P4_BOTH_ENDS_GLOB` x `_T1_HOST` on the allow side for HOST/SERVICE/MOBILE_APP/MOBILE_COMPONENT, and
  `_P4_BOTH_ENDS_GLOB` x {api.acme.com, :8443, both URL forms, userinfo URL, lookalike, mid-label} on the
  exclusion side. No prose in #10..#10.5 determines them.
