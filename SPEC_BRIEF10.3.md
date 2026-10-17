# SPEC_BRIEF10.3.md — Node-type-aware scope dispatch, cross-shape exclusions, generated matrix

**Status:** build brief (stateless). **FORK-2's final piece.** Start from latest `main`, which must
contain the PR #12 merge (check `src/kronos/README_scope.md` exists). New branch, open a PR,
**do NOT merge**.
**Autonomy:** Conservative. This brief changes the signature of the scope chokepoint — the one
interface frozen across ten briefs. Escalate both FORKs (§7) and **stop and report** on anything
not covered. A wrong guess here is a client-facing incident.
**Method: TDD, RED first.** H2 and H3 are measured defects; write them failing first.
**Role separation:** researcher wrote this; builder implements on a branch and never merges;
reviewer reads the diff against §8.

**On completion of this brief, FORK-2 is complete and issue #2 may close** — with a link to the
merge commit, per §6. Until then KRONOS stays on CyberGym and **S3 does not start.**

---

## 0. Why this brief exists

Three rounds on PR #12 closed F1–F8, G1–G6 and H1. Two defects remain, and they share a root
cause that is **my own method**, not the code.

### 0.1 H2 — every single-label hostname gets bucket semantics

`classify_target` step 9 maps any dot-free token to `bucket_name`, which gets free glob expansion.
Measured:

| `in_scope` | target | observed | required |
|---|---|---|---|
| `localhost*` | `localhostevil` | **IN SCOPE** | DENY |
| `localhost*` | `localhost-evil` | **IN SCOPE** | DENY |

This is not about `localhost`. Internal estates are full of single-label hostnames — `jenkins`,
`intranet`, `dc01` — so `jenkins*` authorizes `jenkins-prod` and `jenkinsfoo`. **S3 is infra
ingestion**, which is exactly where those arrive.

**It is not fixable from the string alone.** `kronos-cybergym-*` → `kronos-cybergym-general-secrets`
*requires* mid-token expansion (correct for a bucket); `localhost*` → `localhostevil` must not
(wrong for a hostname). Both targets are dot-free. The distinguishing signal is the **node type**,
which exists at `upsert_node(type, id, props, scope_key=None)` and is discarded before
`is_in_scope(scope_key or id)` is called at `graph.py:140`.

### 0.2 H3 — exclusions do not cross shape boundaries

With `excluded = ['http://localhost:8091*']`:

| target | observed | required |
|---|---|---|
| `localhost:8091` | **IN SCOPE** | DENY |
| `localhost` | **IN SCOPE** | DENY |

Brief #10 §1.1 rule 6 says an exclusion covers the named host on "every port, scheme, path and
representation". After #10.2 it is blind to port, scheme and path *within the URL shape*, but does
not reach the bare `host` / `host:port` forms of the same host. **Deny-side under-match.**

### 0.3 The method defect — why this keeps happening

Brief #10 §5 tested leading globs and missed trailing ones → G1–G6. Brief #10.2 §2 tested only
URL-form exclusion targets → H3. Each time the rule was stated correctly in prose and the matrix
enumerated only some shapes, and **the implementation tracked the matrix, not the prose.**

So §5.4 of this brief replaces hand-picked examples with a **generated cross-product**: every
pattern shape × every target shape, each cell asserted against a declared expectation table. Adding
a shape later forces a decision instead of silently inheriting a default. This is the part of the
brief most likely to prevent a fourth discovery, and it is not optional.

---

## 1. The decisions

### 1.1 `node_type` becomes a required argument (H2)

`ScopeGuard.is_in_scope` takes `node_type` as a **required keyword argument**. There is no default
and no permissive fallback, so no call site can forget it — the compiler enforces what a convention
would not.

`graph.py` passes the `type` it already has. This is the one approved change to the frozen scope
chokepoint; it is additive at the call site and mandatory at the boundary.

**Fail-closed is the governing rule:** an unrecognised, empty or `None` `node_type` **denies**,
unconditionally, before any pattern is consulted. Never fall back to `bucket_name`, never fall back
to "most permissive", never infer the family from the target string when the type is unknown.

### 1.2 Node type → shape family (the builder must complete and justify this table)

Enumerate **every** node type in `schema.py` and assign its permitted shape family. Starting
point — the builder verifies each against how that type's ids are actually produced, and reports
the finished table:

| node type | permitted target shapes | notes |
|---|---|---|
| `HOST` | `host`, `ip`, `host_port`, `ip_port` | boundary rule applies; dot-free is a **hostname**, not a bucket |
| `SERVICE` | `host_port`, `ip_port`, `host`, `ip` | same |
| `WEB_ENDPOINT` | `url` | |
| `API_ENDPOINT` | `url` | |
| `CLOUD_RESOURCE` | `bucket_name`, `arn` | the **only** types that get free mid-token glob expansion |
| `MOBILE_APP` | `bundle_id` | |
| `MOBILE_COMPONENT` | `bundle_id` | |
| `PARAMETER` | opaque | never glob-authorized — see §1.4 |
| `SECRET`, `IDENTITY`, `TECHNOLOGY`, `FINDING` | report what their ids actually are | if a type is never scope-gated in practice, say so with evidence rather than assigning a family by guess |
| `ENGAGEMENT` | n/a | `graph.py`'s `_ALWAYS_IN_SCOPE_TYPES` bypasses the guard; unchanged |
| `EVIDENCE` | n/a | no `in_scope` column; unchanged |

**Free mid-token glob expansion is restricted to `CLOUD_RESOURCE`.** That is what makes
`kronos-cybergym-*` keep working while `localhost*` stops over-matching — the two cases H2 could
not separate from the string alone.

### 1.3 Exclusions are representation-blind across shapes (H3)

For any target, compute **all** of its identities — bare host, `host:port`, the URL form, the
address form. An exclusion denies if **any** target identity matches the exclusion's extracted
host/address identity, regardless of which shape either side was written in, and regardless of port,
scheme or path (Brief #10 §1.1 rule 6).

This is strictly broader than the allow side and that asymmetry is the specification. **Exclusions
are evaluated before and independently of `node_type`:** a type mismatch must never cause an
exclusion to be skipped. An exclusion with an unknown node type still denies.

### 1.4 `PARAMETER` is never glob-authorized

A `PARAMETER` id is an opaque name, not a network identifier. It inherits scope from its parent
endpoint and must never be matched against a host, URL, bucket or bundle-id glob. Report how it is
currently gated and make the behaviour explicit.

---

## 2. Hard guardrails

1. **`src/kronos/manifest.py` zero-line diff.** Signed-manifest format unchanged; a manifest signed
   before Brief #10 still verifies — prove it.
2. **Nothing under `cybergym/` is touched**, including `generate_scope_manifest.py`. No manifest
   edited or re-signed. CyberGym's real patterns must keep working **as signed**.
3. `graph.py` changes **only** to pass `node_type` through to `is_in_scope`. No other behaviour
   change: `_ALWAYS_IN_SCOPE_TYPES`, `_NO_IN_SCOPE_COLUMN_TYPES`, the prop allowlists and the
   `scope_key or id` precedence all stay exactly as they are.
4. **Fail-closed everywhere.** Unknown/empty/`None` `node_type` → deny. No permissive default
   anywhere in the dispatch.
5. **Excluded-first, default-DENY stays absolute**, and exclusions never gate on `node_type`.
6. Every case from Briefs #10, #10.1 and #10.2 stays green — F1–F8, G1–G6, H1, the §5.5b
   port-blind address rows, and the CyberGym manifest table.
7. `lifecycle.py`, `schema.py`, `validate/`, `reconcile/`, `ingest/`, `budget/`, `cleanup/`,
   `events.py` all zero-diff.
8. Stdlib only. Deterministic. No LLM.
9. Do not weaken or delete any existing test. **If a test outside §3 must change to accommodate the
   new required argument, stop and report with the list** — do not edit it unilaterally. (A test
   that drives scope through `upsert_node` should need no change; one that calls `is_in_scope`
   directly will.)
10. Re-pin the three `_SCOPE_GUARD_SHA256` constants (constant + comment only), guards intact.
11. **Stop and report rather than broaden.** Every escape in this series came from matching more
    than intended.

---

## 3. Permitted files

`src/kronos/scope_guard.py` · `src/kronos/graph.py` (§2.3 limit only) ·
`tests/test_scope_guard.py` · `src/kronos/README_scope.md` · `DECISIONS.md` · and the three
hash-pin constants in `tests/test_budget.py`, `tests/test_cleanup.py`, `tests/test_reconcile.py`.

Any other file: **stop and report** with the file and the reason.

---

## 4. Design

- `is_in_scope(target, *, node_type)` — required kwarg; unknown → deny.
- A `NODE_TYPE_SHAPES` mapping (§1.2) owned by `scope_guard.py`, not `graph.py`: the guard owns
  scope policy, the graph only reports what kind of node it is holding.
- `classify_target` keeps its shape detection, but step 9's dot-free fallback is **gated by the node
  type**: dot-free is `bucket_name` only for `CLOUD_RESOURCE`, and a `host` for `HOST`/`SERVICE`.
- One exclusion path computing all target identities (§1.3), independent of `node_type`.
- The module-level spec-named `scope_guard(target, manifest)` helper: see FORK-V.

---

## 5. Tests

### 5.1 H2 (RED first)

| node_type | in_scope | target | expected |
|---|---|---|---|
| `HOST` | `localhost*` | `localhostevil` | **DENY** |
| `HOST` | `localhost*` | `localhost-evil` | **DENY** |
| `HOST` | `localhost*` | `localhost` | ALLOW |
| `HOST` | `localhost*` | `localhost:8091` | ALLOW |
| `HOST` | `jenkins*` | `jenkins-prod` | **DENY** |
| `HOST` | `jenkins*` | `jenkins` | ALLOW |
| `CLOUD_RESOURCE` | `kronos-cybergym-*` | `kronos-cybergym-general-secrets` | ALLOW (lock) |
| `CLOUD_RESOURCE` | `kronos-cybergym-*` | `kronos-cybergym-x.attacker.net` | **DENY** (G6 lock) |
| `HOST` | `kronos-cybergym-*` | `kronos-cybergym-general-secrets` | **DENY** — bucket glob, host type |

### 5.2 H3 (RED first) — `excluded = ['http://localhost:8091*']`, `in_scope = ['*']`

| node_type | target | expected |
|---|---|---|
| `WEB_ENDPOINT` | `http://localhost:8091/x` | **DENY** |
| `WEB_ENDPOINT` | `http://localhost:9091/x` | **DENY** (lock, #10.2) |
| `SERVICE` | `localhost:8091` | **DENY** (H3) |
| `HOST` | `localhost` | **DENY** (H3) |
| `SERVICE` | `localhost:4566` | **DENY** — port-blind |
| `HOST` | (unknown/`None` type) `localhost` | **DENY** — exclusions ignore type |

Also the reverse direction: `excluded = ['localhost']` must deny
`http://localhost:8091/x` for `WEB_ENDPOINT`.

### 5.3 Fail-closed

`node_type` of `None`, `""`, `"NOT_A_TYPE"`, and a correctly-spelled type that is not in
`NODE_TYPE_SHAPES` — each **denies** every target in §5.1's ALLOW rows, and still **denies**
excluded targets. Assert the deny comes from the type gate, not from a failed allow.

### 5.4 The generated cross-product (replaces hand-picked matrices)

Build the test from two declared lists — pattern shapes × target shapes — and assert every cell
against a declared expectation table, **as data, not computed from `scope_guard.py`**.

- Pattern shapes: bare hostname, `*.`-leading glob, trailing-glob hostname, both-ends glob, bare IP,
  CIDR, `host:port`, URL without port, URL with port, URL trailing glob, bucket glob, ARN glob,
  bundle-id glob.
- Target shapes: `host`, `host_port`, `ip`, `ip_port`, bracketed IPv6 with port, `url` standard
  port, `url` nonstandard port, `url` with userinfo, dot-free single-label host, lookalike
  `<prefix>.attacker.net`, mid-label `<prefix>-evil.net`, `bucket_name`, `arn`, `bundle_id`.
- Run the product for the allow side **per node type**, and for the exclusion side **once**,
  type-independent.
- **A cell with no declared expectation must fail the test**, not default. That property is the
  whole point: report the total cell count and confirm none is undeclared.

### 5.5 Regression

Every Brief #10 / #10.1 / #10.2 case; the CyberGym real-manifest table (now with node types
attached, and still passing as signed); the `_SCOPE_GUARD_SHA256` guards; a pre-Brief-#10 signed
manifest still verifying. Report totals against the post-#10.2 baseline (**620 passed / 1 skipped**
in `tests/`, **17 passed** in `cybergym/cloud/`).

**Live:** CyberGym **X-score 3/3, exit 0** at the PR head on an unproxied host. This is the real
check that `node_type` threading did not narrow anything: every node the range creates now goes
through the type gate. If it drops, report with the per-target type and verdict — **do not loosen
§1 to recover the score.**

---

## 6. Live-use gate — the closing conditions

FORK-2 is complete, and issue #2 may close, when **all** hold:

1. This PR is merged to `main` after independent reviewer diff approval.
2. Every case from Briefs #10, #10.1, #10.2 and this brief is green, including §5.4's generated
   product with zero undeclared cells.
3. Live CyberGym X-score 3/3, exit 0, at the merge commit on an unproxied host.
4. `manifest.py` zero-line diff; a pre-Brief-#10 signed manifest still verifies.
5. Issue #2 closed **with a link to the merge commit**.
6. `README_scope.md` documents the node-type dispatch, the allow/deny asymmetry, and that
   `CLOUD_RESOURCE` is the only type with free mid-token expansion.

Only then may KRONOS be pointed at a live client target or run in Beast mode, and only then does
**S3** start.

---

## 7. FORKs

**FORK-V — the module-level `scope_guard(target, manifest)` helper.** (1) Add a required
`node_type` parameter, matching `is_in_scope`. (2) Keep the two-argument signature for SPEC.md
fidelity and have it deny any target whose shape is ambiguous without a type.
→ **DEFAULT: (1).** Fail-closed by construction beats a second path with its own rules — a
permissive-by-omission helper is how H2 happened. If SPEC.md's wording makes (1) a documentation
conflict, report it rather than choosing silently.

**FORK-W — `SECRET` / `IDENTITY` / `TECHNOLOGY` / `FINDING` shape families.** (1) Determine from the
code what their ids actually are and assign families accordingly. (2) Deny them all, on the grounds
that they are not network targets.
→ **DEFAULT: (1), with evidence.** But if the evidence shows a type is never a scope-gated action
target, (2) is the safer answer for that type — say which and why. Do not assign a family by
analogy.

---

## 8. Acceptance criteria

1. `node_type` is a **required** kwarg on `is_in_scope`; no call path omits it; unknown/empty/`None`
   denies (§5.3).
2. H2's rows deny; `CLOUD_RESOURCE` bucket globs still work; a bucket glob under `HOST` denies.
3. H3's rows deny in both directions; exclusions never gate on `node_type`.
4. §5.4's generated cross-product runs with **zero undeclared cells**; cell count reported.
5. Every Brief #10 / #10.1 / #10.2 case green — F1–F8, G1–G6, H1, §5.5b, the CyberGym table.
6. `manifest.py` zero-diff; pre-#10 signed manifest verifies; nothing under `cybergym/` touched.
7. `graph.py` changed only to pass `node_type`; §2.3's untouched list confirmed.
8. Only §3's files changed. Any test outside §3 needing a change was **reported, not edited**.
9. Live X-score 3/3 exit 0, or **BLOCKED / INCOMPLETE** naming the environment.
10. FORK-V and FORK-W recorded with reasons; §1.2's completed node-type table reported.
11. `README_scope.md` and `DECISIONS.md` carry §6's gate verbatim and the dispatch rules.
12. PR left **open and unmerged**.

---

## 9. Output expected back

- Branch + PR link (not merged); commit SHA; diff summary; confirmation only §3's files changed.
- H2 and H3 as RED-before / GREEN-after tables.
- The completed §1.2 node-type → shape-family table **as implemented**, with the evidence for
  `SECRET`/`IDENTITY`/`TECHNOLOGY`/`FINDING`/`PARAMETER`.
- §5.4's cell count, and confirmation that an undeclared cell fails rather than defaults.
- The fail-closed proof (§5.3), naming the tests.
- Any test outside §3 that would have needed editing — listed, not edited.
- Full totals before/after; `git status --porcelain`; the literal `X-SCORE:` line and exit code.
- Whether §6's six closing conditions are met, item by item.
