# SPEC_BRIEF10.md — FORK-2: shape-aware `scope_guard` matcher (hard pre-live blocker)

**Status:** build brief (stateless). Start from latest `main` (must contain the PR #11 merge —
check `src/kronos/ingest/contract.py` exists). New branch, open a PR, **do NOT merge**.
**Autonomy:** Balanced. Proceed on reversible calls. Escalate the FORKs in §7, and **stop and
report** on anything in §8 (open uncertainties) rather than guessing — this brief governs an
authorization boundary, so a wrong guess here is a client-facing incident, not a bug.
**Role separation (binding):** researcher wrote this; builder implements on a branch, opens a PR,
and never merges; reviewer reads the diff against §9 before merge.

**Method:** **TDD, RED first.** Issue #2 requires it explicitly. For every case in §5 you write the
failing test first, confirm it fails against today's behaviour, then make it pass. The §5 table is
the specification; code is what makes it green.

---

## 0. Why this brief exists, with evidence

`src/kronos/scope_guard.py` uses one untyped `fnmatch` mechanism for genuinely different identifier
kinds — FQDN, CIDR, URL, `host:port`, mobile bundle id — all drawn from one flat pattern list with
no tag saying which kind an entry is. GitHub **issue #2** (reopened 2026-10-16) records the
architectural resolution; the probes below are new measurements of the real
`ScopeGuard`/`_matches` on `main` @ `71ac247`, not inference.

### 0.1 Deny-side bypasses — an excluded host is reachable

| # | `excluded` | target | observed |
|---|---|---|---|
| F1 | `10.0.0.5/32` | `https://10.0.0.5/admin` | **IN SCOPE** |
| F2 | `10.0.0.5` | `https://10.0.0.5/admin` | **IN SCOPE** |
| F3 | `2001:db8::1/128` | `[2001:db8::1]:443` | **IN SCOPE** |

Mechanism, from the source: the `"/" in pattern` branch tries `ip_address()` on `target` and on
`_strip_port_suffix(target)`. A URL parses as neither, and `_strip_port_suffix` only strips when
`target.count(":") == 1` — so `https://10.0.0.5/admin` (one colon, non-numeric tail) and
`[2001:db8::1]:443` (many colons) both survive unchanged. Both candidates fail to parse, the loop
falls through, and matching degrades to `fnmatch` on the raw string, which cannot match. **The
exclusion silently does not apply.** This class is *not* described in issue #2 and is the most
serious finding here.

### 0.2 Allow-side over-matching — issue #2's two classes, confirmed

| # | `in_scope` | target | observed |
|---|---|---|---|
| F4 | `*acme.com*` | `https://evil.net/?next=acme.com/x` | **IN SCOPE** (class 1) |
| F5 | `com.acme.*` | `com.acme.evil.attacker.net` | **IN SCOPE** (class 2 — a bundle-id glob authorizes a hostname) |

### 0.3 False denials — these block S3 onward

| # | `in_scope` | target | observed |
|---|---|---|---|
| F6 | `*.acme.com` | `https://api.acme.com/v1/users` | **DENIED** → every URL-shaped endpoint node is out of scope |
| F7 | `*.acme.com` | `api.acme.com:8443` | **DENIED** → every `hostname:port` node is out of scope |

F7 also exposes an asymmetry: `10.0.5.10:443` **is** allowed by `10.0.5.0/24`, because
port-stripping lives only inside the CIDR branch and never on the hostname path.

### 0.4 The causal link

F6/F7 **cause** F4. An operator who cannot get endpoints or services in scope writes `*acme.com*`
to make the engagement run, and that glob is matchable by an attacker-controlled string. The safety
gap is downstream of the usability gap, so one brief must close both — fixing only the denials
leaves the leak, and fixing only the leak leaves KRONOS unable to test web or infra at all.

---

## 1. The binding architectural decision (do not re-litigate)

From issue #2, already resolved by architectural review:

- **ADOPT option (c):** `_matches` dispatches on the **target's** apparent shape — bare IP / CIDR,
  URL, bare hostname-or-bundle-id — the way it already does for CIDR-vs-everything, extended to
  URL-vs-hostname.
- **REJECTED option (b):** typed-prefix scope entries (e.g. `host:`, `cidr:`). They would require a
  signed-manifest schema change and a migration of already-signed manifests.
- **REJECTED option (a):** ship as-is permanently.

Therefore: **the signed manifest's on-disk schema does not change.** The pattern list stays flat and
untyped; all new intelligence is on the target side plus pattern-shape *inference*. Already-signed
manifests must verify and behave identically or better. If you conclude the decision is
unachievable as stated, **stop and report** — do not substitute option (b).

---

## 2. Hard guardrails

1. **`src/kronos/manifest.py` MUST have a zero-line diff.** No schema change, no new field, no
   change to `canonicalize`/`sign_manifest`/`load_and_verify`. A manifest signed before this brief
   must still verify after it.
2. **Excluded-first, default-DENY stays absolute.** The order is: any exclusion match → deny; else
   any in-scope match → allow; else deny. No new branch may return allow before exclusions have
   been fully evaluated.
3. **Exclusions are evaluated against every equivalent representation of the target.** This is the
   core of the fix: if a target is `https://10.0.0.5/admin`, the exclusion check must see
   `10.0.0.5` too. Under-matching an exclusion is the worst failure available in this module.
4. **Allow must never widen as a side effect of the fix.** Every case in §5 marked DENY must stay
   denied. A change that fixes F6 by making matching generally looser has failed.
5. **`scope_key` is not the fix.** `graph.py:140` calls `self.scope.is_in_scope(scope_key or id)`,
   so a caller may already pass a scope-relevant string. Do **not** solve this by asking ingesters
   to pass better `scope_key`s — that is the forget-to-filter trap, and SPEC_BRIEF9 guardrail 4
   forbids ingesters deciding scope. The fix lives in `scope_guard.py`.
6. **Deterministic, no LLM, no new runtime dependencies.** `ipaddress`, `fnmatch` and `urllib.parse`
   (stdlib) only.
7. `_ALWAYS_IN_SCOPE_TYPES = {"ENGAGEMENT"}` and `_NO_IN_SCOPE_COLUMN_TYPES = {"EVIDENCE"}` in
   `graph.py` are unchanged — not this brief's concern.
8. Do not weaken or delete any existing test. Baseline: **475 passed / 1 skipped** in `tests/`,
   **17 passed** in `cybergym/cloud/`.

---

## 3. Permitted files

**May change:**
- `src/kronos/scope_guard.py` — the matcher. **This brief is where its six-brief zero-diff streak
  ends; that is expected and intended.**
- `tests/test_scope_guard.py` — extend with the §5 matrix.
- `src/kronos/README_scope.md` (new, or the existing scope section of whichever README documents
  it) — document the shape taxonomy and the deny-side rule.
- `DECISIONS.md` — the FORK-2 resolution record, closing the issue-#2 loop.

**Must NOT change:** `manifest.py`, `graph.py`, `lifecycle.py`, `schema.py`, `validate/`,
`reconcile/`, `ingest/`, `budget/`, `cleanup/`, `events.py`, everything under `cybergym/`.
If you believe one is required, **stop and report**.

---

## 4. Design sketch (non-binding on implementation detail, binding on behaviour)

Two helpers, both pure and individually testable:

- **`classify_target(target) -> TargetShape`** — one of `url`, `ip`, `ip_port`, `host`,
  `host_port`, `bundle_id`, `unknown`. Detection order matters and must be documented.
- **`target_identities(target) -> list[str]`** — the equivalent representations a pattern may
  legitimately match. For example `https://api.acme.com:8443/v1/x` yields the host
  `api.acme.com`, the `host:port` `api.acme.com:8443`, and the full URL; `[2001:db8::1]:443` yields
  the bare address `2001:db8::1` and the bracketed `host:port` form.

`_matches` then compares **like to like**: a CIDR pattern is tested against the target's *address*
identities only; a hostname glob against its *host* identities; a URL pattern against the URL. A
bundle-id-shaped pattern must not match a hostname-shaped target, which is F5 (see §8.2 for the
part I am not certain about).

`is_in_scope` keeps its shape: exclusions over all identities first, then allows, then deny.

---

## 5. The test matrix — this is the specification

Write each as a RED test first. Cases marked **(F*)** reproduce a measured finding from §0 and must
fail before the fix.

### 5.1 Exclusion survives every equivalent representation (the headline)

| in_scope | excluded | target | expected |
|---|---|---|---|
| `*` | `10.0.0.5/32` | `https://10.0.0.5/admin` | **DENY** (F1) |
| `*` | `10.0.0.5` | `https://10.0.0.5/admin` | **DENY** (F2) |
| `*` | `2001:db8::1/128` | `[2001:db8::1]:443` | **DENY** (F3) |
| `*` | `10.0.0.5` | `10.0.0.5:443` | **DENY** |
| `*` | `10.0.0.5/32` | `10.0.0.5` | **DENY** |
| `*` | `api.acme.com` | `api.acme.com:8443` | **DENY** |
| `*` | `api.acme.com` | `https://api.acme.com/v1/x` | **DENY** |
| `*` | `api.acme.com` | `https://api.acme.com:8443/v1/x` | **DENY** |
| `*` | `2001:db8::1` | `2001:db8::1` | **DENY** |

### 5.2 Exclusion precedence beats a broader allow

| in_scope | excluded | target | expected |
|---|---|---|---|
| `*.acme.com` | `secret.acme.com` | `secret.acme.com` | **DENY** |
| `*.acme.com` | `secret.acme.com` | `https://secret.acme.com/x` | **DENY** |
| `10.0.5.0/24` | `10.0.5.10` | `10.0.5.10:443` | **DENY** |
| `10.0.5.0/24` | `10.0.5.10/32` | `https://10.0.5.10/x` | **DENY** |

### 5.3 Legitimate in-scope targets work — without widening

| in_scope | target | expected |
|---|---|---|
| `*.acme.com` | `https://api.acme.com/v1/users` | **ALLOW** (F6) |
| `*.acme.com` | `api.acme.com:8443` | **ALLOW** (F7) |
| `*.acme.com` | `api.acme.com` | ALLOW (regression — already passes) |
| `10.0.5.0/24` | `10.0.5.10:443` | ALLOW (regression — already passes) |
| `10.0.5.0/24` | `https://10.0.5.10/x` | **ALLOW** |
| `2001:db8::/32` | `[2001:db8::1]:443` | **ALLOW** |
| `2001:db8::/32` | `2001:db8::1` | **ALLOW** |
| `com.acme.*` | `com.acme.mobile` | ALLOW (regression — already passes) |

### 5.4 Wildcard over-match stays denied

| in_scope | target | expected |
|---|---|---|
| `*.acme.com` | `x.acme.com.attacker.net` | **DENY** (suffix confusion) |
| `*acme.com*` | `https://evil.net/?next=acme.com/x` | **DENY** (F4) |
| `com.acme.*` | `com.acme.evil.attacker.net` | **DENY** (F5) |
| `*.acme.com` | `https://evil.net/redirect?to=api.acme.com` | **DENY** |
| `*.acme.com` | `https://api.acme.com.attacker.net/x` | **DENY** |
| `10.0.5.0/24` | `10.0.6.10` | DENY (regression) |
| `*.acme.com` | `com.acme.mobile` | **DENY** (host glob must not catch a bundle id) |

### 5.5 Structural properties

1. **Default-deny:** empty `in_scope` denies every target in §5.3.
2. **Exclusion-first ordering is structural**, not incidental: a test asserting that for every
   (in_scope, excluded, target) triple in §5.1–5.2, swapping evaluation order would change the
   answer — i.e. the deny genuinely comes from the exclusion, not from a failed allow. *(This is the
   §7.6/§7.9 lesson: a case that passes by default-deny proves nothing about exclusions. Probe F
   in §0 passed for exactly that wrong reason before the matrix was written.)*
3. **Idempotent/pure:** `is_in_scope` returns the same answer for the same inputs; no ordering or
   caching effects.
4. **No crash on junk:** empty string, whitespace, `"://"`, a 4KB target, a pattern that is not a
   valid CIDR but contains `/` — all return a boolean, never raise.

### 5.6 Regression checks

- Every existing test in `tests/test_scope_guard.py` stays green **unmodified**. If one must
  change, that is a behaviour change outside this brief's intent — **stop and report** with the
  test name and why.
- `tests/test_invariants.py`, `test_schema_graph.py`, `test_ingest*.py`, `test_reconcile.py`,
  `test_validate_*.py` all stay green: scope feeds node creation everywhere, so a widened or
  narrowed matcher shows up as fixture drift here first.
- Full suite: report new totals against the 475/1 and 17 baselines.
- **Live:** the CyberGym run must still earn **X-score 3/3**, exit 0. The range's manifest is
  already signed — if the matcher changes its verdicts, the score moves, so this is the real
  end-to-end check that allow did not narrow. Needs an **unproxied** host; in a proxied cloud
  container report **BLOCKED / INCOMPLETE** and do not present hermetic tests as satisfying it.

---

## 6. The live-use gate (exact wording for `DECISIONS.md` and issue #2)

KRONOS may be pointed at a live client target, or run in Beast mode, only when **all** of these
hold:

1. This brief's PR is merged to `main` after reviewer diff approval.
2. Every §5 case is green, including §5.1 in full.
3. The live CyberGym run earns X-score 3/3 at the merge commit on an unproxied host.
4. `manifest.py` carries a zero-line diff, so previously signed manifests still verify.
5. GitHub issue #2 is closed **with a link to the merge commit**, not closed as stale.

Until all five hold, KRONOS stays confined to CyberGym and other non-live engagements, and **S3
does not start.**

---

## 7. FORKs

**FORK-S — how a URL's path participates in matching.** (1) A pattern containing `://` or a `/`
after a hostname is treated as a URL pattern and matched against the full URL; a bare hostname
pattern matches the URL's *host component only*. (2) Hostname patterns also match URL paths.
→ **DEFAULT: (1).** Option 2 is F4. Note the interaction with CIDR detection: `"/" in pattern`
currently routes to the CIDR branch, so URL-pattern detection must not break `10.0.5.0/24`.

**FORK-T — bundle-id vs hostname disambiguation.** (1) Treat a dotted token as a bundle id only
when the target cannot be a hostname (see §8.2), matching bundle-id patterns against bundle-id
targets only. (2) Keep them interchangeable.
→ **DEFAULT: (1)**, but see §8.2 — this is the one case where I am not confident the rule is
decidable from the string alone. If your analysis says it is not, **stop and report** rather than
shipping a heuristic that silently authorizes hostnames.

---

## 8. Open uncertainties — flagged for review, do not silently resolve

**8.1 `scope_key` call sites.** `graph.py:140` passes `scope_key or id`. I have verified the one
call site but **not** audited every caller that supplies a `scope_key`, so I do not know the full
set of target strings reaching the matcher in practice. Before relying on any shape assumption,
enumerate the actual `scope_key` values passed anywhere in the tree and report the list. If a shape
appears that §4's taxonomy does not cover, stop and report instead of extending the taxonomy by
guess.

**8.2 Bundle id vs hostname is not cleanly decidable.** `com.acme.mobile` and
`com.acme.evil.attacker.net` are both dotted ASCII labels. Distinguishing them from the string
alone is heuristic — a public-suffix check would help but adds a dependency, which guardrail 6
forbids. **This is the weakest point in the brief.** Report your proposed rule, its false-positive
and false-negative direction, and which §5.4 cases it decides, before treating F5 as closed. If the
honest answer is "cannot be decided safely here," say so: a documented limitation with a denied
default is acceptable; a heuristic that authorizes `com.acme.evil.attacker.net` is not.

**8.3 Whether F6/F7 reflect operator intent.** I assume `*.acme.com` in a signed manifest is meant
to authorize that host's services and endpoints, not just a bare-hostname node. That matches how
S3/S5 will emit node ids, but it is my inference, not a recorded decision. If it is wrong, the fix
for F6/F7 is a scope *widening* and must be escalated, not defaulted.

**8.4 IPv6 forms.** I probed the bracketed `[addr]:port` form. Zone indices (`%eth0`),
IPv4-mapped (`::ffff:10.0.0.5`) and compressed-vs-expanded equivalence are **not** probed. Treat
`::ffff:10.0.0.5` vs `10.0.0.5` as an open question: if an exclusion on one does not cover the
other, that is an F1-class bypass and must be reported.

---

## 9. Acceptance criteria

1. `manifest.py` zero-line diff; signed-manifest schema unchanged; a pre-brief signed manifest
   still verifies (prove it with a test).
2. Every §5.1 case denies — no exclusion escapable by changing the target's representation.
3. Every §5.2 case denies — exclusion precedence intact.
4. Every §5.3 case allows, including F6 and F7.
5. Every §5.4 case denies, including F4 and F5 **or** F5 explicitly reported unresolved per §8.2.
6. §5.5 structural properties hold, including the exclusion-not-default-deny assertion.
7. Existing `tests/test_scope_guard.py` green **unmodified**; whole suite green with totals reported.
8. Live X-score 3/3 exit 0, or **BLOCKED / INCOMPLETE** naming the environment.
9. Only §3's permitted files changed.
10. FORK-S and FORK-T choices recorded; every §8 uncertainty answered with evidence or escalated.
11. RED-first demonstrated: for each of F1–F7, state that the test failed before the fix and name it.
12. `DECISIONS.md` records the FORK-2 resolution and §6's live-use gate verbatim.

---

## 10. Output expected back

- Branch + PR link (not merged); diff summary; suite totals before/after.
- Guardrail confirmation: `manifest.py` zero-line, permitted files only.
- The §5 matrix as a pass/fail table, with F1–F7 flagged RED-before / GREEN-after.
- `classify_target`'s taxonomy and detection order, as implemented.
- FORK-S and FORK-T choices with reasons.
- An answer to each of §8.1–8.4, with evidence — including an honest "cannot be decided safely"
  where that is the truth.
- The live X-score line and exit code, or the BLOCKED / INCOMPLETE report.
- Confirmation that issue #2's five live-use gate conditions are either met or explicitly not met.
