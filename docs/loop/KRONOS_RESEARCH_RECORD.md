# KRONOS — Research & Decision Record

**Last updated:** 2026-10-16 (v5 — supersedes v4)

**Changes in v5:** Beast-mode action classes **revised** — Class C is unattended where the signed
manifest enumerates class + named target + time window (decision 10, §7.3); origin-direct arm and
variant-generation questions **resolved** (§4.10c); **S6.5 dependency assessment** added; archive
verification log added (§4.8a) recording that the 2026-10-16 customized-Cairn archive is
byte-identical to the 2026-10-15 one, so **no new upstream features have been assessed**.
**Withdrawn in v4 and still withdrawn:** the blanket rejection of authorized WAF/firewall bypass
testing — see the record correction in §4.10(c).
**Researcher/architect/reviewer:** Claude Opus 5 (`claude-opus-5`) · **Builder:** Claude Sonnet 5 in Claude Code
**Repo:** `github.com/Aks2812/KRONOS` — `main` @ `3d89223`

Human-readable record of KRONOS architecture research and decisions. A *record*, not a spec;
build specs live in `SPEC_BRIEF*.md` at the repo root.

---

## 1. The three goals

Every reference assessment, architecture decision, and brief in this project is justified against
these and only these. If an idea cannot be tied to one of them, it is not adopted.

> ### G1 — STRONGER
> Build meaningful **cross-domain** capability, so KRONOS can connect evidence across **web,
> infrastructure, mobile, API, and cloud**.
>
> ### G2 — MORE EFFECTIVE
> Increase **autonomous planning and execution** within **explicitly authorized scope and signed
> engagement limits**.
>
> ### G3 — FEWER FALSE POSITIVES
> Make findings **validation-gated, evidence-backed, and appropriately classified**, with
> **abstention** when the evidence is insufficient.

**How the goals interact, and which wins when they conflict.** G3 constrains G1 and G2: a new
domain that cannot produce two-armed evidence does not ship (G1 yields to G3), and autonomy never
widens scope or relaxes a validation gate (G2 yields to G3 and to the signed manifest). G1 before
G2 in sequencing: breadth first, then autonomy over that breadth — an autonomous planner over
half-built domains generates work the framework cannot validate. This ordering is why web and infra
precede the agent layer (§6).

**Verdict vocabulary used throughout.** **Adopt** = take substantially as-is. **Adapt** = take the
idea, change the mechanism to fit KRONOS. **Defer** = good, blocked on a prerequisite or premature.
**Reject** = assessed and deliberately declined, with reasons. **Investigate** = promising,
insufficient evidence to decide. **Not assessed** = present in the reference, never examined —
recorded as such so absence is never mistaken for rejection.

---

## 2. Implementation state (`main` @ `3d89223`)

| Brief | Content | Status |
|---|---|---|
| #1 | Graph core + validation lifecycle (Kùzu, scope guard, query interface) | merged |
| #2 | Mobile static ingestion (MobSF + apktool/jadx + extractors) | merged (PR #3) |
| #0.5 | CyberGym seeded range (APK + API + SigV4-gated LocalStack S3) | merged (PR #4) |
| #3 | Secret validation `extracted→validated→reachable` | merged (PR #5) — first earned live X-score **3/3** |
| #4 + #4.1 | Reconciliation/dedup; inert tombstones; FINDING merge deferred behind a guard | merged (PR #6) |
| #5 | Per-engagement budget governance (fail-closed ledger) | merged (PR #7) |
| #6 | Cleanup/teardown registry (LIFO, budget-exempt, crash-safe) | merged (PR #8) |
| #7 | CyberGym denial fidelity (fixture-only; `src/kronos/` zero-diff) | **PR #9 — all 10 §5 criteria PASS.** `src/kronos/` zero-line diff confirmed; 7 files inside the §2 allowlist; live on Kali: 5/5 denial rows match, 13/13 selftest checks, **X-score 3/3** exit 0 (§7.6b). **Merge blocked only on SPEC_BRIEF7.1** — one undeclared dep (`httpx2==2.13.1`) introduced by this PR |
| #7.1 | Declare `httpx2==2.13.1` in `cybergym/requirements.txt` (amends PR #9, pre-merge, same branch) | built `bdec3b4`, reviewed, one-line diff verified |

**PR #9 MERGED to `main` as `ac1167b`** (verified: `bdec3b4` is an ancestor of `origin/main`, and
the `httpx2==2.13.1` pin is present on main). All 10 §5 criteria passed. The CyberGym range is now
a **verified** measurement instrument.

| #8 (S1) | Negative-control validation — two-armed proof in `src/kronos/validate/` | **MERGED** as `d9355a5` (PR #10). All 12 §6 criteria passed, live-verified at `46fbff4` (§7.7b) |
| #8.1 | Differential fixes + allowlist carve-out (amended PR #10 pre-merge) | **MERGED** with PR #10; Fix #1's `b.success or c.success` confirmed live on `main` |
| #9 (S2) | Ingestion contract, canonical keys, owned event stream | **MERGED** as `71ac247` (PR #11), live re-verified at `4a2da51` (§7.9) |
| #10 (FORK-2) | Shape-aware `scope_guard` matcher — **hard pre-live blocker** | brief rev 3 committed `915dec8`; **PR #12 open, reviewed, NOT merged** — closes F1–F8 but leaks on trailing globs (§7.12) |
| #10.1 | Trailing-glob boundary rule (amends PR #12, pre-merge) | built `d0e5232`, reviewed — G1–G6 closed, live X-score 3/3; two carve-outs found (§7.13) |
| #10.2 | Explicit-port URL patterns must obey the boundary rule (H1) | brief ready (`SPEC_BRIEF10.2.md`, sha256 `4eb25f1a…`), not yet committed |
| #10 + #10.1 + #10.2 | Shape-aware matcher, boundary rule, structural port comparison | **MERGED** as `3d89223` (PR #12). F1–F8, G1–G6, H1 all closed and reviewer-verified. `scope_guard.py` now 656 lines, up from 73 |
| #10.3 | **H2 + H3 — node-type-aware scope dispatch, cross-shape exclusions, generated matrix** | **PR #13 open at `d2ad51e`, reviewed, MERGE-APPROVED** (§7.15). Completes FORK-2 on merge |

### 7.15 PR #13 review (Brief #10.3) — FORK-2 complete, 2026-10-17

Head `d2ad51e611927525780b9069db2bc16b0a7209b2`, off `main` @ `3d89223`. **Every claim verified
independently from the diff, not accepted from the report.**

**The instruction I cared most about held.** `tests/test_schema_graph.py`,
`test_invariants.py` and `test_query.py` are **zero-diff** — the six out-of-allowlist tests were
*reported, not edited*. Their shared cause (fixtures using a bare hostname where a URL or bucket id
belongs) is a genuine finding about the fixtures, surfaced rather than silently patched away.

**Guardrails: ten paths zero-diff** — `manifest.py`, `lifecycle.py`, `schema.py`, `validate/`,
`reconcile/`, `ingest/`, `events.py`, `budget/`, `cleanup/`, all of `cybergym/`. `graph.py` is
**literally one line**: `is_in_scope(scope_key or id, node_type=type)`.

**Fail-closed verified by direct call.** `node_type` of `None`, `""`, `"NOT_A_TYPE"`,
`"CLOUD_RESOURCES"`, and the mis-cased `"host"`/`"Host"` each **deny** an otherwise-allowed row,
while `"HOST"` allows it — so the gate requires an exact known type and never guesses from the
string. And `is_in_scope("localhost")` raises `TypeError`: the required kwarg is genuinely
enforced, so no call site can omit it. That is the single property H2 was caused by lacking.

**H2 closed:** `localhost*` now denies `localhostevil` and `localhost-evil` while allowing
`localhost` and `localhost:8091`; `jenkins*` denies `jenkins-prod`. **The type separation works
both ways** — `kronos-cybergym-*` allows the bucket under `CLOUD_RESOURCE` and **denies the same
string under `HOST`**, which is exactly the distinction unavailable from the string alone.

**H3 closed:** a URL-shaped exclusion now reaches `localhost:8091` (`SERVICE`) and `localhost`
(`HOST`), is port-blind to `localhost:4566`, works in reverse, and **still denies under
`NOT_A_TYPE` and `None`** — exclusions are type-independent as specified.

**CyberGym preserved:** all 9 real-manifest targets still allow with their true node types
attached, and the lookalike/userinfo rows still deny. This **corroborates the reported live
X-score 3/3** rather than merely trusting it: node-type threading is the mechanism by which the
score could have broken, and the targets it gates all still pass.

**§5.4's generated matrix is real.** 13 patterns × 14 targets × 2 grids = **364 declared cells**,
and the expectations are dicts indexed directly, so an undeclared cell raises `KeyError` and
**fails** rather than defaulting — the property I said mattered more than the cell count. It also
**earned its keep immediately**: on its first run it caught a second H3 gap (dot-free exclusion
targets) that my hand-written table had missed. The method fix worked on its first outing.

Tests 620 → **1023**. FORK choices: V(1) required kwarg; W(2) for `IDENTITY`/`TECHNOLOGY`/`FINDING`
— empty families, on evidence of zero production `upsert_node` calls, rather than a family assigned
by analogy. `SECRET` → `{"host"}` with the `scope_key=bundle_id` evidence. `PARAMETER` → empty.

**Minor process note, not a defect:** the builder's precondition "`SPEC_BRIEF10.3.md` on main" was
not met — the brief was committed to the **branch** (`dcbdba9`) and the build proceeded instead of
stopping. The risk a precondition guards against is empirically absent: the branch copy is
**byte-identical** to the authored draft (`75a666d8…`), and the brief merges with the PR as every
earlier one did.

**Coverage boundary worth carrying forward:** §5.4's allow grid is generated for `HOST` only
(plus a type-independent exclusion grid); other types are covered by §5.1's targeted cases. A full
12-type product would be ~4,368 cells. Reasonable, but when a later brief adds a node type, the
grid should be extended rather than assumed to cover it.

**Merge verdict: APPROVED.** On merge plus closing issue #2 with the merge-commit link, **FORK-2 is
complete**, the §6 live-use gate is satisfied, and **S3 is unblocked.**

### 7.14 PR #12 after Brief #10.2 — H1 closed, H3 found, 2026-10-17

Head `96fc293470efef610e8fd1986068b7ea72c6af4b`. Verified independently.

**Guardrails: nine modules zero-diff** — `manifest.py`, `graph.py`, `lifecycle.py`, `schema.py`,
`validate/`, `reconcile/`, `ingest/`, `events.py`, all of `cybergym/`. Only §4's permitted files
changed.

**The instruction that mattered held.** `tests/test_negative_controls.py`,
`test_validate_candidates.py` and `test_validate_runner.py` are **zero-diff** — the nine
explicit-port tests passed unmodified, confirming the H1 carve-out was unnecessary as hypothesised.
No fixture was adjusted to make a fix look right.

**H1 fully closed, 12/12 verified**, including all four leaks (userinfo, lookalike suffix, port
`80915`, mid-token) plus port/scheme/host mismatches, with the chain-1 path and query/fragment
forms still allowed. **G1–G6 still DENY. CyberGym's real manifest: 9/9 unchanged.** Robustness on
malformed port patterns: 4/4, no raises, no over-allows. Live X-score 3/3 exit 0, selftest 15/15.

**The builder also found a defect my brief's table caught but I had not predicted** — explicit-port
*exclusions* were not port-blind (`excluded=['http://localhost:8091*']` did not deny
`http://localhost:9091/x`). Fixed. That is §2's exclusion table earning its place.

**NEW — H3: exclusions do not cross shape boundaries.** My probe added two rows the brief's table
omitted. With `excluded = ['http://localhost:8091*']`:

| target | observed | required by Brief #10 §1.1 rule 6 |
|---|---|---|
| `localhost:8091` | **IN SCOPE** | DENY |
| `localhost` | **IN SCOPE** | DENY |

Rule 6 says an exclusion covers the named host on "every port, scheme, path and representation".
A URL-shaped exclusion is now blind to port, scheme and path *within the URL shape*, but does not
reach the bare `host`/`host:port` representations of the same host. Deny-side under-match — the
class I have treated as most serious.

**This is my brief's gap, for the third time.** §5 of Brief #10 missed trailing globs (→ G1–G6);
§2 of #10.2 tested only URL-form exclusion targets (→ H3). The recurring failure is specifying a
rule in prose ("every representation") and then enumerating only some shapes in the matrix. **#10.3
must derive its exclusion matrix from the cross-product of pattern shape × target shape**, not from
hand-picked examples.

**Not exposed before #10.3 lands.** H3 needs an engagement whose manifest carries a URL-shaped
exclusion with an explicit port; CyberGym's manifest has `"excluded": []`, and KRONOS cannot leave
CyberGym while FORK-2 is incomplete. Over-broad exclusion failures also cost missed testing, not
unsafe testing — unlike an allow-side leak.

**Merge verdict: MERGE PR #12.** It closes F1–F8, G1–G6 and H1, is strictly better than `main`, and
a fourth amendment cycle on one branch buys nothing when H2 already forces #10.3. **FORK-2 stays
incomplete**: issue #2 open, live-use gate unmet, KRONOS on CyberGym, S3 blocked until #10.3 closes
H2 **and** H3.

### 7.12 PR #12 review (FORK-2) — eight findings closed, one new leak found, 2026-10-16

Head `fa6285fc19cb453ced10a544fef05e00aa8b1dff`, one commit, 7 files, +1247/-33.

**Verified correct.** `manifest.py` **zero-line diff**; 475 → 551 tests; F1–F8 each demonstrated
RED-before/GREEN-after; §8.2 answered honestly as *not safely decidable* from the target string
(fix moved pattern-side); §8.4 found and closed a real IPv4-mapped bypass; §8.6 confirmed
`urlsplit().hostname` matches client behaviour.

**The three out-of-allowlist test edits are legitimate.** `test_budget.py`, `test_cleanup.py` and
`test_reconcile.py` hash-pin `scope_guard.py`'s bytes — guards placed by *earlier* briefs to prove
they left FORK-2 alone. This brief is chartered to end that streak, so re-pinning to the new hash
preserves the guard going forward rather than deleting it. Verified the new pin
(`affcf9df…`) matches the committed bytes exactly. Disclosed, not hidden. Accepted.

**NEW LEAK — trailing-glob patterns still escape to lookalike hosts.** Probed the branch head
directly:

| # | `in_scope` | target | PR #12 |
|---|---|---|---|
| G1 | `api.acme.com*` | `api.acme.com.attacker.net` | **IN SCOPE** |
| G2 | `api.acme.com*` | `api.acme.com-evil.net` | **IN SCOPE** |
| G3 | `localhost*` | `localhost.attacker.net` | **IN SCOPE** |
| G4 | `127.0.0.1*` | `127.0.0.1.attacker.net` | **IN SCOPE** |
| G5 | `http://localhost*` | `http://localhost.attacker.net/x` | **IN SCOPE** |
| G6 | `kronos-cybergym-*` | `kronos-cybergym-x.attacker.net` | **IN SCOPE** |

`api.acme.com*` also admits `:22` and `:3389`, while the bare `api.acme.com` correctly denies them.
This is issue #2's class 1 surviving in the pattern shape most likely to be hand-written — and
**SPEC_BRIEF10's §5 matrix never covered a trailing glob, so the gap is in my brief as much as the
code.**

**The live gate would not have caught it.** Ran PR #12's matcher against CyberGym's real signed
`in_scope` list (`com.kronos.cybergym.*`, `localhost*`, `127.0.0.1*`, `http://localhost*`,
`http://127.0.0.1*`, `kronos-cybergym-*`, `arn:aws:s3:::kronos-cybergym-*`): **all nine range
targets pass**, so X-score would have held at 3/3. The leak sits inside the code path the range
depends on. → Brief #10.1 §5.3 makes the range's own manifest a permanent tripwire instead of a
blind spot.

**Brief #10.1's resolution.** A trailing `*` on a host-shaped pattern expands only at a **delimiter
boundary** (`:`, `/`, end-of-string), never across a `.` or mid-label. Bucket/ARN-shaped targets
keep free glob expansion, because `kronos-cybergym-*` → `kronos-cybergym-general-secrets` is
mid-label and must work — so the boundary rule is selected by the **target's** shape, which is the
§8.1 escalation PR #12 folded into the `host` catch-all instead.

**Port semantics, decided explicitly (§1.2).** A trailing `*` after a complete host means *that
host, any port, any path*; a bare host entry stays standard-port-only. Option A over Option B
because B denies `localhost:8091` and `127.0.0.1:4566`, taking **X-score to 0/3** and requiring the
range manifest to be edited and re-signed — which §3 forbids. A is a real widening, but an
**operator-chosen** one: you get all ports by typing `*`, never by accident, and the boundary rule
keeps it to one host.

**Merge verdict: PR #12 does NOT merge until #10.1 lands.** KRONOS stays on CyberGym; S3 does not
start.

### 7.13 PR #12 after Brief #10.1 — G1–G6 closed, two carve-outs re-open the class, 2026-10-17

Head `d0e5232ddb45a61789d619b839e540dc5c5f0e96`. Guardrails clean: `manifest.py`, `graph.py`,
`lifecycle.py` and all of `cybergym/` zero-diff; only §3's permitted files changed; 551 → 591
tests; live **X-score 3/3 exit 0** on Kali. **G1–G6 independently re-verified DENY on the new
head.** The boundary rule works.

But report item 9 disclosed two carve-outs made mid-build to keep 12 pre-existing tests green, and
both re-open the same escape class in narrower form.

**H1 — explicit-port URL patterns kept on the old literal-match path.** With
`in_scope = ['http://localhost:8091*']`:

| target | result |
|---|---|
| `http://localhost:8091@evil.net/x` | **IN SCOPE** — real host is `evil.net` |
| `http://localhost:8091.attacker.net/x` | **IN SCOPE** |
| `http://localhost:80915/x` | **IN SCOPE** — digit-extended port |
| `http://localhost:8091evil.net/x` | **IN SCOPE** |

The userinfo form is the one Brief #10 §5.6/§8.6 explicitly pinned for other shapes, re-opened for
this one. **Scope of impact:** triggered only by a `http://host:port*` pattern. CyberGym's manifest
uses `http://localhost*` with no explicit port, which correctly denies all four — verified — so the
range and X-score are unaffected. Exclusions still override. Fix looks straightforward: route
explicit-port URL patterns through the boundary rule. `/` is already a legal boundary, so the 12
tests that drove the carve-out may well pass under it — a hypothesis for the builder to check, not
an assertion.

**H2 — `classify_target` step 9 maps every dot-free token to `bucket_name`.** Documented reasoning:
"every lookalike G1–G6 close introduces its new label via a literal `.`". Coherent but incomplete,
because it means **every single-label hostname gets bucket semantics and free glob expansion**:

| in_scope | target | result |
|---|---|---|
| `localhost*` | `localhostevil` | **IN SCOPE** |
| `localhost*` | `localhost-evil` | **IN SCOPE** |

This is not really about `localhost`. Internal estates are full of single-label hostnames —
`jenkins`, `intranet`, `dc01` — so `jenkins*` would authorize `jenkins-prod` and `jenkinsfoo`. **S3
is infra ingestion**, which is exactly where those targets arrive.

**H2 is not fixable inside the current allowlist, and that is the real finding.**
`kronos-cybergym-*` → `kronos-cybergym-general-secrets` *requires* mid-token expansion, while
`localhost*` → `localhostevil` must not — and both targets are dot-free. The distinguishing signal
is not in the string: it is the **node type**, which exists at `upsert_node(type, id, …)` and is
discarded before `is_in_scope` sees it. Closing H2 properly means passing a shape hint or node type
into the guard, which touches `graph.py` — outside §3. So this escalates rather than defaults; it is
the same family as §8.2's honest "not safely decidable."

**Verdict.** PR #12 is strictly better than `main` and should merge once H1 is closed, but
**FORK-2 is not complete** while H2 stands: issue #2 stays **open**, the §6 live-use gate stays
**unmet**, KRONOS stays on CyberGym, and **H2 must close before S3** — the stage whose targets it
affects.

### 7.9 PR #11 review (Brief #9 / S2) — 2026-10-16

Head `4a2da514a3882f82fd3255deb80969ca7bd1719a`, one commit, 13 files, +1329/-26.

**Guardrails verified by `git diff --stat`, not report:** `scope_guard.py`, `lifecycle.py`,
`graph.py`, `manifest.py` and all of `cybergym/` zero-diff. FORK-2 still open and still gating S3.
`schema.py` changed **only** as §4.0 specified — `merged_into` on the three tables plus the three
`NODE_COLUMNS` entries; the `NODE_PROPS_FORBIDDEN` line appears in the diff as hunk *context* only,
so the column stays writable solely by the reconcile path. All five FORKs took DEFAULT.

**The chokepoint holds.** `git grep` across `src/kronos/` and `cybergym/` finds real
`upsert_node`/`upsert_edge` calls under `ingest/` only at `ingest/__init__.py:104,108` — that is
`apply_upserts` itself, and `apply_plan` delegates to it rather than writing. The mechanical guard
exempts exactly one file (`__init__.py`) and carries the `assert scanned > 0` non-vacuity check.
No direct graph writes anywhere in `cybergym/`.

**Judgment call 1 — two mobile entry points: benign, and my constraint caused it.** `cybergym/` was
off-limits in §2 and depends on the legacy bare-list return, so the builder added
`ingest_mobile_static_plan` alongside `ingest_mobile_static` instead of changing the legacy
signature. Both still funnel through `apply_upserts`, so the single-writer property is intact; the
cost is duplicated surface, not a bypass. Accept as transitional — collapse to one entry point in
the brief where `cybergym/` becomes editable.

**Judgment call 2 — raw ids instead of canonical keys as parent keys: the builder found a real
inconsistency in MY brief.** §4.2/§4.3 specified the *parent's canonical key* as the compound-key
component, while §5 required parents to merge before children. Those are mutually redundant:
`canonical_key_for_host` is a pure function of the host id's text, so two genuine host duplicates
yield the same key regardless of merge state — services would therefore group correctly with no
host merge at all, making §5 vacuous by construction. The observation is **correct and mine to
own**.

Its *reasoning direction* was backwards: "the literal wording makes the ordering rule untestable"
is an argument for deleting a redundant test, not for changing the design to keep it. The design it
landed on is nonetheless sound, so I accept it rather than demanding a rewrite:
- Raw-id parent keys can never mis-merge (same raw host id + port + protocol *is* the same service).
- The failure mode under a broken ordering is a **missed** merge, never a wrong one — conservative,
  consistent with guardrail 7.
- **Consequence to carry forward:** the §5 ordering rule is now **load-bearing rather than
  redundant**. A silent ordering regression would leave duplicate nodes live, which degrades **G1**
  (a path through a duplicate can be missed) even though it manufactures no false finding. The
  ordering test must never be deleted.

**The ordering test is well-built.** Two HOST duplicates differing only in case (so
`canonical_key_for_host` groups them while their raw ids stay textually distinct), each exposing a
443/tcp SERVICE. It drives `_group_services`/`_merge_type` directly *before* any HOST merge and
asserts zero merges resulted, with a failure message stating the test must fail under reverse
order. The builder also reported reverting to the canonical-key design and confirming the assertion
flips — the same inversion discipline Brief #8.1 §3 required.

**RESOLVED — pinned independent re-run PASSED at `4a2da51`.** Clean tree before any run, Kali,
unproxied. `tests/` **475 passed / 1 skipped**, `cybergym/cloud/` **17 passed**, **15/15 selftest
checks**, **`X-SCORE: 3/3` exit 0**. Teardown clean (only the unrelated MobSF container and
pre-existing volumes); `git status --porcelain` empty at detached HEAD and after returning to main.

### PR #11 — REVIEWER APPROVAL FOR MERGE

All twelve §9 criteria met at `4a2da514a3882f82fd3255deb80969ca7bd1719a`. **S2 complete.** Ingestion
now has a formal contract with a single graph writer, the three compound/normalized canonical keys
are wired and exercised on genuine duplicates, and the engagement owns an append-only event stream.

**Carried forward from this review:**
1. The §5 ordering rule is **load-bearing**, not redundant (see judgment call 2). Its test must
   never be deleted.
2. Two mobile entry points collapse to one in whichever brief makes `cybergym/` editable.

### 7.10 FORK-2 scoped empirically — `scope_guard` gaps measured, not inferred (2026-10-16)

`main` @ `71ac247` (S2 merged). Read `scope_guard.py` in full and **probed the real
`ScopeGuard`/`_matches` with crafted targets** rather than reasoning about it. Seven findings, four
of them new relative to GitHub issue #2.

**Deny-side bypasses — NEW, and the serious class.** Issue #2 frames the problem as allow-side
over-matching. The worse direction is the deny side *under*-matching, which makes an explicitly
excluded host reachable:

| # | excluded pattern | target | result |
|---|---|---|---|
| F1 | `10.0.0.5/32` | `https://10.0.0.5/admin` | **IN SCOPE** |
| F2 | `10.0.0.5` | `https://10.0.0.5/admin` | **IN SCOPE** |
| F3 | `2001:db8::1/128` | `[2001:db8::1]:443` | **IN SCOPE** |

Cause: the CIDR branch tries `ip_address()` on the target and on `_strip_port_suffix(target)`;
neither parses for a URL or a bracketed IPv6 literal, so it falls through to `fnmatch` on the raw
string, which cannot match. The exclusion silently does not apply.

**Allow-side over-matching — issue #2's two classes, confirmed:**

| # | in_scope pattern | target | result |
|---|---|---|---|
| F4 | `*acme.com*` | `https://evil.net/?next=acme.com/x` | **IN SCOPE** (class 1) |
| F5 | `com.acme.*` | `com.acme.evil.attacker.net` | **IN SCOPE** (class 2 — bundle-id glob authorizes a hostname) |

**Functional denials — NEW, and they block S3 onward:**

| # | in_scope pattern | target | result |
|---|---|---|---|
| F6 | `*.acme.com` | `https://api.acme.com/v1/users` | denied → **every WEB_ENDPOINT/API_ENDPOINT URL node is out of scope** |
| F7 | `*.acme.com` | `api.acme.com:8443` | denied → **every hostname:port SERVICE/HOST node is out of scope** |

F7 also exposes an inconsistency: `10.0.5.10:443` **is** allowed by `10.0.5.0/24`, because
port-stripping exists only inside the CIDR branch and never on the hostname path. IPs with ports
work; hostnames with ports do not.

**The causal link that makes this one brief, not two.** F6/F7 *cause* F4: an operator who cannot
get web endpoints or `host:port` services in scope will write `*acme.com*` to make the engagement
run, and that glob is matchable by an attacker-controlled string. **The safety gap is downstream of
the usability gap**, so fixing shape-awareness closes both.

**Sequencing is now a hard dependency, not a preference.** F7 means S3 (infra ingestion) would emit
`host:port` nodes that `scope_guard` denies universally, so infra validation could never run —
and a "fix" by loosening globs walks straight into F4. **FORK-2 must precede S3.**

**Binding constraint, from issue #2's recorded decision — I would have got this wrong from
memory.** The resolution is **option (c)**: dispatch on the *target's* apparent shape (bare
IP/CIDR, URL, bare hostname/bundle-id), extended to URL-vs-hostname, **with no change to the signed
manifest's on-disk schema** — already-signed manifests must keep working. Option (b), typed-prefix
scope entries, was **rejected** for requiring a manifest migration. So the fix is target-side only;
the flat untyped pattern list stays.

**Process risk:** **issue #2 is CLOSED** even though the work has not been done, and it is the
tracker for a hard pre-live prerequisite. Reopen it, or the gate is invisible to anyone reading the
issue list.

**Superseded — earlier recommendation, now settled by the evidence above:** FORK-2 first.

### 7.11 FORK-2 brief drafted (`SPEC_BRIEF10.md`) + issue #2 reopened — 2026-10-16

Issue #2 **reopened** and the §7.10 findings posted to it as a comment, so the pre-live gate is
visible to anyone reading the issue list rather than buried in this record.

`SPEC_BRIEF10.md` is TDD/RED-first as issue #2 requires: the §5 matrix **is** the specification,
and each of F1–F7 must be shown failing before the fix. Honours the recorded decision — option (c)
target-side shape dispatch, **`manifest.py` zero-line diff** so already-signed manifests keep
verifying, typed-prefix entries off the table.

Design notes: two pure helpers, `classify_target` (shape taxonomy) and `target_identities` (the
equivalent representations a pattern may legitimately match), with `_matches` comparing like to
like. Guardrail 3 is the heart of it — **exclusions are evaluated against every equivalent
representation**, which is what closes F1–F3. Guardrail 5 forbids the tempting shortcut of solving
this via `scope_key` at the call sites (`graph.py:140` passes `scope_key or id`): that is the
forget-to-filter trap and SPEC_BRIEF9 guardrail 4 already bars ingesters from deciding scope.

§5.5.2 carries the §7.9 lesson forward: a test must prove a deny came from the **exclusion**, not
from a failed allow. Probe F in §7.10 passed for exactly that wrong reason before the matrix
existed.

**Four uncertainties flagged rather than guessed (§8), because this brief governs an authorization
boundary:**
1. **§8.1** — I verified the single `ScopeGuard` call site but did *not* audit every caller that
   supplies a `scope_key`, so the full set of target strings reaching the matcher is unknown. The
   builder must enumerate and report them.
2. **§8.2 — the weakest point.** `com.acme.mobile` vs `com.acme.evil.attacker.net` may not be
   safely decidable from the string alone; a public-suffix check would help but adds a dependency
   that guardrail 6 forbids. A documented limitation with a denied default is acceptable; a
   heuristic that authorizes a hostname is not.
3. **§8.3** — that `*.acme.com` is *meant* to authorize that host's services and endpoints is my
   inference from how S3/S5 will emit ids, not a recorded decision. If wrong, fixing F6/F7 is a
   scope *widening* and must be escalated.
4. **§8.4** — IPv4-mapped (`::ffff:10.0.0.5`), zone indices and compressed/expanded IPv6
   equivalence are unprobed; a one-way exclusion there would be an F1-class bypass.

**§6 live-use gate, now recorded in both the brief and issue #2:** five conditions — merged after
diff review, every §5 case green, live X-score 3/3 at the merge commit on an unproxied host,
`manifest.py` zero-diff, and issue #2 closed *with a link to the merge commit*. Until all five
hold, KRONOS stays confined to CyberGym and **S3 does not start**.

**`scope_guard.py`'s six-brief zero-diff streak (#4 through #9) ends here, by design.** S3 is infra ingestion, the
first stage where real hostnames and CIDR shapes arrive; building it against a scope matcher that
cannot reason about shapes means re-testing all of S3 afterward. FORK-2 also remains the hard gate
on any live-target or Beast-mode use.

**Superseded note — one pinned live re-run (now done):** The live `X-SCORE: 3/3` was produced by the
*build* session on Kali, so builder and live verifier were the same session, and the report does not
state the run happened at the final commit `4a2da51` on a clean tree. Every prior live gate was
verified independently at a pinned SHA; relaxing that because the builder happened to be on the
right machine would weaken the standard for no reason. One short re-run (selftest + X-score, pinned)
closes it.

### 7.7 PR #10 review (Brief #8 / S1) — 2026-10-16

Reviewed the real diff against `origin/main` `4ef4f8e`. Head `561cf2b`, 14 files,
1369 insertions.

**Guardrails all hold.** `scope_guard.py` zero-line, `lifecycle.py` untouched, `cybergym/cloud/*`
untouched — verified by `git diff --stat`, not by report.

**The §3.1 invariant is real and it bites.** Enforced in `ValidationOutcome.__post_init__` on a
frozen dataclass, so no caller anywhere can construct `live=True` without `discriminated=True` and
`classification == "live_discriminated"`. Evidence it is load-bearing rather than decorative: it
*forced* six mock updates in `tests/test_budget.py` and `tests/test_reconcile.py` (files outside
the allowlist's "may change" list but not in its "must not" list — a gap in my §2). Those six
diffs are one line each, add only the two new fields, and weaken no assertion. Accepted.

`controls.py` is clean: stdlib only, no circular import (`types.py` imports it, not the reverse),
`self_request_malformed` correctly prioritized over every other classification, and
`derive_negative_control` forces a per-position character change rather than trusting the hash to
differ, with a fail-closed guard for degenerate shapes. Test growth 140 → **306** is exhaustive
parametrization (5×5×5 = 125 cloud combinations + HTTP), not padding.

**Two defects found, same family — the code claims more than it checked:**

1. **Cloud `live_discriminated` never consults arm C.** `if a.success: if b.success: →
   indiscriminate; else → live_discriminated` — so (A success, B denied, **C success**) yields a
   positive claim *while a control arm succeeded*, with a `detail` string asserting "both controls
   were rejected", which is false there. Violates §3.4 as written and guardrail 3. **Can produce a
   false positive** — the one thing this brief exists to prevent.
2. **Cloud has no both-transport-error branch.** HTTP returns `inconclusive`; cloud falls through
   to `not_live` ("canonical arm did not succeed"). An unreachable endpoint is recorded as a claim
   about the *credential*. False negative, violates guardrail 4 (abstain rather than guess).
   `_all_cloud_arm_combinations()` never sets `transport_error`, so this case is **wholly
   untested**.

**Why the 125-combination test missed both:** it asserts only `not (live and not discriminated)`
plus the label on a live result. Defect 1's bad cell returns `live=True` **with**
`discriminated=True` — invariant satisfied, classification wrong. An exhaustive test that cannot
fail on a wrong answer is a coverage illusion. → Brief #8.1 §3 requires an
expected-classification table, written as data rather than recomputed from the implementation, and
a confirmation that inverting the fix makes it fail.

**My error, correctly refused.** Brief #8 §5.1.8 told the builder to edit
`cybergym/cloud/test_denial_matrix.py` while §2 forbade `cybergym/cloud/*`. It stopped and
reported instead of picking one. Brief #8.1 §4 carves out that one file (a test about the range,
not range behaviour) and keeps the rest of `cybergym/cloud/` forbidden.

**Merge verdict: not yet.** Defect 1 can manufacture exactly the false positive S1 was built to
eliminate, so it must not land. Fixes are a handful of lines in a file already in the allowlist,
same branch, pre-merge.

#### 7.7a Brief #8.1 amendment reviewed — all four fixes verified, 2026-10-16

PR #10 head `46fbff4444d7af1f8c2546b5ac6ed27f0ea82133`. One commit, three files, +225/-2 — exactly
the authorized set. **Seven guardrails confirmed zero-diff** by `git diff --stat`, not report:
`scope_guard.py`, `lifecycle.py`, `sigv4_proxy.py`, `sigv4_verify.py`, `known_secrets.py`,
`ground_truth.yaml`, `requirements.txt`.

- **Fix #1 ✓** `if b.success or c.success` → `indiscriminate_target`. The false `detail` string is
  corrected to "at least one control also succeeded", which now matches what was checked.
- **Fix #2 ✓** cloud dual-transport-error branch added ahead of the success checks →
  `inconclusive`, `discriminated=False`.
- **Fix #3 ✓** 125 **literal** rows, written as data, not computed from `controls.py`.
  Spot-audited several cells against §3.4 independently: the Fix-#1 cell
  `(None, "AccessDenied", None)` → `indiscriminate_target`, the
  `("AccessDenied","SignatureDoesNotMatch","InvalidAccessKeyId")` →
  `authenticated_not_authorized` rule, and `self_request_malformed` pre-empting
  `indiscriminate_target` — all faithful.
  **The inversion check is independently corroborated, not merely claimed:** reverting Fix #1 can
  only break cells where B is denied *and* C succeeds; B has exactly three denial codes that are
  not pre-empted by `self_request_malformed`, so **exactly 3 rows** must fail. The builder reported
  3. Arithmetic matches, so the acceptance check genuinely ran.
- **Fix #4 ✓** `assert scanned > 0` placed *before* the offenders assert, so a broken path fails
  loudly rather than passing vacuously. The non-M1 header
  `"AWS4-HMAC-SHA256 totally-not-even-the-right-shape"` has no `Credential=`, so `_CASE_M1_RE`
  cannot match; asserts 403 `AccessDenied`, pinning the §3.1a scope claim against a future widening.

Counts: `tests/` 306 → **433** passed / 1 skipped (+127 = 125 table rows + 2 direct tests,
arithmetically consistent); `cybergym/cloud/` 16 → **17**.

**One low-priority item, and it is my spec's gap, not a builder deviation.** Brief #8.1 §2
specified the dual-transport-error case only, so (A transport_error, B reachable) still falls to
`not_live` — a claim about the *credential* when the canonical arm never reached the target.
Behaviourally identical today (live=False, no advance, no edge); only the recorded label differs.
→ reporting-fidelity refinement for a later brief, **not** a merge gate.

**Merge verdict: APPROVED pending the live §5.3 run only.** Everything hermetically checkable is
checked. The remaining gate is Brief #8 §5.3 on an unproxied host: the `/health` abstention check
against the real range, plus X-score 3/3.

#### 7.7b Live verification PASSED at `46fbff4` — S1 COMPLETE, 2026-10-16

Run on local Kali, unproxied, SHA exact. Hermetic baseline reproduced from a fresh venv:
`tests/` **433 passed / 1 skipped**, `cybergym/cloud/` **17 passed**. All three images built.
Brief #7's five denial rows still correct. **15/15 selftest checks** (13 from Brief #7 + 2 new
negative-control checks). **`X-SCORE: 3/3`, exit code 0**, all three chains reachable. Teardown
clean, `git status --porcelain` empty throughout.

**The two results that matter:**

1. **The false positive is closed on a real target, not just a stub.** The live `/health` arm
   returned `classification="indiscriminate_target"` with detail *"negative control also succeeded
   — target does not discriminate"*. Pre-S1, that same endpoint certified any garbage secret as
   live. This is the headline FP of §0 of Brief #8, demonstrated closed against the running range.
2. **No false negative was introduced while tightening.** X-score held at **3/3** even though
   validation is now strictly stricter — the genuine fixture credential still classifies
   `live_discriminated` ("canonical succeeded, both controls rejected"), and the over-privilege
   distinction still holds (the general credential does not reach the admin-secrets bucket; the
   over-privileged one does). A drop to 2/3 would have meant the differential rejecting a chain
   that genuinely validates; it did not happen.

- **SPEC_BRIEF8 §5.3 (live negative-control differential): PASS**
- **SPEC_BRIEF8 §6.4 (live X-score 3/3): PASS**

### PR #10 — REVIEWER APPROVAL FOR MERGE

All twelve §6 criteria met across PR #10 + Brief #8.1, verified at
`46fbff4444d7af1f8c2546b5ac6ed27f0ea82133`. **S1 is complete**: KRONOS now makes no positive
validation claim without its counterfactual, and abstains rather than guessing.

**Carried forward, deliberately not blocking:** the asymmetric transport-error labelling
(A unreachable, B reachable → `not_live` rather than `inconclusive`) — a reporting-fidelity
refinement, my spec's gap, behaviourally inert today.

**Next: S2** — ingestion contract, canonical keys for `WEB_ENDPOINT`/`PARAMETER`/`SERVICE`, and the
owned event stream. **FORK-2 (shape-aware scope matcher, GitHub #2) must land at or before S3** —
still the hard blocker for live targets and Beast mode.

### 7.8 S2 brief drafted (`SPEC_BRIEF9.md`) — 2026-10-16

Three source findings shaped it:

1. **`WEB_ENDPOINT`, `PARAMETER` and `SERVICE` have no `merged_into` column** (only `HOST`,
   `API_ENDPOINT`, `MOBILE_APP`, `SECRET`, `FINDING` do). Reconciliation tombstones by writing
   `merged_into`, so canonical keys for those three would compute and **never merge** — Brief #4's
   no-op-proof defect, reintroduced. The schema addition is therefore inside S2 (FORK-P), with
   `NODE_PROPS_FORBIDDEN` unchanged so only the reconcile path can write it.
2. **The ingestion contract already exists implicitly**: `ingest_mobile_static` returns
   `list[NodeUpsert | EdgeUpsert]` — a declarative plan, no graph handle. S2 formalizes that shape
   rather than inventing one, and requires conformance by *adaptation*: if the mobile ingester
   needs restructuring to fit, the contract is wrong and the builder stops.
3. **No event stream exists** under `src/kronos/` (`git grep -i event` → one unrelated hit).

Design calls worth noting: **no path templating for `WEB_ENDPOINT`** (FORK-N) — `/blog/post-1` and
`/blog/post-2` are distinct pages, unlike `/users/123` as an API route, so templating would merge
real attack surface and lose findings. **`PARAMETER` and `SERVICE` take compound keys** including
the parent's, with `None` propagating from an unreconcilable parent (FORK-O) — a flat parameter key
would merge `?id=` across unrelated endpoints. **Parents merge before children** and child keys use
survivor ids (§5), asserted by a test that fails under the reverse order. The **event stream is
JSONL on disk, not a graph table** (FORK-Q), and is explicitly *not* load-bearing: an unwritable
stream warns rather than failing the run — the opposite of the budget ledger, deliberately.

Standing gate restated in the brief itself: **FORK-2 required before S3 and before any
live-target or Beast-mode use**; `scope_guard.py` keeps a zero-line diff in S2, so S2 does not
discharge it.

140 passed / 1 pre-existing skip.

### Coverage against G1 — verified in source

| Domain | Schema | Ingestion | Validation | Reality |
|---|---|---|---|---|
| **Mobile** | `MOBILE_APP`, `MOBILE_COMPONENT` | **Yes** (`ingest/mobile/`) | feeds secrets onward | **real** |
| **API** | `API_ENDPOINT` | partial — only via the mobile parser | **Yes** (`validate/http_validator.py`) | **real, mobile-sourced** |
| **Cloud** | `CLOUD_RESOURCE`, `IDENTITY` | n/a | **Yes** (`validate/cloud_validator.py`) | **real** |
| **Web** | `WEB_ENDPOINT`, `PARAMETER` | **No** | **No** | **schema-only** |
| **Infra** | `HOST`, `SERVICE` | **No** | **No** | **schema-only** |

**G1 is 3/5 domains real, 5/5 modelled.** Nothing scans a web app or a network today. Closing
this is the current priority (§6).

---

## 3. Locked architectural decisions

1. **No jailbreak / prompt-laundering layer.** Rejected. Routing a restricted action through plain
   code *specifically to avoid a safety control* is the same restricted action with extra steps.
2. **Findings graph in Kùzu**, one embedded DB per engagement. The LLM queries the graph; it never
   ingests raw tool dumps. *(G1, G3)*
3. **Validation lifecycle is the FP moat.** `SECRET`: extracted→validated→reachable→dead.
   `FINDING`: hypothesis→reachable→exploited→reported. Confidence *derived* from status. *(G3)*
4. **Signed Ed25519 manifest is the only authorization object**, excluded-first default-deny. *(G2)*
5. **Single chokepoints in code:** `scope_guard`, `advance_secret_status`, `BudgetLedger.charge`,
   `CleanupRegistry`. `merged_into` is in `NODE_PROPS_FORBIDDEN`. *(G2, G3)*
6. **Static-first for mobile**; dynamic (Frida) pre-wired, not built.
7. **Human review gate before merge is mandatory.**
8. **FORK-2 (open, GitHub #2):** one untyped `fnmatch` glob for FQDN/CIDR/URL/bundle-id, so a loose
   wildcard can cross identifier boundaries. **Hard blocker for live targets and for Beast mode.**
9. **Reviewer LLM may downgrade, never upgrade** (§5). *(G3)*
10. **Beast mode: autonomous within signed authorization.** *(G2)* — **REVISED 2026-10-16,
    supersedes the earlier "Class C keeps a per-action human trigger in both modes".* Beast mode runs
    autonomously, without per-action approval, for any action class **explicitly enumerated in the
    signed manifest for a named target within a named time window**, until the operator stops it.
    Two refinements kept as engineering constraints: (a) a generic `mode: beast` is **not**
    authorization for anything — the manifest must enumerate the specific class, target and window,
    so breadth is never inherited; (b) irreversible/destructive classes remain separately enumerated
    (`destructive_allowed` already exists and is not implied by Beast). Anything **not** enumerated
    stays unavailable and produces an explicit inconclusive result rather than a silent skip (§7.3).

---

## 4. Goal-framed reference ledger

Nine references assessed. Each idea is stated with its source path, the goal it serves, a verdict,
and how KRONOS would verify it actually worked.

### 4.1 Shannon

**Idea: "no exploit, no report."** Source: framework's reporting gate.
*Goal:* **G3.** *Verdict:* **Adopt** — already the core of KRONOS's lifecycle (decision 3).
*Gain:* structurally prevents unproven claims reaching a client. *Trade-off:* suppresses genuine
findings that are real but unexploitable in the window — mitigated by the LIKELY/INCONCLUSIVE tiers
(§5) so they are reported honestly rather than dropped. *Verify:* existing lifecycle tests plus the
X-score; a finding with no evidence must be unable to reach `reported`.

**Idea: dual-stream reconciliation.** *Goal:* **G1, G3.** *Verdict:* **Adopted** (Brief #4).
*Gain:* multiple sources feeding one graph without duplicate entities splitting the lifecycle.
*Verify:* done — real-duplicate tests assert the loser ends edgeless and `find_paths` returns the
survivor only.

### 4.2 PentAGI

**Idea: chain summarisation.** *Goal:* **G2.** *Verdict:* **Adapt** — summarise *from the graph*,
not from transcript history, so the summary is derived from validated state rather than from model
recollection. *Gain:* keeps planner context small as engagements lengthen. *Trade-off:* a summary
is lossy; the planner must be able to re-query the graph rather than trusting it. *Dependency:*
agent layer. *Verify:* a planner given only the summary must reach the same next-intent decision as
one given the full graph, on a fixed fixture.

**Idea: mentor/reflector loop-breaking.** *Goal:* **G2.** *Verdict:* **Adapt** — KRONOS's
loop-breaking is deterministic (per-task backoff + probe caps, §4.8/§4.9), with an LLM reflector
only as an advisory signal, never the stop authority. *Rationale:* a model deciding when to stop
itself is the least reliable place to put the stop. *Verify:* the doomed-task test — a task that
cannot succeed must be quarantined within N attempts without an LLM in the decision.

### 4.3 PentestGPT

**Idea: pentest task tree (PTT).** *Goal:* **G1, G2.** *Verdict:* **Adapt** — KRONOS already has a
richer substrate (a typed findings graph). Take the *idea* of an explicit, inspectable plan
structure; reject a parallel tree that could drift from the graph. **Single source of truth stays
the graph.** *Trade-off:* a graph is less legible to a human than a tree — mitigated by the export
view. *Verify:* no planner state exists that cannot be reconstructed from the graph.

### 4.4 RedAmon

**Idea: EPSS + KEV enrichment.** *Goal:* **G1 (prioritisation).** *Verdict:* **Defer** — both are
CVE-keyed and KRONOS emits no CVE-numbered findings today, so it would build into a vacuum.
*Dependency:* a CVE-producing ingestion path (realistically arrives with infra ingestion, S3/S4).
*Verify when built:* enrichment must never alter a finding's tier — assert that EPSS/KEV write only
to advisory fields and that the pre/post tier is identical.

**Idea: EvoGraph (evolving attack graph).** *Goal:* **G1.** *Verdict:* **Investigate** — overlaps
KRONOS's graph; unclear it adds anything beyond what Decepticon's DAG semantics (§4.9) already
supply. Not assessed in depth.

**Idea: AI-in-pipeline cascade.** *Goal:* **G2.** *Verdict:* **Adapt** — cheap deterministic
filters first, model calls only on what survives. Directly serves cost/latency. *Verify:* measure
model-call count per finding before/after on the CyberGym fixture.

### 4.5 PentestAgent

**Idea: MCP RAG tool-optimizer** (retrieve the right tool/technique for the current context).
*Goal:* **G1, G2.** *Verdict:* **Defer to the agent layer**, then **Adapt**. *Gain:* with five
domains (G1), the tool surface becomes too large for a fixed prompt, so retrieval becomes genuinely
necessary — but only *after* the domains exist. *Trade-off:* a retrieval layer is a new failure
mode and an indirect-prompt-injection surface if any retrieved content is attacker-influenced.
*Security:* retrieved tool docs must be treated as data, never instructions, and must come from a
KRONOS-controlled corpus — not from target-derived content. *Verify:* a poisoned-corpus test — an
entry containing instruction-shaped text must not change planner behaviour.

### 4.6 Strix

**Idea: contract-driven API testing.** *Goal:* **G1, G3.** *Verdict:* **Adopt at S5/S6** — testing
an API against its declared contract (OpenAPI/schema) gives deterministic expected-vs-actual
oracles, which is exactly the kind of evidence G3 wants. *Gain:* turns "looks wrong" into "violates
the declared contract," a strong, citable finding. *Dependency:* API ingestion that captures a
contract, which today does not exist (endpoints arrive only via the mobile parser). *Verify:* a
fixture API whose implementation deliberately deviates from its schema — KRONOS must find the
deviation and cite both the schema clause and the observed response.

**Idea: budget governance.** *Goal:* **G2.** *Verdict:* **Adopted** (Brief #5). *Verify:* done —
fail-closed tests plus the ledger snapshot.

### 4.7 Pentest-Swarm-AI

**Idea: cleanup/teardown registry.** *Goal:* **G2.** *Verdict:* **Adopted** (Brief #6). *Verify:*
done — live run leaves zero artifacts on both the happy path and a forced budget stop.

**Idea: `--strict` mode.** *Goal:* **G3.** *Verdict:* **Adapt** — KRONOS's equivalent is that
strictness is not a mode: the gates are always on. What `--strict` becomes here is a *reporting*
switch that suppresses everything below CONFIRMED.

**Idea: stigmergic swarm coordination.** *Goal:* nominally G2. *Verdict:* **REJECT (explicit).*
*Reason:* emergent coordination through shared environment state is unpredictable and unauditable;
it multiplies the places scope and budget must be enforced, and KRONOS is single-operator so there
is no throughput problem to solve. Rejected, not omitted.

**Idea: fails-open false-positive filter.** *Goal:* nominally G3. *Verdict:* **REJECT (explicit).**
*Reason:* a filter that fails open converts an error into a silently-accepted finding — the exact
inverse of G3. Every KRONOS gate fails closed. Rejected, not omitted.

### 4.8 Cairn (OG + the operator's private fork)

**Idea: the control plane is the sole writer.** Source: `docs/specs/dispatcher-design.md`; the agent
never claims, heartbeats, or calls the API — it returns structured JSON and the dispatcher performs
all authoritative writes. *Goal:* **G2, G3.** *Verdict:* **Adopt — this is the agent layer's
spine.** *Gain:* the LLM cannot write a finding, spend budget, or touch an out-of-scope target; it
can only hand the dispatcher a proposal the rails accept or reject. *Trade-off:* every agent
capability must be expressed as a contract, which is more work up front. *Verify:* a hostile-output
test — a proposal attempting to set `status`, `in_scope`, or `confidence` must be rejected at the
contract boundary, mirroring the existing C1 hostile-input test.

**Idea: minimal task taxonomy `bootstrap`/`reason`/`explore`.** Source: same spec; `reason` reads
the graph and either declares completion or proposes one intent, `explore` executes one claimed
intent. *Goal:* **G2.** *Verdict:* **Adapt** — take `reason` (planner) and `explore` (executor),
add KRONOS's **reviewer**, which Cairn has no equivalent for. *Verify:* the mock-driver end-to-end
test must complete a full plan→execute→review cycle with zero LLM calls.

**Idea: strict structured-output contracts.** Source: `dispatcher/contracts.py` —
`validate_reason_payload` etc. enforce shape before any action ("complete and intents cannot
coexist", intent count capped). *Goal:* **G2, G3.** *Verdict:* **Adopt.** *Gain:* a malformed or
hallucinated plan never reaches the graph. *Verify:* contract unit tests over malformed payloads.

**Idea: mock worker driver.** Source: `dispatcher/workers/adapters/mock.py` + `tests/test_mock_end_to_end.py`.
*Goal:* **G2, G3.** *Verdict:* **Adopt.** *Gain:* the entire orchestration is testable
deterministically at zero model cost — the single highest-leverage testing idea in the whole ledger,
and the project charter demands measurable evaluation. *Verify:* it *is* the verification mechanism.

**Idea: independent watchdog process with confirm-window escalation.** Source:
`supervisor/target_watchdog.py` — detects two distinct loop signatures ("the target is dead" vs
"your own driver has a bug"); on first detection always warns visibly; auto-pauses only if the same
signature persists past `CONFIRM_WINDOW_SECONDS` (900s) **and** no human acted; resets cleanly on
recovery. *Goal:* **G2.** *Verdict:* **Adopt.** *Gain:* unattended operation becomes defensible
because a pathological run stops itself without a human watching. *Security:* the escalation path is
the *human* stop path — *"There is no separate kill path; auto-pause IS that button, just pressed by
this script instead of a person."* No privileged capability is created. *Trade-off:* a second
process to run and monitor. *Verify:* inject a synthetic repeated signature and assert warn-then-stop
timing, plus that a human action inside the window cancels the escalation.

**Idea: cancelled tasks write nothing.** Source: same spec (a cancelled `bootstrap`/`explore` does
not enter conclude fallback). *Goal:* **G3.** *Verdict:* **Adopt.** *Gain:* a stop can never
manufacture findings. *Verify:* cancel mid-task, assert zero new nodes.

**Idea: conclude-on-timeout salvage.** *Goal:* **G2.** *Verdict:* **Adapt with a hard caveat** — a
salvaged result is a **hypothesis**, never validated. *Verify:* assert a salvaged result cannot
exceed `hypothesis`/INCONCLUSIVE.

**Idea: per-task-identity backoff.** Source: `CHANGES.md`, "Per-intent backoff on repeated
policy_refusal" — the only cooldown was a flat 5s keyed by `(project, task_type, worker)`, so one
doomed intent burned ~95 model invocations over 40+ minutes. *Goal:* **G2.** *Verdict:* **Adopt.**
*Gain:* KRONOS's budget ledger caps *total* spend but cannot stop one doomed task consuming all of
it — this closes that hole. *Verify:* the doomed-task test above.

**Idea: non-LLM deterministic credential checks.** Source: `supervisor/ssh_login_check.py`,
`http_login_check.py`, `winrm_login_check.py` — plain scripts, credentials from env only, never
logged, never in finding text. *Goal:* **G3** (deterministic evidence) and credential hygiene.
*Verdict:* **Adopt the hygiene and the determinism** — KRONOS already does this (validators are
plain code; `value_ref` stores a reference, not the secret). **Reject the framing** that moving an
action out of the LLM is a way to make an otherwise-gated action unattended; the fork's own
changelog reaches the same conclusion and declines it (§4.8 next entry).

**Idea: unattended automation of credential submission.** *Verdict:* **REJECT (explicit) — and the
reference rejects it too.** Source: `CHANGES.md` ~line 1055: *"**Explicitly did not build** ... That
was asked for directly and declined — not a technical limitation, a deliberate one. Routing
credential submission through plain code instead of the `claude` agent specifically to dodge the
safety classifier ... is the same restricted action with extra steps ... The trigger for this script
has to stay a human typing the command, every time."* *Goal impact:* this is the binding constraint
on G2. **SUPERSEDED 2026-10-16** as a blanket rule — see decision 10 and §7.3's revised action-class
table: Class C is now unattended in Beast mode **where the signed manifest enumerates the class for
a named target and time window**, and human-triggered otherwise. The reference's own reasoning still
stands for the case it addressed (an *LLM worker* submitting credentials with no authorization
naming that action), which is why the implementation note in §7.3 keeps credential submission inside
deterministic validators rather than model-authored requests.

**Idea: heavy multi-project/multi-worker server + scheduler + lease infrastructure.** *Verdict:*
**REJECT (explicit) for now.** *Reason:* built for many projects and workers in parallel; KRONOS is
single-operator, one engagement. Adopting it multiplies scope/budget enforcement points — a security
regression, not merely complexity. Revisit only if concurrent engagements become real.

**Idea: evidenceless `Fact` model.** *Verdict:* **REJECT (explicit).** A Fact is an LLM-asserted
description with no evidence requirement — precisely what G3 exists to prevent.

**Idea: session-JSONL tailing for live visibility.** Source: `supervisor/tailer.py`. *Verdict:*
**Defer as an optional adapter** (§7.4). *Reason:* gives detail the dispatcher structurally cannot,
but depends on a format Anthropic documents as internal/unstable. KRONOS owns its event stream
instead.

**Not assessed in Cairn:** `middleware`-equivalent internals of the server, the `pi` worker adapter,
container-archive handling, the RDP/X11 tooling (`rdp_lock.py`, `rdp_xtest.py`, `setup_headless_rdp.sh`).
Omission, not rejection.

### 4.8a Archive verification log (customized Cairn)

Recorded so the research history is auditable and so an unexamined area is never mistaken for a
cleared one.

| Date | Archive | Result |
|---|---|---|
| 2026-10-15 | `cairn-main.zip` | readable, 155 entries / 125 files; reviewed — findings in §4.8, §7.1, §8 |
| 2026-10-16 | `cairn-main_1.zip` | **byte-identical to the 2026-10-15 archive — no new features present** |

Verification method and evidence for the 2026-10-16 archive: zip integrity passed
(`unzip -t`); **zip SHA-256 identical** —
`7ef6db52eaa194e18b3a12a4f58878a3885284414cbcb9ff8f8ba54dfb1b7a62` for both; extracted-tree
aggregate SHA-256 identical — `923b01a2b3d103b46caa65d02e4205a5c39061191aca43b3306e1c7ca9808939`;
`diff -rq` across both trees reported **zero differences**; 125 files in each with none added or
removed; `CHANGES.md` 1157 lines in both with its newest dated entry **2026-10-10**, predating the
2026-10-15 review. The `_1` filename suffix is consistent with a repeated browser download of the
same export.

**Consequence:** the team's post-review additions have **not been assessed** — this is *omission for
lack of material*, explicitly not rejection. Any conclusion about their impact on KRONOS (including
on S6.5, §4.10c) remains open. To review them, the most reliable inputs are, in order: the
repository URL plus branch or commit (I clone and diff directly against the reviewed commit); a
`git bundle`; or `git diff <reviewed-commit>..HEAD` as a patch. A fresh zip works too, but a commit
reference removes exactly the ambiguity that occurred here.

### 4.9 Decepticon

**Idea: negative controls per finding.** Source:
`packages/decepticon/decepticon/agents/prompts/standard/finding_verifier.md` — re-run the smallest
in-scope positive proof, plus *"an equivalent negative control against the same route and
authentication context without the exploit condition,"* preserving both outputs; *"a status-code
difference alone is not proof of impact."* *Goal:* **G3 — the single highest-value idea in the
ledger.** *Verdict:* **Adopt (brief S1).** *Gain:* closes a real FP path in KRONOS's own
differentiator — `validate/` has **no** negative control and `http_validator.py` treats any 2xx as
live, so a permissive endpoint or proxy can drive an invalid credential to `reachable`. *Trade-off:*
2–3× validation requests. *Dependency:* the CyberGym fidelity fix (§7.2). *Verify:* §7.2's arm
matrix, plus a deliberately-permissive fixture endpoint that 200s on any header — KRONOS must
classify it as *not* a credential finding.

**Idea: verdict vocabulary with abstention** (`verified` / `false_positive` / `unverified`) plus a
mandatory `verification_rationale` naming both control results; *"never silently drop a rejected or
unverified finding"*; report gate allows only `verified` as a confirmed vulnerability. *Goal:*
**G3.** *Verdict:* **Adopt, mapped to CONFIRMED / LIKELY / INCONCLUSIVE** (§5). *Verify:* reporting
test — only CONFIRMED appears in the confirmed-vulnerability section; INCONCLUSIVE appears with
rationale and is never absent.

**Idea: the reviewer is independent and distrusts prior confidence.** Source: same file — *"A prior
agent's confidence is not evidence"*; *"Do not mark a finding verified merely because an earlier
agent did so."* *Goal:* **G3.** *Verdict:* **Adopt** — the reviewer sees the finding plus evidence
only, never the executor's context. *Verify:* assert the reviewer prompt contains no executor
reasoning; a fixture where the executor was confident but evidence is thin must downgrade.

**Idea: epistemic rule on blocked requests.** Source: same file, line 33 — *"Do not claim that a
blocked request proves the backend did not execute it."* *Goal:* **G3.** *Verdict:* **Adopt as a
first-class outcome class** — this is the correct epistemics for control-efficacy testing (§4.10).
*Verify:* a blocked probe must produce `INCONCLUSIVE`, never `false_positive`.

**Idea: evidence-gated plan DAG with transitive revocation.** Source:
`packages/decepticon/decepticon/tools/opplan.py` (`record_plan_fact`: fact must be pre-declared,
producer objective must be `completed`, ≥1 evidence path, evidence must be readable, `inspect_plan`
can reject, optimistic concurrency) and `middleware/opplan.py` (`revoke_plan_fact`: evidence
*"disproven or lost"* → *"Active and completed dependent objectives become blocked transitively"*;
`blocked_by` = all predecessors, `any_of` = one per alternative group; *"neither `phase` nor ATT&CK
tactic implies a DAG dependency"*; read-before-write for staleness prevention). *Goal:* **G1, G3.**
*Verdict:* **Adopt** — the dependency semantics for cross-domain chains, and transitive invalidation
(§7.5). *Gain:* `any_of` is what real attack paths need (alternative routes); the phase-is-not-a-
dependency rule keeps the graph causal rather than procedural; transitive revocation closes the
credential-rotation FP. *Trade-off:* explicit `derived_from` edges to maintain. *Verify:* rotate a
fixture credential, assert every dependent finding moves to `requires_revalidation` and none remains
CONFIRMED.

**Idea: decision-support layer is read-only.** Source:
`skills/standard/decepticon/kill-chain-analysis/SKILL.md` — `kind: analytic`, **`allowed-tools: Read`**,
"analytic decision support, no direct attack technique." *Goal:* **G2, G3.** *Verdict:* **Adopt** —
KRONOS's planner is read-only over the graph and has no capability to execute what it proposes.
*Gain:* the component choosing the next action physically cannot act, so planner misjudgement cannot
become target traffic. *Verify:* assert the planner's tool set contains no action tool.

**Idea: probe budget and three-strike rule.** Source: `prompts/workflows/recon.md` — *"At MOST 2
confirm probes per hypothesis. If 2 don't confirm, hand the hypothesis off, do not deepen"*;
`prompts/workflows/exploit.md` — three-strike rule, silent-stall recovery. *Goal:* **G2, G3.**
*Verdict:* **Adopt.** *Gain:* bounds rabbit-holing and FP-chasing. *Verify:* assert ≤2 probes per
hypothesis on a fixture that never confirms.

**Idea: RoE intake not revisable by the agent.** Source: `prompts/workflows/soundwave.md` — *"No
silent material assumptions. Scope, permitted actions, success criteria, evidence handling, and
safety boundaries require explicit operator confirmation"*; *"Do not revise launcher-provided RoE."*
*Goal:* **G2.** *Verdict:* **Adopt** — KRONOS's stronger form is the *signed* manifest, which the
agent cannot alter at all (§7.3). *Verify:* a tampered manifest must fail `load_and_verify`;
existing tests cover this.

**Idea: negative results are recorded as tested coverage.** Source: `finding_verifier.md` — *"A
verified negative result is tested coverage, never a verified vulnerability."* *Goal:* **G3.**
*Verdict:* **Adopt** — prevents re-testing and supports dedup, and is a genuine client deliverable
("we tested X and it held"). *Verify:* a negative result must be queryable and must not be
listable as a vulnerability.

**Idea: 16 specialist agents on LangGraph.** *Verdict:* **REJECT (explicit) as a structure**, adopt
the *intent*. *Reason:* three packages, a plugin loader and registry-parity tests are a large
surface for one operator; the benefit (domain specialisation with fresh context per objective) is
obtainable with role-specialised prompts/phases on one dispatcher loop. *Revisit* if KRONOS ever
needs genuine parallel specialisation.

**Not assessed in Decepticon:** `middleware/opplan_dispatch.py`, `opplan_hierarchy`, the
`decepticon-sdk` scaffold, `telemetry-gateway`, `benchmark/`, the wireless/IoT/contract-audit skill
families, and the `blue_cell` defensive agent (the last is **worth investigating** for the purple-team
loop in the project charter). Omission, not rejection.

### 4.10 Firewall resilience and control-efficacy testing

**This is a new goal-driven request, not an inherited feature — but the capability does exist in an
ancestor and has been assessed, so its treatment here is a decision, not an omission.** Source:
Decepticon `packages/decepticon/decepticon/skills/shared/defense-evasion/SKILL.md` and
`references/modern-evasion-techniques.md`; `skills/shared/stealth-infra/SKILL.md`;
`skills/shared/opsec/SKILL.md` (described as "traffic shaping, scan rate limiting, source IP
management, **tool signature avoidance**, evidence handling, **anti-detection patterns**", tagged
MITRE **T1562** impair-defenses, **T1070** indicator-removal, **T1036** masquerading).

This is split into five parts with different verdicts. **(c) was rewritten on 2026-10-16** — an
earlier blanket rejection of bypass testing is withdrawn as an over-broad categorisation; see the
record correction there.

#### (a) Engagement hygiene and blast-radius control — **ADOPT**

Source: `skills/shared/opsec/SKILL.md` §1 — "Written Rules of Engagement (ROE) on file", "Target IP
ranges and domains explicitly listed", rate limiting, "collect only what you need", *"Document
everything — if you can't prove it was authorized, it wasn't."*

*Goals:* **G2, G3.** *Gain:* rate limiting and footprint control keep an unattended Beast run from
degrading the target or drowning the client's SOC — a precondition for G2 being acceptable at all.
The ROE-on-file precondition is already stronger in KRONOS (signed manifest). *Trade-off:* slower
scans. *Dependencies:* budget ledger (exists), signed manifest (exists). *Verify:* assert a
configured request-rate ceiling is never exceeded across a full run, read from the event stream.

#### (b) Control-efficacy testing as a first-class finding type — **ADOPT (this is the valuable part)**

The defensible, measurable form of "firewall resilience" is: **did the protective control block the
authorized probe, and can we prove it?** Not: can we get past it undetected.

*Design:* every validation attempt already produces a positive arm and (after S1) control arms. Add
a third recorded dimension — the **control disposition** of each attempt: `blocked` / `allowed` /
`ambiguous`, derived from observable signals (connection reset vs challenge page vs WAF
fingerprint vs clean response), with the raw response preserved as evidence. Aggregate into a
**Control Efficacy Matrix** per engagement: for each attempted technique against each in-scope
target, did the control block it?

*Goals:* **G1** (it is cross-domain — WAF for web, IPS/segmentation for infra, API gateway for API,
cloud policy for cloud: one matrix across all five domains, which is exactly the connective tissue
G1 asks for) · **G3** (it makes "blocked" an explicit outcome class rather than a failed probe
silently recorded as "not vulnerable", which is a *false-negative* source KRONOS currently has) ·
**G2** (it is Class A/B work — observation of whether a control fired — so it is unattended-safe).

*The epistemic rule is already in the ledger:* Decepticon's *"Do not claim that a blocked request
proves the backend did not execute it"* (`finding_verifier.md:33`). A blocked probe therefore yields
**INCONCLUSIVE** for the underlying vulnerability and a **CONFIRMED control-efficacy observation** —
two different findings from one attempt. This is strictly more informative than today's behaviour.

*Why this is the better client deliverable:* "your WAF did not block parameter tampering on these
four endpoints, evidence attached" tells a defender what to fix. "we bypassed your WAF" tells them
they have a problem but not which control failed or how to verify the fix.

*Trade-offs:* control disposition is heuristic (WAF fingerprinting is inference, not proof), so it
must be tiered like everything else — `ambiguous` is a first-class value and the honest default.
*Security implications:* none beyond the probes already authorized; this adds *recording*, not new
traffic. *Dependencies:* S1 negative controls (shares the arm machinery), the owned event stream
(§7.4), per-protocol disposition rules at S4/S6.

*Verification — measurable outcomes, which is what makes this adoptable:*
1. **Range-level ground truth.** Extend CyberGym with a control tier: one route behind a blocking
   rule, one route explicitly unprotected, one behind a rule that logs-but-allows. Ground truth
   states the expected disposition per route.
2. **Disposition accuracy** as a scored metric: fraction of probes whose recorded disposition matches
   ground truth, with `ambiguous` counted as neither right nor wrong but reported separately.
3. **False-negative check:** a probe against the *unprotected* route must never be recorded as
   `blocked`, and a blocked probe must never yield a CONFIRMED vulnerability verdict.
4. **Idempotence:** the same probe twice yields the same disposition.

These are the "measurable outcomes" the goal asks for, and they can enter the X-score as a separate
dimension without polluting the existing E/P/X terms.

#### (c) Authorized WAF/firewall resilience assessment — **OPEN ARCHITECTURE DECISION (operator preference: build it)**

**Record correction (2026-10-16).** An earlier version of this record rejected "covert bypass"
wholesale. That was an over-broad categorisation and is withdrawn. It conflated two separable
things, and the operator's distinction is the correct one:

> **Bypass testing varies the payload. Concealment varies the attribution.**

Assessing whether a deployed control actually blocks the attack classes it is supposed to block is
mainstream control assessment that clients explicitly commission — "can an attacker get class X past
our WAF?" is a core deliverable, and a control that fails is a real finding the client needs. It is
**fully attributed**: the tester's traffic is identified, logged, and auditable. That is categorically
different from anti-forensics (log erasure, telemetry tampering, hiding activity), which remains a
separate concern and is **not** in scope here — see (d).

*Operator preference:* build this as an intended client-facing capability.
*Status:* **open architecture decision** — the design below is the proposal; the decision points at
the end are unresolved.
*Goals:* **G1** (controls exist in every domain: WAF for web, IPS/segmentation for infra, gateway for
API, policy for cloud — one assessment model across all five) · **G3** (it removes a real
false-negative source: a blocked probe recorded as "not vulnerable") · **G2** (most of it is Class
A/B; the parts that are not are called out below).

##### The epistemic core: one request cannot answer two questions

Bypass testing asks two independent questions, and conflating them is the entire FP/FN risk:

- **Q1 — did the control block the request?** (control disposition)
- **Q2 — did the backend actually accept/execute the payload?** (vulnerability existence)

| | Backend vulnerable | Backend not vulnerable |
|---|---|---|
| **Control blocked** | **Compensating control** — the bug is real; the control is the only thing preventing exploitation. A high-value client finding. | Both safe |
| **Control allowed** | **Exposed** — the serious finding | Allowed, but nothing to exploit |

A single request cannot distinguish these. A 403 may originate at the control or the application. A
200 may mean the payload reached the backend and did nothing, *or* that the control sanitised it and
the backend saw something benign. This is exactly Decepticon's rule
(`finding_verifier.md:33`): *"Do not claim that a blocked request proves the backend did not execute
it."*

##### The validation model — an n-arm differential, not an abandonment of two-armed proof

The earlier draft treated "the two-armed validator needs adapting" as a reason to decline. That was
wrong. The two-armed rule generalises: **the invariant is not "exactly two arms" but "no positive
claim without the counterfactual arms that isolate the variable."** For control assessment that is
four arms:

| Arm | Request | Establishes |
|---|---|---|
| **1 — benign baseline** | benign request, same route, through the control | what "normal" looks like (status, timing, body shape, control-injected headers) — needed to attribute a block to the control rather than the app |
| **2 — canonical attack through the control** | unmodified representative payload of the authorized class | the control's baseline efficacy for that class |
| **3 — canonical attack direct to origin** | same payload, via the separately-authorized origin path | **Q2 independently of Q1** — is the backend actually vulnerable? |
| **4 — variant through the control** | same semantic payload, different representation | whether the control's coverage of the class is complete |

**The backend-observable oracle is the hard requirement.** A bypass claim is only measurable if
execution at the backend can be observed, in descending strength: **out-of-band interaction** (the
payload causes the backend to contact a tester-controlled collector declared in the manifest —
strongest, unambiguous) · **in-band deterministic differential** (a reproducible observable unique to
execution) · **client-supplied telemetry** (app/WAF logs the client shares — weakest for proving
execution but strongest for attribution and auditability) · **response inference alone** → yields
INCONCLUSIVE, never CONFIRMED.

Without an oracle, "the variant got through" is unfalsifiable. **Arm 3 plus an oracle is what makes
this measurable;** arm 3 is also the part needing separate authorization.

##### Verdict taxonomy for this finding class

- **`CONTROL_BYPASSED`** (CONFIRMED) — arm 2 blocked, arm 4 passed, **and** the oracle fired. All
  three are required; arm 2 blocking is what proves the control normally covers the class, so the
  variant represents a genuine coverage gap rather than a class the control never claimed to handle.
- **`CONTROL_EFFECTIVE`** (CONFIRMED, **scoped**) — every variant within the authorized budget was
  blocked. The claim is always *"N variants of class X were blocked"*, **never** "the control cannot
  be bypassed." Abstention discipline applies in the negative direction too: absence of a found
  bypass is not proof of absence.
- **`BACKEND_VULNERABLE_CONTROL_COMPENSATING`** (CONFIRMED) — arm 3 fires, all through-control arms
  blocked. The underlying defect is real and the control is the only mitigation. Clients need this,
  and it is the finding most often lost today.
- **`INCONCLUSIVE_NO_ORACLE`** — arm 4 passed the control but execution could not be observed.
- **`INCONCLUSIVE_NO_ORIGIN_ARM`** — no authorized origin path, so Q1 and Q2 cannot be separated.
- **`AMBIGUOUS_DISPOSITION`** — cannot attribute the block to the control versus the application.

##### Authorization and scope representation

The control becomes a **first-class in-scope asset**, which means a new `CONTROL` node type in the
schema (and therefore canonical keys and reconciliation handling). Signed manifest extension:

```yaml
control_efficacy_testing:
  allowed: true
  controls:                                 # named, in-scope protections
    - id: waf-edge-prod
      kind: waf | ips | api_gateway | cloud_policy
      in_scope_routes: [...]
  payload_classes_authorized: [...]         # explicitly enumerated
  prohibited_classes: [dos, destructive_write, ...]
  variant_budget_per_class: 25              # hard ceiling; makes effort measurable
  origin_access:                            # SEPARATELY authorized, time-boxed
    allowed: true
    method: allowlisted_source_ip | provisioned_test_header | direct_origin_hostname
    reference: "client authorization ref"
    window_start / window_end
  oob_collector:
    allowed: true
    domain: "<tester-controlled, declared>"
  attribution:
    correlation_header: true                # default true
    declared_source_ranges: [...]
    blind_test: false                       # true requires its own authorization
```

##### Attribution preservation — the line that separates this from concealment

This is the enforceable invariant, and it is testable:

1. Every request carries a stable **engagement correlation header** (`engagement_id` + `attempt_id`)
   unless `blind_test` is explicitly authorized.
2. Source ranges and the OOB collector domain are **declared in the signed manifest**, so the
   client's SOC can attribute the traffic rather than chase it as a real intrusion.
3. **Variant generation operates only on the payload representation — never on the attribution
   markers.** KRONOS does not vary, strip, or rotate the headers, source identity, or collector
   domain that identify its traffic as authorized testing. *This is the architectural definition of
   "bypass testing, not concealment,"* and it should be enforced in code at the request-construction
   chokepoint, with a test asserting that no variant generator can touch a marker field.
4. KRONOS's own event stream records every request's args-digest and disposition; evidence blobs hold
   raw request/response for both the positive and control arms.

##### What must be isolated, auditable, or separately authorized

| Item | Treatment |
|---|---|
| **Origin-direct access (arm 3)** | separate manifest flag, separate client authorization reference, **time-boxed**; it is a network path that bypasses a production control and must not outlive the test window |
| **OOB collector** | domain declared in the manifest; receives interaction proof only — **never** target data; its logs are retained as evidence |
| **Variant corpus** | recorded as evidence so the client can see exactly what was sent; budget-capped per class |
| **Availability-affecting classes** | prohibited by default; opt-in per engagement only |
| **Blind testing** (no correlation header) | separate authorization — it defeats the client's own triage, so it is a detection-test engagement, not a default |
| **Action class** | arms 1, 2, 4 are Class B. **Arm 3 is Class C** — a provisioned bypass path. **RESOLVED 2026-10-16:** arm 3 may run **unattended in Beast mode only if the signed authorization permits it for the named target within the named time window**. Absent that, arm 3 is **unavailable**, Q1 and Q2 cannot be separated, and the finding is reported `INCONCLUSIVE_NO_ORIGIN_ARM` — never silently omitted |

##### Measurability — the CyberGym extension that makes this trustworthy

Extend the range with a control tier: a filtering proxy in front of a deliberately vulnerable route,
plus an unprotected route, plus a logs-but-allows route. Ground truth declares, per route: is the
backend vulnerable, does the control block class X, and is there a planted bypassable variant.

Scored metrics:

1. **Bypass detection rate** — did KRONOS find the planted bypass?
2. **False-bypass rate** — did it claim `CONTROL_BYPASSED` where ground truth says no bypass exists?
   **This is the G3 metric that matters and needs a hard floor**; a framework that over-claims
   bypasses is worse than one that finds none.
3. **Oracle attribution accuracy** — when it claims execution, did execution occur?
4. **Disposition accuracy** — blocked/allowed/ambiguous versus ground truth, with `ambiguous`
   reported separately rather than counted right or wrong.
5. **Compensating-control recall** — does it correctly identify the vulnerable-but-blocked case?

##### Unresolved decision points

- Whether `CONTROL_BYPASSED` requires arm 2 to have been blocked (proposed: yes — otherwise the
  "bypass" may be a class the control never covered, which is a scoping finding, not a bypass).
- Whether the control-efficacy matrix enters the X-score as its own dimension or is reported
  unscored until false-bypass rate is measured (leaning unscored initially).
- ~~Whether arm 3 can ever be unattended in Beast mode~~ — **RESOLVED 2026-10-16 (operator):**
  yes, **only** where the signed authorization permits it for the **named target and time window**.
  Otherwise arm 3 is unavailable and the result is `INCONCLUSIVE_NO_ORIGIN_ARM`. This makes the
  origin path an authorization-gated capability rather than a mode-gated one, which is the stronger
  model: a time-boxed signed grant is auditable, where a mode flag is not.
- ~~Variant generation mechanism~~ — **RESOLVED 2026-10-16 (operator):** **deterministic,
  replayable variants by default.** Model-proposed variants are deferred, and admissible later only
  if **recorded, replayable, attributable, and reproducible**. *Architectural consequence:* the
  variant generator must be a pure function of (payload class, seed, transformation set) so a
  finding's evidence can name the exact variant and a reviewer can regenerate it bit-for-bit; a
  model-proposed variant would have to be persisted as a literal artifact, not as a prompt, to meet
  the same bar. **Technique specifics stay out of this record** — it documents architecture and
  evaluation, not operational payload construction.

##### S6.5 dependency assessment (2026-10-16)

Keeping S6.5 as a **proposed** stage, after web validation (S6) and before staleness (S7). Hard
dependencies: (1) **S1's arm machinery** — S6.5's four arms are a generalisation of S1's two-armed
interface, so S1 must land first or the arm abstraction gets built twice; (2) **S6 web validation** —
WAF assessment needs a working web request/response path and web finding types; (3) **S4 infra
validation** — needed only for non-web controls (IPS/segmentation), so a web-only first cut of S6.5
could technically precede S4, but that would fork the disposition logic per protocol and is not
recommended; (4) **the `CONTROL` node type** plus its canonical key and reconciliation handling,
which is a schema touch requiring explicit authorization under decision 8's successor rule; (5) **the
owned event stream** (§7.4), since control disposition rides on invocation events. No dependency on
the agent layer — S6.5 is operator-driven and does not require autonomy to be useful.

**Impact of new Cairn features on S6.5: none assessable.** The archive supplied on 2026-10-16 is
byte-identical to the 2026-10-15 one (§4.8a), so no new upstream capability has been examined that
would change S6.5's dependencies. This is an *unverified* area, not a cleared one.

#### (d) Anti-forensics and unauthorized concealment — **separate concern, out of scope**

Kept deliberately separate from (c) per the operator's instruction. Not part of the control-efficacy
capability and not planned: log erasure or modification, telemetry/detection tampering
(MITRE **T1070**, **T1562**), and concealing KRONOS's own activity from the client's defenders
outside an explicitly authorized blind/detection test. These conflict with the evidence model that
makes KRONOS's output defensible — signed manifest, hashed evidence, teardown reports, the event
stream all exist so a client can audit exactly what was done. Where a client *does* commission a
detection test (can the SOC catch us?), that is a distinct engagement type with its own
authorization, and even then KRONOS retains its **own** complete internal audit trail; the test
reduces what the *client's defenders* are told in advance, never what the record contains.

#### (e) Purple-team inverse: detection signatures — **ADOPT (complements (c), does not replace it)**

For each control-efficacy observation, emit the **detection signature or telemetry expectation** a
defender needs to catch that technique. *Goal:* G1, G3, and the charter's
attack → telemetry → detection → hardening → validation loop. *Gain:* turns every bypass finding
into a remediation artifact — the client gets both "this got through" and "here is how to see it."
*Verify:* replay the recorded probe against the generated signature and assert it fires; replay a
benign-traffic sample and assert it does not.

---

## 5. Reviewer: downgrade-only authority (G3)

**Decision:** the reviewer LLM may downgrade a mechanically CONFIRMED finding to LIKELY or
INCONCLUSIVE when the evidence does not support the claimed impact. It may never upgrade, and never
override the rails.

**Tiers** (evidence rules, never model confidence): **CONFIRMED** — positive proof succeeded, every
negative control failed, impact *observed*. **LIKELY** — positive proof exists but a control arm is
missing/inconclusive, or impact is *inferred*. **INCONCLUSIVE** — scope, environment or evidence
prevents a verdict.

**Asymmetry enforced in code, not prompt.** The rails compute a *ceiling*; the reviewer supplies
`review_tier`, accepted only if at or below it. A tier above the ceiling is rejected as a contract
violation and logged. One function owns the comparison, as `advance_secret_status` owns status.

**Recorded on every downgrade, or the downgrade is rejected:** `mechanical_tier` (preserved),
`review_tier`, `downgrade_reason_code` (closed vocabulary: `impact_not_observed`,
`control_arm_inconclusive`, `attribution_ambiguous`, `duplicate_of`, `contradicted_by`,
`scope_uncertain`), `downgrade_rationale` naming **both control-arm results** and the unresolved
limit, `evidence_refs` (non-empty, must resolve), `contradicted_by`/`duplicate_of` node ids where
applicable, and `reviewer_id` / `reviewed_at` / `review_pass_id`.

**Independence:** a separate pass over the finding plus its evidence only — never a continuation of
the executor's context. **Nothing is silently dropped**; `discarded` is retired in favour of
retained-with-a-verdict. Only CONFIRMED may be listed as a confirmed vulnerability.

---

## 6. Sequencing — G1 before G2, both gated by G3

Web and infra are primary capabilities built **before** the agent layer, so the agent layer operates
across capabilities that already exist.

**Shared foundations first:** (1) an explicit **ingestion-source contract** —
`ingest(source, target) -> list[NodeUpsert|EdgeUpsert]`, everything entering at
`extracted`/`hypothesis`, upsert allowlist the only write path, so every new source inherits C1's
protection; (2) the **negative-control validator interface**, defined before web/infra validators
exist so they are born two-armed; (3) **canonical keys** for `WEB_ENDPOINT`, `PARAMETER`, `SERVICE`
(none exist — reconciliation would silently not dedupe them); (4) the **owned event stream**, emitted
from validators and ingestion first.

| Stage | Content | Goal | Why here |
|---|---|---|---|
| **S1** | Negative controls in `validate/` (+ CyberGym fidelity fix, §7.2) | G3 | FP-critical; defines the interface later stages implement against |
| **S2** | Ingestion contract + canonical keys + event stream | G1, G3 | one-time foundation; cheap now, expensive after two more sources |
| **S3** | **Infra ingestion** → `HOST`, `SERVICE` | G1 | web discovery needs to know which hosts expose HTTP; infra's parser is the most deterministic, so the best first exercise of S2 |
| **S4** | **Infra validation**, two-armed + control disposition | G1, G3 | extends the interface to a second protocol family |
| **S5** | **Web ingestion** → `WEB_ENDPOINT`, `PARAMETER`, seeded from S3 | G1 | depends on S3 |
| **S6** | **Web validation**, two-armed + control disposition | G1, G3 | largest surface; benefits from S1/S4 experience |
| **S7** | Transitive invalidation / staleness (§7.5) | G3 | worth building once ≥2 domains exist |
| **S8** | Agent layer Increments 1–3 | G2 | now has five domains to plan across |

FORK-2's shape-aware matcher lands at or before **S3** — infra is the first thing producing CIDR and
`ip:port` identifiers at volume, exactly where the untyped glob is most dangerous.

**First usable milestone — reachable at S6:** *a five-domain, evidence-validated engagement run —
infra, web, mobile, API and cloud ingestion feeding one graph, every finding carrying a two-armed
proof, a verdict tier and a control disposition — driven manually by the operator.* That is a
deliverable framework, not a demo. The agent layer then multiplies a working system rather than being
what makes it work. Cost, stated plainly: the agent layer slips ~four briefs.

---

## 7. Research findings (carried forward)

### 7.1 Decepticon attack-path linking — structurally evidence-gated, semantically LLM-adjudicated

Mechanically enforced in `tools/opplan.py` `record_plan_fact()`: versioned DAG required; fact
**pre-declared**; **producer objective `completed`**; **≥1 evidence path**, under `/workspace` and
**actually readable**; `inspect_plan()` can reject; optimistic concurrency. Not over-claimed — the
success message says *"The artifact exists; review its contents before relying on its claim."*
`middleware/opplan.py` adds execution-time dependency validation, `blocked_by`/`any_of` semantics,
"phase is not a dependency", `revoke_plan_fact` (evidence "disproven **or lost**" → transitive
blocking), and read-before-write staleness prevention. `kill-chain-analysis/SKILL.md` is read-only.
**Confidence: high.** Residual: `opplan_dispatch.py`, `opplan_hierarchy` not read.

**Differentiator, precisely:** KRONOS **mechanically re-executes each cross-domain edge as a live
authentication event and derives node status from that execution, with no agent in the attribution
path.** Not "the only framework treating mobile as first-class" (Decepticon has `mobile_operator`,
`cloud_hunter`) and not "the only one with chain-level evidence" (OPPLAN is evidence-gated). The
distinction is *what establishes the link*: code executing a request, versus an agent asserting one.

### 7.2 Cloud negative controls — specified, then verified empirically

**Method:** Docker Hub unreachable from the research container, so LocalStack could not be pulled.
The classification logic under test lives in `cybergym/cloud/sigv4_proxy.py` *before* it forwards, so
the real proxy was run against a stub upstream and driven with boto3. Repo unmodified; harness in
scratch; servers stopped after. This isolates the auth decision from LocalStack's known permissiveness.

| Arm | Observed |
|---|---|
| A valid general key → general bucket | **HTTP 200** |
| F valid admin key → admin bucket (over-privilege) | **HTTP 200** |
| E **unauthenticated** (UNSIGNED) | **403 `AccessDenied` — "Missing or malformed AWS SigV4 Authorization header"** |
| D **unknown access key** | **403 `AccessDenied` — "Unknown access key"** |
| C **known key, wrong secret** | **403 `AccessDenied` — "SignatureDoesNotMatch"** |
| B valid key → disallowed bucket | **403 `AccessDenied` — "…is not authorized to access…"** |

**What each tests:** unauthenticated (E) — whether auth is required *at all* (public buckets,
default-allow proxies). Wrong-but-well-formed (C/D) — whether *this* credential caused the success
(broken auth accepting any token); C exercises the signature cryptography and is the stronger arm.
B is not a liveness control — it is the **over-privilege discriminator**.

**Recommendation:** run **both** negative arms; `reachable` requires positive success **and** E and
C/D failing. Prefer C where the key id is known. **If E succeeds, reclassify as an
unauthenticated-access finding** (often more severe), never discard.

> **Finding that changes the brief: all four denial arms return identical HTTP 403 and identical
> `Error.Code` (`AccessDenied`), differing only in free-text `Message`.** So (1)
> `cloud_validator.py`, which collapses every `ClientError` to `live=False`, cannot distinguish
> no-auth-required from wrong-credential from valid-but-unauthorized — the last being the
> over-privilege signal; chain 3 passes today only because the *positive* arms differ. (2)
> Classifying on `Error.Code` is insufficient and on `Message` is fragile.
>
> **Range-fidelity gap — fix the fixture first.** Real AWS returns *distinct* codes
> (`InvalidAccessKeyId`, `SignatureDoesNotMatch`, `AccessDenied`); the proxy flattens all four, so a
> validator tuned to CyberGym prose would not transfer to a real target. Emit the real codes, or add
> a machine-readable `x-cybergym-deny-reason` header, and classify on codes/headers — never prose.

`validate/http_validator.py` treats any 2xx as live; same two-armed requirement, same
classify-on-structure rule. **Confidence: high** (directly observed).

### 7.3 Autonomy envelope in the signed manifest, with signed amendments (G2)

`src/kronos/manifest.py` signs Ed25519 over canonicalised `{engagement, scope}`; `load_and_verify()`
is the sole entry point; `engagement.destructive_allowed: false` already exists — **a signed
permission flag is an established pattern**, so this extends it.

Recommended signed fields under `engagement.autonomy`: `mode_max` (calm|beast),
`unattended_action_classes` (never C), `max_unattended_duration_seconds`, `max_unattended_budget`
(mirroring `BudgetLimits` dimensions), `exfil_simulation{allowed, byte_budget, dataset_marker}`,
`watchdog{may_auto_stop, confirm_window_seconds}`, and `amends{manifest_id, reason}`.

**Amendments:** Calm→Beast or **any** permission increase requires a **signed amendment chaining to
the prior manifest**, effective only once verified; the previous envelope stays in force until then,
and never applies retroactively. **Tightening applies immediately**, no ceremony, recorded.
Unsigned/unverifiable → rejected, previous envelope stands. A single function computes whether a
change is loosening or tightening, structurally per field.

**Effective-limit rule:** `min(signed, runtime)` in exactly one function; runtime config can only
narrow; **runtime exceeding signed is a hard startup failure** with a named reason, never a silent
clamp; no runtime path grants a class the manifest withholds; missing/unparseable autonomy block →
Calm with conservative defaults; the signed envelope is echoed into the engagement record, ledger and
teardown report.

**Operator stop is immediate and outranks everything.** One mechanism shared by operator and
watchdog — *"There is no separate kill path."* The flag is checked **before each action starts**, so
latency is one action; in-flight atomic actions are cancelled; **cancelled tasks write nothing**;
cleanup runs regardless of budget state. Stop is never gated by the envelope.

#### Action classes — REVISED 2026-10-16 (supersedes "Class C always human-triggered")

| Class | Content | Calm | Beast |
|---|---|---|---|
| **A** | read / analyse / graph query / report drafting | unattended | unattended, higher concurrency |
| **B** | active, non-credentialed, in-scope | tightly capped or asked | unattended within signed limits |
| **C** | credential use, target writes, exfil simulation, origin-direct arm, anything irreversible | per-action operator trigger | **unattended *iff* the signed manifest enumerates that class for the named target inside the named time window**; otherwise the action is **unavailable** and the dependent finding is reported **inconclusive**, never silently skipped |

**Why this is sound rather than a relaxation of rigour.** The authorization is specific (class +
named target + time window), signed, and verified before the action runs — categorically different
from an agent using credentials at its own discretion. It also matches how authorized engagements
actually work: a statement of work authorizes activities in advance; the tester does not call the
client before each request. Every safeguard that made the stricter rule defensible is retained —
attribution markers, evidence capture on all arms, the event stream, fail-closed gates, and an
**immediate** operator stop that is never gated by the envelope. Two constraints keep it honest: a
generic `mode: beast` authorizes nothing by itself (the class/target/window must be enumerated, so
breadth is never inherited), and destructive classes stay separately enumerated via the existing
`destructive_allowed` flag.

**Implementation note (operational fact, not policy).** The operator's customized-Cairn changelog
records that an **LLM worker** proposing credential submission was stopped by an external safety
classifier. That control sits on the *LLM-worker* path, not on KRONOS's own deterministic
validators, which are plain code and already perform unattended credential validation against the
CyberGym range. So this decision is implementable for KRONOS's validators as designed. A future
agent layer in which an LLM *constructs* the credential action may still meet that control — which
is a further argument for keeping credential submission inside deterministic validators the
dispatcher invokes, rather than in model-authored requests.

### 7.4 Progress visibility — own the event stream

KRONOS's dispatcher emits structured progress events as the stable interface; session-JSONL parsing
is a replaceable adapter. Required categories: task lifecycle · **every tool/validator invocation**
with args-digest and outcome · **every gate decision** (scope, budget + headroom, reviewer verdict,
lifecycle transition) with reason · **evidence created** by id and sha256 · budget/wall-clock as it
accrues · **heartbeat per in-flight task** · **stop and teardown** with initiator · **monotonic
sequence number + engagement id** for replay. Items 2–4 and 7 are what make the stream sufficient
for defensible client reporting; item 6 is what the watchdog consumes. Control disposition (§4.10b)
rides on the invocation events.

### 7.5 Staleness and re-evaluation (G3)

**Verified gap:** KRONOS has no invalidation propagation — `git grep` across `src/kronos/` finds only
per-node `dead` stickiness (`lifecycle.py:180`). A credential rotating mid-engagement leaves every
chain proven through it silently "proven."

**Design:** explicit **`derived_from`** edges from a FINDING to each node/edge its proof rests on
(without these the walk is inferred, which is where silent misses live) · evidence carries a
**validity basis** (`observed_at`, plus credential and target for auth proofs) · three deterministic
triggers — **refuted** (re-validation now fails), **lost** (blob missing or sha256 mismatch),
**expired** (`observed_at` older than a per-evidence-*kind* TTL; credentials age fast, static mobile
findings barely at all) · on trigger, walk `derived_from` transitively and move dependents to
**`requires_revalidation`**, preserving `mechanical_tier_at_stale` and recording `stale_reason` plus
the triggering evidence id · reporting treats it like INCONCLUSIVE and the synthesis must account
for it · **re-validation is the only way back**, re-entering at whatever tier the *fresh* evidence
earns · `dead` stays sticky · **read-before-write** on every finding update, rejecting writes against
a stale revision. Stage **S7**. **Confidence: high** on gap and mechanism; **medium** on TTL
defaults — make them configurable with conservative values.

### 7.6 Brief #7 review (PR #9) — reviewer findings, 2026-10-16

Reviewed the **actual diff** against `origin/main` `7d2df97`, not the builder's self-report.

**Verified correct.** `src/kronos/` zero-line diff (the brief's single most important criterion);
7 files, all inside the §2 allowlist; one commit. The §3.1 matrix matches real AWS on every row —
`AuthorizationHeaderMalformed` 400, `InvalidAccessKeyId` 403, `SignatureDoesNotMatch` 403,
anonymous 403 `AccessDenied`. FORK-H **DEFAULT taken**: `git grep` confirms
`x-cybergym-deny-reason` appears nowhere in proxy code — only in docs and as the forbidden literal
in the anti-leak guard. No assertion anywhere matches on `Message` text (verified by grep).

**§3.1a scoping is correct — the main fidelity risk, checked closely.** `_CASE_M1_RE` is
`$`-anchored immediately after `aws4_request`, so a valid header carrying
`, SignedHeaders=…, Signature=…` cannot match it; the authorized path is provably untouched even
though the M1 check runs *before* `parse_authorization_header`.

**Anti-leak guard verified non-vacuous.** Independently replicated its `REPO_ROOT` computation:
the glob resolves and scans **21** files. (A guard whose path is wrong finds zero files and passes
trivially — that failure mode was checked for, and is absent.)

**Two hardening nits, neither a blocker — fold into S1:**
1. The anti-leak guard asserts `offenders == []` but never asserts it *scanned* anything. Add
   `assert scanned > 0` so it can't silently become vacuous if the layout moves.
2. No negative test that a **non-M1** malformed shape does *not* get 400. The regex is correctly
   narrow today; without that test, a future widening of `_CASE_M1_RE` would silently break the
   §3.1a scope claim.

**§5.5 + §5.6 BLOCKED (live Docker run, X-score 3/3).** `pip install` inside the image build fails
TLS verification against PyPI in the cloud container; the fix needs the Dockerfiles, which are
**not** in §2's allowlist, so the builder stopped and reported instead of widening scope. **That is
the correct behaviour** and the clarification added to the brief did its job — hermetic tests were
not passed off as the live run. Blocker accepted as credible but **not independently reproduced by
the reviewer**; a local run settles it either way.

#### 7.6b Third attempt — LIVE VERIFICATION PASSED on local Kali, 2026-10-16

Run on the **correct environment** (local Kali, unproxied egress). The pre-flight gate passed:
`kali`, no proxy variables, no cloud CA marker, and a throwaway `docker build` installed from
PyPI successfully. **The proxy-CA hypothesis in 7.6 was therefore correct**, and 7.6a's
"reproduced in a second environment" was two runs of the *same* wrong environment — the earlier
prompt failed to state which machine it required, which is a researcher (my) error, not a builder
or environment one.

Live results at PR head `d6dc3264f3de4c63c4063e437b75491c8aadf60c`:

| Row | Observed live `(status, Error.Code)` | Matches declared matrix |
|---|---|---|
| `no_auth` | 403 `AccessDenied` | yes |
| `malformed_auth_header` (M1) | 400 `AuthorizationHeaderMalformed` | yes |
| `unknown_access_key` | 403 `InvalidAccessKeyId` | yes |
| `signature_mismatch` | 403 `SignatureDoesNotMatch` | yes |
| `bucket_not_allowed` | 403 `AccessDenied` | yes |

All **13** selftest checks passed. **`X-SCORE: 3/3`, exit code 0.**

- **§5.5 (live Docker-backed run): PASS**
- **§5.6 (live denial matrix via selftest): PASS**

All ten §5 criteria are now met. Re-fetched the PR head after the run: still
`d6dc3264…`, so no force-push changed what was reviewed or verified.

**Caveats, both minor.** The returned report was truncated mid-sentence, so the Step 6 clean-tree
proof was never delivered (low risk — the task performed no commits, and teardown reported only an
unrelated pre-existing MobSF container, not a range artifact). The `S0.5 range buildability`
brief proposed in 7.6a is **cancelled**: the range builds fine: there was never an infrastructure
defect, only a misdirected run.

**One defect survives, and it is introduced by this PR.** `git grep` on base `7d2df97` shows
**no** `TestClient` usage anywhere under `cybergym/` — PR #9's `test_denial_matrix.py` is the
first, and `httpx2` is declared in **no** requirements file or `pyproject.toml` on the branch.
Exact missing pin, from the Kali run: **`httpx2==2.13.1`**. So the PR adds a test that cannot be
*collected* from a clean checkout following the repo's own declared dependencies. `requirements.txt`
sits outside §2's allowlist, so the correct builder move was to stop and report the need; it never
noticed, because its venv already had the package. → **SPEC_BRIEF7.1**, one line, same branch,
before merge.

#### 7.6c Brief #7.1 amendment verified — and a researcher error it exposes

PR #9 head is now `bdec3b493a8364b354e420be4c34f97a6cfe1220`. Reviewed the amendment diff in full:
**exactly one line**, `+httpx2==2.13.1`, matching the file's existing pin style. `src/kronos/`
still zero-diff vs `7d2df97`. Files changed vs base: the original 7 plus
`cybergym/requirements.txt` — nothing outside Brief #7.1 §1's allowlist. Builder confirmed
`starlette==1.8.0`'s testclient imports `httpx2` (falling back to `httpx` only if absent), and
proved collection from a genuinely fresh venv: `cybergym/cloud/` 16 collected / 16 passed,
`tests/` 140 passed / 1 skipped.

**My error in SPEC_BRIEF7.1 §3.** The brief asserted the live Docker run need not be repeated
because "a one-line dependency pin cannot invalidate" it. That is false, and I should have traced
the file before claiming it:

- `cybergym/docker-compose.yml` builds all three services with `context: .` (inside `cybergym/`)
- `cybergym/cloud/Dockerfile` and `cybergym/api/Dockerfile` both
  `COPY requirements.txt /app/requirements.txt` then `RUN pip install --no-cache-dir -r`

So the pin is installed **into the `sigv4-proxy` and `api` images**. The passing X-score in §7.6b
was measured at `d6dc326`, whose images did **not** contain `httpx2`. Behavioural risk is low
(a test-only HTTP client, additive), but the *build* risk is real: pip may resolve
`httpcore`/`anyio`/`h11` differently against `fastapi` + `starlette`, which can break the image
build or shift runtime deps. The range is the measurement instrument for every later brief, so it
does not merge on evidence collected from different image contents.

**Action: re-run Steps 3–4 only (selftest + X-score), pinned at `bdec3b4`, on Kali.** No code
change, no new brief. Merge on 5/5 rows + 13/13 checks + X-score 3/3 at that exact commit.

**RESOLVED — re-verified at `bdec3b4` on Kali, 2026-10-16.** SHA exact, unproxied host. **All
three images built successfully**, with the build log showing `httpx2-2.13.1` resolving and
installing cleanly inside the `sigv4-proxy` image via the amended `requirements.txt` — the pip
resolution risk named above is **closed by direct evidence, not assumed away**. Live results:
5/5 denial rows match the declared matrix, **13/13 selftest checks**, **`X-SCORE: 3/3`, exit 0**.
Teardown clean (only an unrelated MobSF container, exited 4 days prior); `git status --porcelain`
empty. §5.5 and §5.6 **PASS at the merge commit**.

### PR #9 — REVIEWER APPROVAL FOR MERGE

All ten §5 criteria met, verified at `bdec3b493a8364b354e420be4c34f97a6cfe1220`:
`src/kronos/` zero-line diff · 8 files, all authorized (7 from §7 §2 + `requirements.txt` from
§7.1 §1) · hermetic 140+1-skip and 16/16 reproducible from a clean venv · live range 5/5 + 13/13 +
X-score 3/3. **Merge approved.** The CyberGym range is now a *verified* measurement instrument
rather than an assumed one, which is the precondition S1 needed.

**Carry into S1:** the two §7.6 hardening nits — `assert scanned > 0` non-vacuity on the anti-leak
guard, and a negative test that a **non-M1** malformed `Authorization` header does *not* return
400.

#### 7.6a Second verification attempt, 2026-10-16 — blocker reproduced, plus a new defect

A pinned read-only re-verification was run at PR head `d6dc3264f3de4c63c4063e437b75491c8aadf60c`.
Confirmed again: `src/kronos/` zero-line diff, 7 files inside the §2 allowlist, `tests/` 140 passed
/1 skipped, `cybergym/cloud/` 16 passed, clean tree, no leftover Docker artifacts.

**§5.5 and §5.6 remain BLOCKED/INCOMPLETE.** Identical root cause, now reproduced in a second
environment: `pip install` inside the image build fails
`SSLCertVerificationError: self-signed certificate in certificate chain` against PyPI, for all
three images (`sigv4-proxy`, `init-buckets`, `api`). The failure is in **stand-up**, before any
brief-#7 logic executes. No denial-matrix row has an observed `(status, Error.Code)` from a live
proxy; **no `X-SCORE` line was emitted at all** (exit code 1) — correctly reported as FAIL, not
rounded up.

**NEW DEFECT, independent of the environment — `httpx` missing from `cybergym/requirements.txt`.**
`fastapi.testclient` needs it transitively; a clean environment following only that file cannot
even *collect* `test_denial_matrix.py`. The cloud builder never hit this because its venv already
had `httpx`. So PR #9's hermetic suite — the only evidence currently supporting the brief — is
**not reproducible from a clean checkout**. `cybergym/requirements.txt` is **not** in the §2
allowlist, so the builder could not have fixed it without stopping to report; it is a genuine gap,
not a builder error. *(The reported error text mentioned `httpx2`; treat the exact package name as
unconfirmed and pin whatever the installed starlette actually requires.)*

**Reframing — this is no longer a brief-#7 problem.** The range cannot be stood up in either
environment tried. X-score is the measurement instrument for **every** live acceptance criterion
from here on, so an unbuildable range blocks S1 and everything after it, not just this brief.
Range buildability is therefore an **infrastructure prerequisite for S1+**, and should be its own
narrowly-scoped brief rather than a workaround smuggled into this one.

**Merge verdict: do not merge yet.** Not because the work is suspect, but because S1
(negative-control validation) is *measured against this range*. Merging on hermetic-only evidence
would seed S1 with an unverified instrument — the precise "passes the benchmark, fails in
production" failure §0 of the brief exists to prevent.

**Revised sequencing after 7.6a:** insert **S0.5 — range buildability** before S1. Scope: add
`cybergym/Dockerfile*`, `cybergym/docker-compose.yml` and `cybergym/requirements.txt` to an
allowlist *for that brief only*, to (i) make the image build trust the environment's egress-proxy
CA, and (ii) pin the missing test dependency. `src/kronos/` keeps its zero-line diff there too.
PR #9 then gets its live verification and both merge. This keeps the acceptance gate honest —
no criterion is waived — while fixing the thing that actually blocks every later measurement.

My earlier "just run it on local Kali" recommendation is **superseded**: it assumed the blocker
was specific to the cloud container's TLS proxy. Reproduction in a second proxied environment
weakens that assumption; it is only properly tested on a host with unproxied egress.

---

## 8. Agent layer design (G2, after S6)

Spine: a **single deterministic dispatcher loop** is the sole graph-writer; **planner** (`reason`,
read-only) and **executor** (`explore`) are structured-output proposers; KRONOS's **reviewer** fills
the slot Cairn leaves evidenceless; `scope_guard` / lifecycle / budget / cleanup are hard rails the
LLM can never override; strict JSON contracts plus a **mock driver** give deterministic tests;
conclude-on-timeout yields **hypotheses only**.

Topology settled from source: OG Cairn has **one** dispatcher loop (`scheduler/loop.py:83`,
`while True` in `DispatcherLoop.run`); the customized fork has **exactly one too**
(`loop.py:102`, same `run()` body — the diff is a `_project_workers_cache`). The "second loop" is a
separate **process**: `supervisor/target_watchdog.py:378`, plus `supervisor/tailer.py:373` and
`supervisor/rdp_lock.py:123,244`. KRONOS adopts **one orchestrator loop + one independent
supervisor-of-the-orchestrator**. Bounded in-loop concurrency is **not** a second loop. No sub-agent
pool.

Increments: **1** dispatcher skeleton + read-only planner, zero side effects, strict contracts, mock
driver · **2** reviewer + rails as commit gate, no live execution · **3** executor behind the gate,
CyberGym range only · **4+** loop-breaker, conclude-on-timeout, observability.

---

## 9. Open questions

1. **Per-protocol negative-control and control-disposition semantics beyond S3** — infra (S4) and web
   (S6) need their own expected-outcome tables; for some protocols an unauthenticated connection is
   indistinguishable from a port probe, which may make the two-armed rule degenerate there.
2. **TTL defaults per evidence kind** (§7.5) — ship configurable, conservative.
3. **Exact signed-manifest field names** for the autonomy envelope; amendment chains vs supersedes
   (current recommendation: chains via `amends.manifest_id`).
4. **`opplan_dispatch.py` / `opplan_hierarchy`** not read — unlikely to change §7.1.
5. **Decepticon's `blue_cell` defensive agent** — not assessed; worth investigating for the charter's
   purple-team loop and for the detection-signature output in §4.10(c).
6. **Where the Control Efficacy Matrix sits in the X-score** — a separate dimension, or reported
   alongside without scoring? Leaning separate-and-unscored until disposition accuracy is measured.
7. **Control-efficacy capability (§4.10c) — open architecture decision; operator preference is to
   build it.** Still unresolved: whether `CONTROL_BYPASSED` requires arm 2 to have been blocked
   (proposed yes), and where the `CONTROL` node type sits in the schema given it needs a canonical
   key and reconciliation handling (a schema touch needing explicit authorization).
   *Resolved 2026-10-16:* origin-direct arm authorization model, and deterministic-variants-by-default.
8. **Sequencing of §4.10c** — **S6.5 retained as proposed**, after S6, before S7; dependency
   assessment in §4.10c. Open: whether a web-only first cut may precede S4 infra validation
   (technically possible, not recommended — it forks disposition logic per protocol).
9. **Post-2026-10-10 customized-Cairn features — NOT ASSESSED** (§4.8a). The 2026-10-16 archive was
   byte-identical to the previous one, so nothing new was examined. Needs a commit reference, a
   `git bundle`, or a diff against the reviewed commit. Explicitly an omission, not a rejection, and
   it leaves S6.5's dependency assessment provisional.
