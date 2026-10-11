# DECISIONS.md — Brief #1 (Findings Graph Core + Validation Lifecycle)

Every non-trivial autonomous call made while building this brief, per the
escalation contract in `SPEC.md`. None of these required a `FORK:` stop —
each was a naming/property/file-layout/library detail, or a straight bug
fix caught by its own test, with low cost if it turns out wrong later.

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
