# SPEC_BRIEF10.4.md — scope_key dispatch, evidence-only shape families, path-blind exclusions

**Status:** DRAFT awaiting GATE-1. Authored by the orchestrator (claude-opus-5) from the seq 5
independent review and the seq 7/9 research turns. Not yet approved; no code may be written
against it until the maintainer approves it at GATE-1.

**Stage:** FORK-2 (issue #2). **Predecessor:** SPEC_BRIEF10.3, reviewed FAIL at PR #13 head
`d2ad51e611927525780b9069db2bc16b0a7209b2`.
**On approval this lands at repo-root `SPEC_BRIEF10.4.md` on a fresh `claude/*` feature branch.**

**Measured baselines this brief is written against** (re-measured this session, not carried
forward):

| Tree | `tests/` | `cybergym/cloud/` | Live X-score |
|---|---|---|---|
| base `dcbdba9` (main) | 620 passed, 1 skipped | 17 passed | — |
| head `d2ad51e` (PR #13) | **6 failed**, 1023 passed, 1 skipped | 17 passed | `X-SCORE: 3/3 chains validated end-to-end`, exit 0 |

The live 3/3 at the PR head is recorded and is **not** evidence that the six failures are
acceptable. It is evidence that CyberGym's own range never constructs the shapes the six
failures use — see §0.4.

---

## 0. Why this brief exists

SPEC_BRIEF10.3 shipped the H2/H3 work and introduced six regressions in `tests/`. The seq 5
independent review returned FAIL (§8: 9 PASS, 1 FAIL, 1 UNVERIFIABLE; §6: 2 of 6 met) with
findings A–F. Research then reversed two of its own early conclusions. This brief closes the six
regressions, Finding A and Findings B–D, and corrects the one row of 10.3's §1.2 table that was
assigned without evidence.

### 0.1 The method defect, restated — now a hard rule

Every expected value in every test matrix in this brief **derives from this brief's prose**, never
from observed behaviour. A grid cell written from what the code currently does turns a conformance
test into a change detector. This is the fourth occurrence of this defect in the series; 10.3's
§5.4 grid declared two cells expected-`False` that codified a bug (Finding B).

**If the prose of this brief does not determine a cell, that is a PAUSE-DECISION. Stop and report.
Do not supply the value by judgment, by analogy, or by running the code.**

### 0.2 What 10.3 got right, and must not be re-litigated

The seq 7 research turn alleged that 10.3's builder applied §1.2's verification clause
selectively. **That allegation was wrong and is withdrawn.** `scope_guard.py` lines 116–178 carry a
per-type evidence block, headed *"gathered against this branch's actual source (not assigned by
analogy — FORK-W)"*, which cites a real producing call site per row. Its API_ENDPOINT citation was
independently verified at `ingest/mobile/parser.py:276`:

```python
upserts.append(NodeUpsert("API_ENDPOINT", found.url, {"source": "static"}))
```

API_ENDPOINT ids **are** full URLs in the only production ingester that exists. `{"url"}` is
evidenced and correct. H2's node-type dispatch, H3's cross-shape exclusions, the fail-closed rule
and the `CLOUD_RESOURCE`-only mid-token expansion all stand unchanged.

### 0.3 The two real defects

**D1 — the id-shape table is applied to a string that is not an id.** `graph.py:140` gates
`scope_key or id`. §1.2's table is, by its own prose, about *how that type's ids are actually
produced*. When a `scope_key` is present it is the gated string, and it is being filtered by a
table that does not describe it. 10.3's builder saw this and worked around it one row at a time:
its `SECRET` row is assigned `{"host"}` **because** every production SECRET call site sets
`scope_key=bundle_id`, so the family was chosen to fit the scope_key rather than the id. That is a
per-row patch for a structural problem.

**D2 — one row was assigned by analogy, against the brief's own FORK-W rule.** `WEB_ENDPOINT` is
documented as *"no production ingester yet but shares the same URL convention"* as API_ENDPOINT.
That is an analogy, and the same comment block forbids analogy. It is also inconsistent with how
`IDENTITY`, `TECHNOLOGY` and `FINDING` were handled in that same block, where the absence of a
production ingester produced an **empty family and a deny**, reasoned explicitly as *"with no real
evidence to assign a family from, denying is the safer answer, not a guess by analogy."*

Measured, this session: there is no production `WEB_ENDPOINT` ingester;
`canonical_key_for_web_endpoint` returns `f"web:{method}:{scheme}://{host}[:{port}]{path}"`, which
is a **merge key** (`reconcile/runner.py:84`), not a node id; and that real key classifies as
**`unknown`**, not `url`. So `{"url"}` describes a shape nothing produces, and would deny the
canonical key anyway.

### 0.4 Why the live X-score is green while six tests fail

CyberGym's validation run sets `CLOUD_RESOURCE` scope_keys to ARN form
(`kronos_validation_run.py:255,260`) and mobile scope_keys to the bundle id (`:266,:273`) — every
one inside its permitted family — and production API_ENDPOINT ids are full URLs. The live path
therefore never touches a disputed cell. Live green and test red are consistent, and neither
overrides the other.

---

## 1. The decisions

### 1.1 A `scope_key` is gated by its own shape, independent of `node_type`

**Normative.** A `scope_key` is an explicit, operator- or ingester-supplied assertion of the
node's in-scope network identity. It is **not** an id, and the `NODE_TYPE_SHAPES` id-shape table
does **not** apply to it.

- When `graph.py`'s `scope_key or id` resolves to a **`scope_key`**, the allow side gates it on its
  own `classify_target` shape, with no node-type shape-family filter.
- The id-shape family filter applies **only** when that expression falls through to the **id**.
- Everything else about the allow side is unchanged: the boundary rule, the standard-port gate,
  `CLOUD_RESOURCE`-only mid-token expansion, and excluded-first default-deny all still apply to a
  `scope_key` exactly as they do to an id.
- Fail-closed is unaffected: an unknown, empty or `None` `node_type` still denies before any
  pattern is consulted, **whether or not** a `scope_key` is present. §1.1 of 10.3 is untouched.

This is strictly a change to *which table governs which string*, not a widening of any pattern
rule. A `CLOUD_RESOURCE` whose scope_key is `localhost` becomes governed by the host boundary rule
— narrower than bucket-glob treatment, not looser.

**Consequence to implement:** 10.3's `SECRET` row exists only to make the scope_key path work. Once
scope_keys are gated on their own shape, that justification is gone. `SECRET` is re-derived from
its **id** under §1.2 like every other row.

### 1.2 No row may be assigned by analogy; no evidence means an empty family

**Normative, and it generalises 10.3's own FORK-W rule into the table's construction rule.**

1. Every row of `NODE_TYPE_SHAPES` is assigned from a **cited, verified producing call site** in
   `src/` or `cybergym/`.
2. A type with **no production producer and no established id convention** gets
   **`frozenset()`** — it denies unconditionally. This is the rule already applied to `IDENTITY`,
   `TECHNOLOGY` and `FINDING`; it is now the rule for every such type without exception.
3. **No row is ever assigned by analogy to another type**, by shared naming, or by a documented
   convention that no code implements.
4. A canonical/merge key is **not** an id. It may not be cited as evidence of id production.

**`WEB_ENDPOINT` therefore becomes `frozenset()`.** It has no production ingester; its only
documented key is a merge key; and that key does not classify as `url`.

The finished table must be reported **with its per-row citation**, and a row whose citation is
"none" must carry `frozenset()`. A row that cannot be assigned under rules 1–4 is a
PAUSE-DECISION.

### 1.3 Exclusions are blind to path, port, scheme *and* pattern shape — including when the pattern carries a path

**Normative. This is the deny-side half of 10.3's §1.3, which 10.3 left partly implemented
(Finding A).**

10.3 §1.3 already says an exclusion denies if **any** target identity matches the exclusion's
extracted host/address identity, *"regardless of port, scheme or path"*. That must hold for **every
URL exclusion pattern, whether or not the pattern itself spells out a path.**

Today a URL exclusion pattern that carries a path falls through `_matches`'s `"://"` branch to
`_matches_url_pattern`, a literal path-aware `fnmatch` against the raw target string. Measured:

| exclusion `http://localhost:8091/internal/*` vs target | today | required by §1.3 |
|---|---|---|
| `http://localhost:8091/internal/x` | denies | denies |
| `localhost:8091` | **allows** | **denies** (shape-blind) |
| `http://localhost:8091/other` | **allows** | **denies** (path-blind) |
| `localhost` | **allows** | **denies** (port-blind) |
| `http://localhost:8091/` | **allows** | **denies** |

The path-free pattern `http://localhost:8091*` already denies all five. So **adding a path to a URL
exclusion pattern silently collapses a broad deny into a narrow one** — an operator who writes a
more specific exclusion gets *less* exclusion. That is the under-match H3 exists to eliminate.

**The rule:** on the **exclusion** side, a URL pattern's path is **discarded**; the pattern is
reduced to its host/address identity (and port and scheme are likewise ignored, per rule 6) and
compared against all of the target's identities. The allow side is **unchanged**:
`_matches_url_pattern`'s literal, path-aware behaviour remains exactly as it is for allow
patterns, because there the operator spelled the path out to *narrow* authorization, and FORK-S
governs only what an implicit pattern may infer.

The asymmetry is the specification: **deny broad, allow narrow.**

### 1.4 The four bare-host `API_ENDPOINT` tests are corrected, not the table

**Normative.** `{"url"}` is evidenced for `API_ENDPOINT` (§0.2). Four tests hand-construct
`API_ENDPOINT` nodes with **bare-host** ids (`api.acme.example.com`) — a shape no producer emits.
Those tests encode the permissive pre-FORK-2 behaviour, so the **tests** are corrected and the
table is **not** widened.

Each is corrected by giving the node a real network identity, in this order of preference:

1. use the production id shape — a full URL (`http://api.acme.example.com/...`); or
2. where a test's subject is genuinely the node's *identity* rather than its URL, pass an explicit
   `scope_key` carrying the host identity, which §1.1 now gates on its own shape.

Each correction **must preserve what its test was testing.** These tests are about
`can_anchor_finding`, `find_paths` traversal and `upsert_node`'s in-scope stamping — not about
scope permissiveness. A correction that changes a test's subject, weakens an assertion, or deletes
a case is a PAUSE-DECISION, not a fix. 10.3's builder was **correct** to report rather than edit
these (10.3 §8.8); this brief is what authorizes the edits.

### 1.5 `graph.py` stays as it is

`graph.py:140`'s `scope_key or id` precedence is **unchanged**. §1.1 is implemented entirely inside
`scope_guard.py`, which must be told whether the string it received was a scope_key or an id. The
chokepoint keeps its one approved change from 10.3 (passing `node_type`) plus, at most, one
additional keyword argument carrying that distinction. No other `graph.py` behaviour changes.

---

## 2. Hard guardrails

1. **`src/kronos/manifest.py` zero-line diff.** A manifest signed before Brief #10 still verifies —
   prove it.
2. **Nothing under `cybergym/` is touched**, including `generate_scope_manifest.py` and
   `requirements.txt`. No manifest edited or re-signed. CyberGym's real patterns keep working **as
   signed**.
3. `graph.py` changes only as §1.5 permits. `_ALWAYS_IN_SCOPE_TYPES`,
   `_NO_IN_SCOPE_COLUMN_TYPES`, the prop allowlists and the `scope_key or id` precedence all stay
   exactly as they are.
4. **Fail-closed everywhere.** Unknown/empty/`None` `node_type` denies, with or without a
   scope_key. No permissive default anywhere in the dispatch.
5. **Excluded-first, default-DENY stays absolute**, and exclusions never gate on `node_type`.
6. Every case from Briefs #10, #10.1, #10.2 and #10.3 stays green — F1–F8, G1–G6, H1, H2's nine
   rows, H3's seven rows, the §5.5b port-blind address rows, and the CyberGym manifest table.
7. `lifecycle.py`, `schema.py`, `validate/`, `reconcile/`, `ingest/`, `budget/`, `cleanup/`,
   `events.py` all zero-diff.
8. Stdlib only. Deterministic. No LLM.
9. **The allow side is not widened anywhere.** §1.1 redirects which table governs a scope_key;
   §1.3 widens the **deny** side only. If any change in this brief makes a pattern authorize a
   target it does not authorize today, stop and report.
10. Do not weaken or delete any existing test. The five corrections §5.6(a) and §5.6(b) name are
    the **only** permitted test edits beyond §3's list; each must preserve its test's subject and
    assertion strength. §5.6(c)'s test must go green **unedited**. Any further test needing a
    change: **stop and report with the list.**
11. Re-pin the three `_SCOPE_GUARD_SHA256` constants (constant + comment only), guards intact.
12. **Stop and report rather than broaden.** Every escape in this series came from matching more
    than intended.

---

## 3. Permitted files

**Implementation:** `src/kronos/scope_guard.py` · `src/kronos/graph.py` (§1.5 limit only)

**Documentation:** `src/kronos/README_scope.md` · `DECISIONS.md`

**Tests — primary:** `tests/test_scope_guard.py`

**Tests — the §5.6 corrections, authorized by this brief and limited to the five cases §5.6(a)
and §5.6(b) name. `tests/test_query.py::test_find_paths_only_in_scope_excludes_out_of_scope_hop`
(§5.6(c)) must go green with NO edit:**
`tests/test_invariants.py` · `tests/test_query.py` · `tests/test_reconcile.py` ·
`tests/test_schema_graph.py`

**Hash pins (constant + comment only):** `tests/test_budget.py` · `tests/test_cleanup.py` ·
`tests/test_reconcile.py`

Any other file: **stop and report** with the file and the reason.

---

## 4. Design

1. **`scope_guard.py` learns the id/scope_key distinction.** `is_in_scope` takes a second required
   keyword argument stating whether the target string is an id or a scope_key. Required, no
   default, fail-closed on an unrecognised value — same discipline as `node_type` in 10.3 §1.1.
   The node-type shape-family gate is consulted **only** for an id.
2. **The exclusion path discards a URL pattern's path.** Inside `_matches`, the `"://"` branch, on
   the exclusion side only, reduces the pattern to its host/address identity before comparison
   instead of falling through to `_matches_url_pattern`. The allow side keeps its current
   literal path-aware route untouched.
3. **`NODE_TYPE_SHAPES` is re-derived under §1.2**, with per-row citations, `WEB_ENDPOINT` set to
   `frozenset()`, and `SECRET` re-derived from its id now that §1.1 has removed the scope_key
   justification for its current value.
4. `classify_target` stays pure and type-blind. `_effective_shape` keeps its narrowing-only
   contract.

---

## 5. Tests

**RED first, every one.** Each case below must be shown failing against the current head before
the fix lands, and the builder reports the RED output.

### 5.1 Finding A — path-bearing URL exclusions (RED first)

With `excluded = ['http://localhost:8091/internal/*']`, `in_scope = ['*']`, every row denies:

| target | expected | prose authority |
|---|---|---|
| `http://localhost:8091/internal/x` | deny | §1.3 (already passes; keep green) |
| `localhost:8091` | deny | §1.3 shape-blind |
| `http://localhost:8091/other` | deny | §1.3 path-blind |
| `localhost` | deny | §1.3 port-blind |
| `http://localhost:8091/` | deny | §1.3 path-blind |

Repeat for a second, non-localhost pattern (`https://api.acme.example.com/v1/*`) against its own
host/port/URL/dot-free identities, so the rule is not fitted to one host.

**Allow-side control, same patterns:** an allow pattern carrying a path keeps its current narrow,
path-aware behaviour. This is the test that proves §1.3's fix did not leak into the allow side.

### 5.2 §1.1 — scope_key gated on its own shape (RED first)

1. `CLOUD_RESOURCE` id `cr:acme-bucket` with `scope_key='api.acme.example.com'`, manifest
   `in_scope=['*.acme.example.com']` → **in scope**. (Denies today. Prose: §1.1.)
2. The same node with **no** scope_key → the id-shape family applies; `cr:acme-bucket` is
   `bucket_name`, permitted → in scope.
3. A `scope_key` whose own shape is not authorized by any pattern → **deny**. The scope_key is not
   a bypass.
4. An **excluded** scope_key denies, excluded-first, regardless of node type (§2.5).
5. Unknown/empty/`None` `node_type` **with** a valid in-scope scope_key → **deny** (§2.4
   fail-closed is not softened by §1.1).
6. The ARN-form scope_keys CyberGym actually uses (`arn:aws:s3:::kronos-cybergym-*`) stay in
   scope, as signed.

### 5.3 §1.2 — evidence-only families (RED first)

1. `WEB_ENDPOINT` with **any** target denies — `frozenset()` is unconditional. Cover a full URL, a
   `web:{method}:{url}` canonical key, and `web:1`.
2. A `WEB_ENDPOINT` carrying an in-scope **scope_key** is in scope via §1.1 — this is the
   documented route for a type with no id convention, and it is what makes the §1.4 reconcile
   correction work.
3. `IDENTITY`, `TECHNOLOGY`, `FINDING`, `PARAMETER` continue to deny unconditionally.
4. `SECRET`, re-derived, behaves per its reported citation; state the expectation in prose in the
   report before asserting it.
5. The finished table is reported with per-row citations, and a test asserts every `schema.py` node
   type is either present in the table or demonstrably bypassed by `graph.py` — no type may be
   silently absent.

### 5.4 The generated cross-product — rebuilt from prose

Same construction as 10.3 §5.4 (two declared lists, expectations **as data**, an undeclared cell
**fails** the test), with four mandatory corrections:

1. **Every cell's expectation is derived from this brief's or a predecessor's prose, and each cell
   carries a reference to the clause that determines it.** A cell no prose determines is a
   PAUSE-DECISION — report it; do not fill it in. This directly answers Finding B.
2. **Pattern shapes must include a path-bearing URL pattern** (both with and without an explicit
   port), exercised on **both** the allow and the exclusion side. 10.3's grid never matched against
   a path-bearing pattern at all, which is why it could not catch Finding A.
3. **Run the allow side per node type, for every node type in the table** — not one. (Finding C.)
   Add a third axis for the id/scope_key distinction from §1.1.
4. **Assert through the public API** (`scope_guard` / `ScopeGuard.is_in_scope`), never a private
   matcher. (Finding D.)

Report the total cell count and confirm none is undeclared.

### 5.5 Regression

Every case from Briefs #10, #10.1, #10.2 and #10.3; H2's nine rows and H3's seven rows in both
directions; the CyberGym real-manifest table, still passing **as signed**, with node types
attached; the three `_SCOPE_GUARD_SHA256` guards; a pre-Brief-#10 signed manifest still verifying.

**Report totals against these measured baselines:**

- `tests/`: **620 passed / 1 skipped** on `dcbdba9`. The six regressions must be gone, so the final
  figure is 620 + this brief's new cases, **0 failed**, 1 skipped.
- `cybergym/cloud/`: **17 passed**.

**Live:** CyberGym **X-score 3/3, exit 0**, at the PR head, on an unproxied host. If it drops,
report with the per-target type, the id/scope_key distinction and the verdict — **do not loosen §1
to recover the score.**

**Environment note:** the live suite requires `httpx2==2.13.1` (SPEC_BRIEF7.1), which pulls
`httpcore2==2.13.1` and `truststore==0.10.5`. These are installed in the session venv but are
recorded in **no** requirements file, because the only file that should carry them is
`cybergym/requirements.txt`, which guardrail §2.2 forbids touching. **The builder must not add
them anywhere.** Report the gap; it is a maintainer action.

### 5.6 The test corrections — five edits, three different remedies

The six failing tests do **not** all need editing, and they do not all need the same remedy.
Report each one under the heading it belongs to. Getting this split wrong is itself a
PAUSE-DECISION.

**(a) Four §1.4 id corrections** — bare-host `API_ENDPOINT` ids replaced per §1.4:

- `tests/test_invariants.py::test_invariant_out_of_scope_secret_cannot_anchor_finding`
- `tests/test_invariants.py::test_invariant_find_paths_returns_seeded_mobile_to_cloud_chain`
- `tests/test_query.py::test_find_paths_returns_seeded_mobile_to_cloud_chain`
- `tests/test_schema_graph.py::test_upsert_node_stamps_in_scope_via_scope_guard`

For each, report: the old id, the new id or scope_key, the prose clause authorizing it, and proof
the assertion is **no weaker** than before.

**(b) One §5.3.2 scope_key correction** — `WEB_ENDPOINT` now has an empty id family, so the node
needs a scope_key to carry its network identity:

- `tests/test_reconcile.py::test_web_endpoint_real_duplicate_merges_and_tombstones`

**(c) One test that must be fixed by the implementation, with NO edit:**

- `tests/test_query.py::test_find_paths_only_in_scope_excludes_out_of_scope_hop`

This one fails solely because `CLOUD_RESOURCE` `cr:acme-bucket` carries
`scope_key='api.acme.example.com'`, which §1.1 restores. **It must go green untouched.** If it
still fails after §1.1 lands, §1.1 is implemented wrongly — do not edit the test to compensate.

Its deliberately out-of-scope hop `api.evil.com` **stays out of scope** in every case. That node is
the test's control and must not be "fixed" in any of the three groups above.

Note the two seeded-chain tests have **two** independent causes each (a bare-host `API_ENDPOINT`
and a host-shaped `CLOUD_RESOURCE` scope_key). Only the first needs an edit; the second is
restored by §1.1.

---

## 6. Live-use gate — the closing conditions

FORK-2 is complete, and issue #2 may close, when **all** hold:

1. This PR is merged to `main` after independent reviewer diff approval.
2. Every case from Briefs #10, #10.1, #10.2, #10.3 and this brief is green, including §5.4's
   generated product with **zero undeclared cells**.
3. Live CyberGym X-score **3/3, exit 0, at the merge commit**, on an unproxied host.
4. `manifest.py` zero-line diff; a pre-Brief-#10 signed manifest still verifies.
5. Issue #2 closed **with a link to the merge commit**.
6. `README_scope.md` documents the node-type dispatch, the allow/deny asymmetry, the id/scope_key
   distinction (§1.1), the evidence-only table rule (§1.2), and that `CLOUD_RESOURCE` is the only
   type with free mid-token expansion.
7. The `httpx2` environment gap (§5.5) is closed by the maintainer, or explicitly accepted in
   writing as a known non-reproducible step.

Only then may KRONOS be pointed at a live client target or run in Beast mode, and only then does
**S3** start.

**§6 is the live-use gate. It is not the acceptance criteria. §8 is.** Condition 3 is measurable
only after merge and therefore can never gate acceptance; condition 7 is a maintainer action the
loop cannot perform.

---

## 7. FORKs

- **FORK-X —** the id/scope_key distinction is carried as a new required keyword argument on
  `is_in_scope` rather than inferred inside the guard. DEFAULT: explicit argument. A guard cannot
  tell an id from a scope_key by looking at the string; that is the whole lesson of H2.
- **FORK-Y —** `SECRET`'s family after §1.1 removes its scope_key justification. DEFAULT: re-derive
  from its id citation and report. If its real id shape (sha256-derived) matches no pattern family,
  `frozenset()` is the §1.2-consistent answer, since scope arrives via scope_key in every
  production path.
- **FORK-Z —** whether the exclusion side should discard a URL pattern's **query/fragment** as well
  as its path. DEFAULT: yes, by the same rule-6 reasoning; report if any existing case depends on
  the current behaviour.

Record each with its reason in `DECISIONS.md`.

---

## 8. Acceptance criteria

1. `is_in_scope` takes the §1.1 id/scope_key argument as a **required** kwarg; no call path omits
   it; an unrecognised value denies.
2. A `scope_key` is gated on its own shape, with no node-type family filter; the family filter
   still applies on the id path. §5.2's six rows pass.
3. Fail-closed is intact: unknown/empty/`None` `node_type` denies **even with** a valid in-scope
   scope_key.
4. `NODE_TYPE_SHAPES` is re-derived per §1.2 with a **per-row citation**; `WEB_ENDPOINT` is
   `frozenset()`; no row is assigned by analogy; no `schema.py` type is silently absent.
5. §1.3's path-bearing exclusion rows all deny (§5.1), **and** the allow-side control proves the
   allow path is unchanged.
6. §5.4's generated cross-product runs with **zero undeclared cells**; every cell cites the prose
   clause determining it; the product covers path-bearing URL patterns, runs the allow side per
   node type, includes the id/scope_key axis, and asserts through the public API. Cell count
   reported.
7. The six regressions are gone: `tests/` is **0 failed**, 1 skipped, at 620 + this brief's new
   cases. `cybergym/cloud/` is 17 passed.
8. Every Brief #10 / #10.1 / #10.2 / #10.3 case green — F1–F8, G1–G6, H1, H2's nine rows, H3's
   seven rows, §5.5b, the CyberGym table as signed.
9. `manifest.py` zero-diff; pre-#10 signed manifest verifies; **nothing under `cybergym/`
   touched**, including `requirements.txt`.
10. `graph.py` changed only as §1.5 permits; §2.7's untouched list confirmed zero-diff.
11. Only §3's files changed. Each of the five test corrections is reported per §5.6 with proof the
    assertion is no weaker, and §5.6(c)'s test passes **unedited**. Any test outside §3 needing a
    change was **reported, not edited**.
12. Live X-score **3/3 exit 0 at the PR head**, with the verbatim line and exit code, **or
    BLOCKED/INCOMPLETE naming the environment**. The `httpx2` gap is reported, not papered over.
13. FORK-X, FORK-Y and FORK-Z recorded with reasons; the completed §1.2 table reported with
    citations.
14. `README_scope.md` and `DECISIONS.md` carry §6's gate **verbatim** and the §1.1/§1.2/§1.3 rules.
    (10.3's criterion 11 failed because `DECISIONS.md` claimed to carry the gate and did not —
    verify both files by grep, not by assertion.)
15. PR left **open and unmerged**, and **not** marked ready for review.

---

## 9. Output expected back

1. The RED output for every §5.1/§5.2/§5.3 case, before the fix.
2. The completed §1.2 table with per-row citations.
3. The §5.4 cell count, the undeclared-cell count (must be 0), and any cell referred as a
   PAUSE-DECISION.
4. Suite totals against 620/1 and 17, and the verbatim X-SCORE line with exit code.
5. The §5.6 report, split into (a), (b) and (c), with §5.6(c) shown green unedited.
6. FORK-X/Y/Z dispositions.
7. Anything that required stopping, with the file and the reason.
