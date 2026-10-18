# SPEC_BRIEF10.5.md — Rule 5, address-shaped exclusions, and the §5.4 rebuild 10.4 owed

**Status:** APPROVED at GATE-1 (approved draft sha256 `450514c24af17c14cf564216a4d8af6a39fc695ca86c672e581f9518ac072a34`). Authored by the orchestrator (claude-opus-5) from the
independent review of PR #15 and the seq 18/19 research turns. No code may be written against it
until the maintainer approves it.

**Stage:** FORK-2 (issue #2). **Predecessor:** SPEC_BRIEF10.4 at PR #15 head `2a676a8`,
independently reviewed **FAIL — DO NOT MERGE** (§8: 12 PASS, 2 FAIL, 1 PARTIAL).
**On approval this lands at repo-root `SPEC_BRIEF10.5.md` on PR #15's existing branch**,
`claude/scope-key-dispatch-brief10-4`, so PR #15 becomes passing rather than being superseded.

**Measured baselines, re-measured at `2a676a8`, not carried forward:**

| Tree | `tests/` | `cybergym/cloud/` | Live X-score |
|---|---|---|---|
| `2a676a8` (PR #15 head) | 1068 passed, 0 failed, 1 skipped | 17 passed | `X-SCORE: 3/3 chains validated end-to-end`, exit 0 |
| `dcbdba9` (main) | 620 passed, 1 skipped | 17 passed | — |

---

## 0. Goal justification

**This section is now a standing requirement of every KRONOS brief.** It did not exist in 10.4,
and its absence is why that brief justified itself only against review findings. The three goals
and their precedence are recorded in `KRONOS_RESEARCH_RECORD.md` §1.

- **Primary — G2 (MORE EFFECTIVE).** `scope_guard` is the mechanism that makes autonomous
  execution safe inside explicitly authorized, signed scope. Every defect here is a defect in the
  precondition for autonomy. §1.2's address-shaped exclusion gap is the sharpest case: an operator
  who excludes `http://10.0.0.5/admin/*` today does **not** get `10.0.0.5` excluded.
- **Enabling — G1 (STRONGER).** §1.1's rule 5 is what lets the web and infrastructure domains —
  which the research record's own coverage table classes as **schema-only**, no ingestion, no
  validation — acquire ingesters later without re-litigating the shape table. When a producer
  appears, rule 1 supersedes rule 5 for that row automatically.
- **G3 — not advanced by this brief, and not weakened.** No validation gate, evidence arm or
  classification changes. Stated explicitly so the absence is recorded rather than assumed.
- **Precedence respected:** G3 constrains G1 and G2, and nothing here relaxes a gate or widens
  scope. §1.2 **narrows** (deny-side), and guardrail §9 forbids widening the allow side.

---

## 1. The decisions

### 1.1 Rule 5 — schema-derived families for types with no producer

**ORCHESTRATOR-DERIVED. READ THIS BEFORE APPROVING.** The maintainer ruled "add rule 5" but did
not specify its discriminator. The orchestrator's first framing — *"schema-complete with live
reconcile machinery retains its schema-derived family"* — **was wrong and is withdrawn**: that
test does not discriminate, because `reconcile/runner.py` consumes `WEB_ENDPOINT` (`:82`, `:268`),
`HOST` (`:94`, `:270`) and `SERVICE` (`:133`, `:274`) alike, so it would have swept `WEB_ENDPOINT`
back to a non-empty family and silently reversed the maintainer's PD-2/A′ ruling. The rule below
is derived from schema evidence instead. **GATE-1 may reject it; it is not maintainer-ruled.**

Add to §1.2 of SPEC_BRIEF10.4:

> **Rule 5.** When no production producer exists for a type (so rule 1 cannot be satisfied), the
> permitted family is derived from `schema.py`, and only from whether the schema gives that type a
> column carrying its **network identity**:
>
> - If the schema provides **no identity-bearing column other than `id`**, or only *qualifiers* on
>   an identity (a port, a protocol), then the schema forces the network identity into the id, and
>   the id's shape family applies.
> - If the schema provides **a column that carries the network identity** (a `url`, a `name`), the
>   id is **not** required to carry it. The family is `frozenset()`, and scope must arrive via a
>   `scope_key` under §1.1.
>
> Rule 5 is consulted **only** when rule 1 cannot be. The moment a producer exists for a row, rule
> 1 governs it and rule 5 no longer applies. Rules 3 and 4 still bind: no row by analogy, and a
> canonical/merge key is never evidence of id production.

Applied, with the evidence for each (`schema.py` `NODE_COLUMNS` :223-226, `NODE_PROPS_ALWAYS`
:165-168):

| Type | Columns beyond `id` | Identity lives in | Family | Rule |
|---|---|---|---|---|
| `HOST` | `source`, `merged_into` | **the id** | `{host, ip}` | 5 |
| `SERVICE` | `+ port`, `protocol` (qualifiers) | **the id** | `{host, ip, host_port, ip_port}` | 5 |
| `WEB_ENDPOINT` | `+ url`, `method` | the `url` column | `frozenset()` | 5 |
| `PARAMETER` | `+ name`, `param_type` | the `name` column | `frozenset()` | 5 |
| `API_ENDPOINT` | `+ url`, `method` | — | `{url}` | **1** (producer `parser.py:276`) |

`API_ENDPOINT` carries `url`/`method` columns too, yet keeps `{url}`, because a producer exists and
rule 1 outranks rule 5. That is the one case proving the two rules do not collide.

**`HOST` keeps `{host, ip}` — NOT 10.4's `{host, ip, host_port, ip_port}`.** `HOST` has no `port`
column, so nothing in the schema supports a port-bearing id for it; `SERVICE` is the type that
carries ports. This is a **narrowing** of 10.4's `HOST` row and is therefore permitted by
guardrail §9. If any Brief #10/#10.1/#10.2 case depends on a `host_port`-shaped `HOST` id, that is
a PAUSE-DECISION — report it, do not widen the row back.

Each row's citation must name the schema line, not a docstring and not a convention.

### 1.2 Exclusions are blind to shape for **address**-shaped targets too (F3)

**Normative, and it completes 10.3's H3 rather than extending it.**

§1.3 of 10.4 says an exclusion denies if **any** target identity matches the exclusion's extracted
**host/address** identity. The implementation covers name-shaped hosts only. Measured at
`2a676a8`:

| exclusion | target | shape | today | §1.3 requires |
|---|---|---|---|---|
| `http://10.0.0.5/admin/*` | `10.0.0.5` | `ip` | **allows** | denies |
| `http://10.0.0.5/admin/*` | `10.0.0.5:8443` | `ip_port` | **allows** | denies |
| `http://10.0.0.5*` | `10.0.0.5` | `ip` | **allows** | denies |
| `http://[2001:db8::1]:443/x/*` | `[2001:db8::1]:443` | `ip_port` | **allows** | denies |
| `http://localhost:8091/internal/*` | `localhost:8091` | `host_port` | denies | denies |

**The third row is the important one: it has no path at all.** So this is not a gap in 10.4's new
path-blind rule — **H3 was never satisfied for address shapes in the first place**, and it has been
latent since `dcbdba9`. 10.4's §5.1 table probes hostnames only, which is why neither the builder
nor the orchestrator's own verification caught it; both probed name-shaped hosts.

**Cause:** `_host_port_scheme` returns `(None, None, None)` for `ip` and `ip_port`, while
`_HOST_SHAPES_FOR_EXCLUSION` includes both — so every exclusion host-identity branch bails out for
address-shaped targets.

**The rule:** on the exclusion side, an address-shaped target yields its address (and port, where
present) as its identity, including the bracketed IPv6 forms, and is compared exactly as a
name-shaped host is. Port, scheme and path remain ignored. **The allow side does not change** —
CIDR and bare-IP allow patterns keep their existing `_matches_address_pattern` path untouched.

### 1.3 The §5.4 rebuild 10.4 ordered and did not get (F2)

10.4 §5.4 listed four mandatory corrections; one was made. `DECISIONS.md` states the grid was
*"extended, not replaced"*, and the only change between `d2ad51e` and `2a676a8` is two exclusion
rows. The remaining three are **normative here**:

1. **Every cell carries a prose-clause reference.** All 364 inherited cells, not only new ones.
   The 9-row `_B104_ID_SCOPE_KEY_AXIS` already carries a per-row `why` — that is the correct
   pattern; apply it to the whole grid. A cell no prose determines is a **PAUSE-DECISION**: report
   it, do not fill it in.
2. **Run the allow side per node type, for every type in the table.** `HOST` alone is not
   compliance.
3. **Assert through the public API.** The exclusion grid currently asserts
   `_matches(pattern, target, is_exclusion=True)`. The in-code justification — that the node-type
   gate makes public-API exclusion testing impossible — **does not hold**: `in_scope=['*']` with
   `target_kind='scope_key'` yields unconfounded exclusion semantics. Use it.

**One cell is already known to be prose-undetermined** and must be reported rather than guessed:
`_P4_BOTH_ENDS_GLOB` (`*.acme.com*`) is declared `False` against `_T1_HOST` (`api.acme.com`) on
**both** sides — a both-ends glob denying the exact host it names, including as an exclusion where
rule 6 says deny broad. It is predecessor scope and no prose in #10–#10.5 determines it.

### 1.4 The §6 gate must be byte-verbatim (criterion 14)

10.4's criterion 14 says to grep for the gate verbatim. Both copies paraphrase it: *"The PR is
merged"* for *"This PR is merged"*, *"`manifest.py` is zero-line diff"* for *"`manifest.py`
zero-line diff"*, *"Issue #2 is closed"* for *"Issue #2 closed"*, and items 2 and 3 drop the
brief's bold emphasis. `DECISIONS.md` additionally **labels** its block "verbatim" while not being
verbatim.

Both copies must be byte-identical to this brief's §6, and the check must be a real byte
comparison — not a presence grep. **A presence grep cannot test verbatim-ness; using one is how
10.4's criterion 14 was recorded as passing when it was not.**

---

## 2. Hard guardrails

1. **`src/kronos/manifest.py` zero-line diff.** A pre-Brief-#10 signed manifest still verifies —
   prove it.
2. **Nothing under `cybergym/` is touched**, including `requirements.txt`. The `httpx2` /
   `httpcore2` / `truststore` pins must **not** be added anywhere; report the gap (§5.5).
3. **`schema.py` is read-only evidence and stays zero-diff.** Rule 5 derives families *from* the
   schema; it never changes the schema to fit a family.
4. **`graph.py` zero-diff.** 10.4's `target_kind` threading is complete; nothing here needs it.
5. **Fail-closed everywhere.** Unknown/empty/`None` `node_type` denies, with or without a
   `scope_key`.
6. **Excluded-first, default-DENY stays absolute**, and exclusions never gate on `node_type`.
7. Every case from Briefs #10, #10.1, #10.2, #10.3 and #10.4 stays green.
8. `lifecycle.py`, `validate/`, `reconcile/`, `ingest/`, `budget/`, `cleanup/`, `events.py` all
   zero-diff.
9. **The allow side is not widened anywhere.** §1.2 widens the deny side; §1.1's `HOST` change
   narrows. Prove the allow side is unchanged by differential measurement, not by assertion.
10. Stdlib only. Deterministic. No LLM.
11. Do not weaken or delete any existing test. §5.6's control restoration is the only permitted
    edit outside `tests/test_scope_guard.py`. Any other test needing a change: **stop and report**.
12. Re-pin the three `_SCOPE_GUARD_SHA256` constants (constant + comment only) — `scope_guard.py`
    **does** change in this brief.
13. **Stop and report rather than broaden.** Every escape in this series came from matching more
    than intended.

---

## 3. Permitted files

**Implementation:** `src/kronos/scope_guard.py`

**Documentation:** `src/kronos/README_scope.md` · `DECISIONS.md`

**Tests:** `tests/test_scope_guard.py` · `tests/test_schema_graph.py` (§5.6's control only)

**Hash pins (constant + comment only):** `tests/test_budget.py` · `tests/test_cleanup.py` ·
`tests/test_reconcile.py`

Any other file — including `schema.py`, `graph.py`, `SPEC.md` and anything under `cybergym/` —
**stop and report** with the file and the reason.

---

## 4. Design

1. **`_host_port_scheme` learns address shapes.** It returns the address as the host identity for
   `ip` and `ip_port`, including bracketed and zone-indexed IPv6 and IPv4-mapped forms, so the
   exclusion host-identity branches stop bailing out. Allow-side address matching keeps its
   existing `_matches_address_pattern` route.
2. **`NODE_TYPE_SHAPES` is re-derived under rule 5**, with per-row citations naming `schema.py`
   lines. `HOST` narrows to `{host, ip}`.
3. **The §5.4 grid is rebuilt, not extended** — per-cell clause references, a node-type axis over
   the allow side, and public-API assertions on both sides.
4. `classify_target` stays pure and type-blind. `_effective_shape` keeps its narrowing-only
   contract.

---

## 5. Tests

**RED first, every one.** Each case must be shown failing at `2a676a8` before the fix lands, and
the builder reports the RED output.

### 5.1 §1.2 — address-shaped exclusion identities (RED first)

With `in_scope = ['*']`, every row denies:

| excluded | target | prose authority |
|---|---|---|
| `http://10.0.0.5/admin/*` | `10.0.0.5` | §1.2 shape-blind |
| `http://10.0.0.5/admin/*` | `10.0.0.5:8443` | §1.2 shape-blind + port-blind |
| `http://10.0.0.5*` | `10.0.0.5` | §1.2 — path-free, so H3 itself required this |
| `http://10.0.0.5:8443/x/*` | `10.0.0.5` | §1.2 port-blind |
| `http://[2001:db8::1]:443/x/*` | `[2001:db8::1]:443` | §1.2 bracketed IPv6 |
| `http://[2001:db8::1]/x/*` | `[2001:db8::1]` | §1.2 bracketed IPv6, no port |

Plus an IPv4-mapped and a zone-indexed form, since `_parse_bracketed_ip` already accepts both.

**Allow-side controls, same patterns:** a CIDR allow pattern and a bare-IP allow pattern keep their
current behaviour exactly. This is what proves §1.2 did not leak into the allow path.

### 5.2 §1.1 — rule 5 and the re-derived table (RED first)

1. `HOST` with a `host_port`-shaped id (`web-01:8080`) **denies** — `HOST` has no `port` column.
   (Passes today; must fail after the narrowing is wrong, so state the expectation from §1.1's
   prose and assert it.)
2. `HOST` with `host` and with `ip` ids in scope behaves per its family.
3. `SERVICE` with `host`, `ip`, `host_port`, `ip_port` ids behaves per its family.
4. `WEB_ENDPOINT` and `PARAMETER` deny for **any** id (`frozenset()`), and reach scope only via a
   `scope_key`.
5. `API_ENDPOINT` still uses `{url}` — rule 1 outranks rule 5.
6. Every `schema.py` node type is in the table or demonstrably bypassed by `graph.py` (keep 10.4's
   `test_b104_5_3_5`, extended to assert each row's rule number is recorded).

### 5.3 The §5.4 rebuild

Per §1.3: per-cell clause references across all cells; a node-type axis over the allow side
covering every type in the table; public-API assertions on both sides. Report the total cell
count, the undeclared-cell count (must be 0), and **every cell referred as a PAUSE-DECISION** —
including `_P4_BOTH_ENDS_GLOB` × `_T1_HOST`, which is already known to be undetermined.

### 5.4 §1.4 — the gate is byte-verbatim

A test extracts §6's block from `SPEC_BRIEF10.5.md` and byte-compares it against the blocks in
`README_scope.md` and `DECISIONS.md`. Byte comparison, not a presence grep.

### 5.5 Regression

Every case from Briefs #10 / #10.1 / #10.2 / #10.3 / #10.4. Report totals against **1068 passed /
0 failed / 1 skipped** in `tests/` and **17 passed** in `cybergym/cloud/` at `2a676a8`.

**Differential proof for guardrail §9 — required, not optional.** Enumerate the allow side across
the §5.4 pattern and target lists at `dcbdba9`, `2a676a8` and the new head, and show **zero**
allow-side differences. Show every exclusion-side difference is `False → True`. The reviewer of
PR #15 did exactly this (418 pairs, 0 allow differences; 42 exclusion changes, all deny-ward) and
it is the strongest evidence in the series — make it a standing test, not a one-off review step.

**Live:** CyberGym **X-score 3/3, exit 0** at the PR head on an unproxied host. If it drops, report
per-target type, id/scope_key, and verdict — **do not loosen §1 to recover the score.**

**Environment:** the live suite needs `httpx2==2.13.1`, `httpcore2==2.13.1`, `truststore==0.10.5`.
Installed in the verification venv, recorded in **no** requirements file, because the only correct
home is `cybergym/requirements.txt`, which guardrail §2.2 forbids. **Do not add them anywhere.**
Report the gap; it is a maintainer action and §6 condition 7.

### 5.6 F4 — restore the negative control

`tests/test_schema_graph.py::test_upsert_node_stamps_in_scope_via_scope_guard`'s control is
`api.evil.com`, a bare host. Since 10.4 it is denied by the `API_ENDPOINT` → `{url}` family filter
**before any pattern is consulted**, so the assertion would still pass with the pattern logic
entirely broken. Make the control a full URL on an out-of-scope host (`https://api.evil.com`),
restoring its discriminating power without changing the test's subject. Report the before/after
and why the assertion is now **stronger**, not merely different.

### 5.7 Documentation (F5, F6)

- `README_scope.md` documents that a **bucket-name `scope_key` no longer matches a bucket glob**
  (`_scope_key_shape` folds `bucket_name` → `host`). A real behaviour change for any future
  ingester setting a bucket-name scope_key; prose-authorized by §1.1's worked example, currently
  undocumented.
- `DECISIONS.md`'s totals are stale — they report `1067 passed, 1 failed`. Refresh to the measured
  figures.

---

## 6. Live-use gate — the closing conditions

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

---

## 7. FORKs

- **FORK-AA —** rule 5's discriminator. DEFAULT: identity-bearing columns, as §1.1 derives. The
  rejected alternative (live reconcile machinery) is recorded in §1.1 with the reason it fails.
- **FORK-AB —** `HOST` narrowing to `{host, ip}`. DEFAULT: narrow. If a predecessor case depends on
  a `host_port`-shaped `HOST` id, PAUSE-DECISION rather than widening back.
- **FORK-AC —** whether the allow side should also learn address identities from path-bearing URL
  patterns. DEFAULT: **no** — that would widen the allow side, which guardrail §9 forbids. Record
  as deliberately declined.

Record each with its reason in `DECISIONS.md`.

---

## 8. Acceptance criteria

1. Rule 5 is added to §1.2's rule set with its "only when rule 1 cannot be satisfied" precedence
   stated, and rules 3 and 4 still bind.
2. `NODE_TYPE_SHAPES` is re-derived with a **per-row citation naming a `schema.py` line or a
   producer call site**, and the rule number (1 or 5) recorded per row. No row cites a docstring,
   a convention, or another type.
3. `HOST` is `{host, ip}`; `SERVICE` is `{host, ip, host_port, ip_port}`; `WEB_ENDPOINT` and
   `PARAMETER` are `frozenset()`; `API_ENDPOINT` is `{url}` under rule 1.
4. §5.1's address-shaped exclusion rows **all deny**, bracketed IPv6 included, **and** the
   allow-side controls prove CIDR and bare-IP allow matching is unchanged.
5. §5.4's product: zero undeclared cells; **every** cell carries a prose-clause reference; the
   allow side runs per node type for every type in the table; both sides assert through the public
   API. Cell count and every PAUSE-DECISION cell reported.
6. The §6 gate is **byte-identical** in `README_scope.md` and `DECISIONS.md`, verified by byte
   comparison, not a presence grep.
7. `tests/` is **0 failed**, 1 skipped, at 1068 + this brief's new cases. `cybergym/cloud/` is 17
   passed.
8. Guardrail §9 proven by differential measurement: **zero** allow-side differences across
   `dcbdba9` / `2a676a8` / head; every exclusion-side difference is `False → True`.
9. Every Brief #10 / #10.1 / #10.2 / #10.3 / #10.4 case green.
10. `manifest.py` zero-diff; pre-#10 signed manifest verifies; **`schema.py`, `graph.py` and
    everything under `cybergym/` zero-diff**; §2.8's untouched list confirmed.
11. Only §3's files changed. §5.6's control restoration is reported with proof the assertion is
    **stronger**. Any test outside §3 needing a change was **reported, not edited**.
12. Live X-score **3/3 exit 0 at the PR head**, verbatim line and exit code, **or
    BLOCKED/INCOMPLETE naming the environment**. The `httpx2` gap reported, nothing added to any
    requirements file.
13. FORK-AA, FORK-AB, FORK-AC recorded with reasons; the completed table reported with citations.
14. `README_scope.md` carries §5.7's bucket-name-scope_key note; `DECISIONS.md` totals refreshed.
15. PR #15 left **open and unmerged**, and **not** marked ready for review.

---

## 9. Output expected back

1. The RED output for every §5.1 and §5.2 case, before the fix.
2. The completed table with per-row citations **and rule numbers**.
3. The §5.4 cell count, undeclared count (0), and every PAUSE-DECISION cell — `_P4` × `_T1`
   included.
4. The differential allow-side proof (§8.8) as numbers, not prose.
5. Suite totals against 1068/0/1 and 17, and the verbatim X-SCORE line with exit code.
6. The §5.6 before/after and why the control is stronger.
7. FORK-AA/AB/AC dispositions.
8. Anything that required stopping, with the file and the reason.
