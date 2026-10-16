# SPEC_BRIEF10.md — FORK-2: shape-aware `scope_guard` matcher (hard pre-live blocker)

**Status:** build brief (stateless), **revision 3** — §1.1 scope-intent decision added by the
operator (rev 2); §8.5 CIDR/IP port semantics ratified by the operator and encoded as §1.1 rule 7
with matrix §5.5b (rev 3). §0.3 and §5 corrected against both. Start from latest `main` (must contain the PR #11 merge
— check `src/kronos/ingest/contract.py` exists). New branch, open a PR, **do NOT merge**.
**Autonomy:** Balanced. Proceed on reversible calls. Escalate the FORKs in §7, and **stop and
report** on anything in §8 rather than guessing — this brief governs an authorization boundary, so
a wrong guess is a client-facing incident, not a bug.
**Role separation (binding):** researcher wrote this; builder implements on a branch, opens a PR,
and never merges; reviewer reads the diff against §9 before merge.

**Method: TDD, RED first.** Issue #2 requires it explicitly. For every case in §5 you write the
failing test first, confirm it fails against today's behaviour, then make it pass. **The §5 matrix
is the specification**; code is whatever makes it green.

---

## 0. Why this brief exists, with evidence

`src/kronos/scope_guard.py` uses one untyped `fnmatch` mechanism for genuinely different identifier
kinds — FQDN, CIDR, URL, `host:port`, mobile bundle id — all drawn from one flat pattern list with
no tag saying which kind an entry is. GitHub **issue #2** (reopened 2026-10-16) records the
architectural resolution; the findings below are measurements of the real `ScopeGuard`/`_matches`
on `main` @ `71ac247`, not inference.

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

### 0.3 False denials — re-measured against §1.1's scope intent

**Correction to revision 1.** Revision 1 listed `*.acme.com` denying `api.acme.com:8443` as defect
"F7". Under §1.1 that denial is **correct** — 8443 is nonstandard and needs an explicit entry. The
real defects are at *standard* ports and in the URL form:

| # | `in_scope` | target | observed | §1.1 intent |
|---|---|---|---|---|
| F6 | `*.acme.com` | `https://api.acme.com/v1/users` | DENIED | **ALLOW** |
| F6b | `*.acme.com` | `http://api.acme.com/v1/x` | DENIED | **ALLOW** |
| F6c | `*.acme.com` | `https://api.acme.com:443/v1/x` | DENIED | **ALLOW** |
| F7′ | `*.acme.com` | `api.acme.com:443` | DENIED | **ALLOW** |
| F7″ | `*.acme.com` | `api.acme.com:80` | DENIED | **ALLOW** |
| F8 | `api.acme.com:8443` | `https://api.acme.com:8443/x` | DENIED | **ALLOW** — an explicit nonstandard-port entry does not cover its own URL form |

Already correct under §1.1, and therefore **regression locks, not fixes**: `*.acme.com` denies
`api.acme.com:8443`, denies the apex `acme.com`, and allows `a.b.acme.com`.

F8 matters operationally: S5/S6 emit URL-shaped nodes, so without it an operator who explicitly
scopes a nonstandard port still cannot test the endpoints on it.

### 0.4 The causal link

F6/F7′ **cause** F4. An operator who cannot get endpoints or standard-port services in scope writes
`*acme.com*` to make the engagement run, and that glob is matchable by an attacker-controlled
string. The safety gap is downstream of the usability gap, so one brief must close both.

---

## 1. Binding decisions (do not re-litigate)

### 1.0 Architecture, from issue #2

- **ADOPT option (c):** `_matches` dispatches on the **target's** apparent shape — bare IP / CIDR,
  URL, bare hostname-or-bundle-id — the way it already does for CIDR-vs-everything, extended to
  URL-vs-hostname.
- **REJECTED (b):** typed-prefix scope entries. They would require a signed-manifest schema change
  and migration of already-signed manifests.
- **REJECTED (a):** ship as-is permanently.

**The signed manifest's on-disk schema does not change.** The pattern list stays flat and untyped;
all new intelligence is target-side plus pattern-shape *inference*. If you conclude this is
unachievable as stated, **stop and report** — do not substitute option (b).

### 1.1 Scope intent — operator-ratified, governing

This resolves revision 1's §8.3. It is the authoritative reading of a hostname scope entry:

> `*.acme.com` authorizes DNS **subdomains** of `acme.com`, but **not the apex** `acme.com`.
> Equivalent URL forms on those matching hosts inherit scope for **HTTP/HTTPS on their standard
> ports**, regardless of path or query. **Nonstandard ports require explicit scope entries.** A
> redirect or URL parameter naming a different hostname does **not** inherit authorization, and
> **exclusions win across every equivalent representation.**

Derived semantics the implementation must honour:

1. **Subdomain, not apex.** `*.acme.com` matches `api.acme.com` and `a.b.acme.com` (any depth), and
   does **not** match `acme.com`. An operator wanting the apex adds `acme.com` as its own entry.
2. **Standard ports are 80 for `http` and 443 for `https`.** A hostname entry authorizes the bare
   host, the host with a standard port (`host:80`, `host:443`), and `http`/`https` URLs on those
   ports — whether the port is implicit or written out.
3. **Path and query are irrelevant to authorization.** Once the host is authorized, any path or
   query on it is in scope. Scope is host-level, not path-level.
4. **Nonstandard ports need an explicit entry.** `*.acme.com` does **not** authorize
   `api.acme.com:8443` or `https://api.acme.com:8443/x`. An entry naming the port
   (`api.acme.com:8443`) authorizes **both** the bare `host:port` and its URL forms (F8).
5. **No authorization transfer via URL content.** A hostname appearing in a path, query, fragment
   or redirect target never authorizes anything. Only the URL's **host component** is consulted.
6. **Allow is narrow; deny is broad.** This asymmetry is deliberate and must not be "harmonized":
   an *allow* entry for a host covers standard ports only, while an *exclusion* for a host excludes
   it on **every** port, scheme, path and representation. When in doubt, deny.
7. **A CIDR or bare-IP entry authorizes ALL ports on a matching address** — operator-ratified,
   2026-10-16, resolving §8.5. `10.0.5.0/24` authorizes `10.0.5.10`, `10.0.5.10:443`,
   `10.0.5.10:8443`, `10.0.5.10:22` and `https://10.0.5.10/x` alike. Rationale: an IP range in a
   signed SOW expresses **network-level** authorization — the host itself, not merely its web tier
   — whereas a hostname entry expresses web-tier intent and keeps rule 4's standard-port limit.

   **Allow semantics therefore differ by pattern shape, deliberately.** An address-shaped entry is
   port-blind; a hostname-shaped entry is port-limited. A builder's instinct will be to unify these
   — do not. They encode two different authorizations that clients actually grant differently.
   Rule 6 is unaffected: exclusions remain port-blind for every shape.

**Operational consequence to carry into S3:** under rule 7, CIDR- or IP-scoped infra work needs
**no** port-bearing manifest entries — an infra scan of an authorized range can validate services
on any port. Under rule 4, *hostname*-scoped work still does: a service on
`api.acme.com:8443` requires an explicit entry. S3's brief must state both, because an engagement
scoped by hostname and one scoped by CIDR will behave differently on exactly the same network.

---

## 2. Hard guardrails

1. **`src/kronos/manifest.py` MUST have a zero-line diff.** No schema change, no new field, no
   change to `canonicalize`/`sign_manifest`/`load_and_verify`. A manifest signed before this brief
   must still verify after it.
2. **Excluded-first, default-DENY stays absolute.** Any exclusion match → deny; else any in-scope
   match → allow; else deny. No new branch may return allow before exclusions are fully evaluated.
3. **Exclusions are evaluated against every equivalent representation of the target.** If the
   target is `https://10.0.0.5/admin`, the exclusion check must also see `10.0.0.5`. Under-matching
   an exclusion is the worst failure available in this module.
4. **Allow must never widen beyond §1.1.** Every §5 case marked DENY stays denied. A change that
   fixes F6 by making matching generally looser has failed.
5. **`scope_key` is not the fix.** `graph.py:140` calls `self.scope.is_in_scope(scope_key or id)`.
   Do **not** solve this by asking ingesters to pass better `scope_key`s — that is the
   forget-to-filter trap, and SPEC_BRIEF9 guardrail 4 forbids ingesters deciding scope. The fix
   lives in `scope_guard.py`.
6. **Deterministic, no LLM, no new runtime dependencies.** `ipaddress`, `fnmatch` and
   `urllib.parse` (stdlib) only.
7. `_ALWAYS_IN_SCOPE_TYPES = {"ENGAGEMENT"}` and `_NO_IN_SCOPE_COLUMN_TYPES = {"EVIDENCE"}` in
   `graph.py` are unchanged — not this brief's concern.
8. Do not weaken or delete any existing test. Baseline: **475 passed / 1 skipped** in `tests/`,
   **17 passed** in `cybergym/cloud/`.

---

## 3. Permitted files

**May change:**
- `src/kronos/scope_guard.py` — the matcher. **This brief is where its six-brief zero-diff streak
  (#4–#9) ends; that is expected and intended.**
- `tests/test_scope_guard.py` — extend with the §5 matrix.
- `src/kronos/README_scope.md` (new) — the shape taxonomy, §1.1's semantics, the deny-broad rule.
- `DECISIONS.md` — the FORK-2 resolution, §1.1 verbatim, and §6's gate.

**Must NOT change:** `manifest.py`, `graph.py`, `lifecycle.py`, `schema.py`, `validate/`,
`reconcile/`, `ingest/`, `budget/`, `cleanup/`, `events.py`, everything under `cybergym/`.
If you believe one is required, **stop and report**.

---

## 4. Design sketch (binding on behaviour, not on detail)

Two pure, individually testable helpers:

- **`classify_target(target) -> TargetShape`** — one of `url`, `ip`, `ip_port`, `host`, `host_port`,
  `bundle_id`, `unknown`. Detection order matters and must be documented.
- **`target_identities(target) -> list[str]`** — the equivalent representations a pattern may
  legitimately match, carrying the port and scheme so §1.1 rule 4 is decidable. For
  `https://api.acme.com/v1/x`: host `api.acme.com`, effective port 443 (implicit), scheme `https`.
  For `[2001:db8::1]:443`: address `2001:db8::1`, port 443.

`_matches` then compares **like to like**: a CIDR pattern against address identities only; a
hostname glob against the host identity, gated by §1.1's port rule; a port-bearing pattern against
`host:port` **and** the URL form of that same host and port (F8).

`is_in_scope` keeps its shape: exclusions over **all** identities with no port gating (deny is
broad), then allows **with** port gating (allow is narrow), then deny.

---

## 5. Acceptance matrix — this is the specification

Each is a RED test first. Cases marked **(F*)** reproduce a measured finding and must fail before
the fix. Cases marked **(lock)** already pass and must not regress.

### 5.1 Exclusion survives every equivalent representation

| in_scope | excluded | target | expected |
|---|---|---|---|
| `*` | `10.0.0.5/32` | `https://10.0.0.5/admin` | **DENY** (F1) |
| `*` | `10.0.0.5` | `https://10.0.0.5/admin` | **DENY** (F2) |
| `*` | `2001:db8::1/128` | `[2001:db8::1]:443` | **DENY** (F3) |
| `*` | `10.0.0.5` | `10.0.0.5:443` | **DENY** |
| `*` | `10.0.0.5/32` | `10.0.0.5` | **DENY** |
| `*` | `api.acme.com` | `api.acme.com:8443` | **DENY** — deny is broad: a host exclusion covers nonstandard ports |
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
| `api.acme.com:8443` | `api.acme.com` | `https://api.acme.com:8443/x` | **DENY** — exclusion outranks an explicit port entry |

### 5.3 Subdomain and apex (§1.1 rule 1)

| in_scope | target | expected |
|---|---|---|
| `*.acme.com` | `api.acme.com` | ALLOW (lock) |
| `*.acme.com` | `a.b.acme.com` | ALLOW (lock) — any depth |
| `*.acme.com` | `acme.com` | **DENY** (lock) — apex not authorized |
| `acme.com` | `acme.com` | **ALLOW** — explicit apex entry |
| `acme.com` | `api.acme.com` | **DENY** — an apex entry is not a wildcard |

### 5.4 Standard-port inheritance (§1.1 rules 2–3)

| in_scope | target | expected |
|---|---|---|
| `*.acme.com` | `https://api.acme.com/v1/users` | **ALLOW** (F6) |
| `*.acme.com` | `http://api.acme.com/v1/x` | **ALLOW** (F6b) |
| `*.acme.com` | `https://api.acme.com:443/v1/x` | **ALLOW** (F6c) |
| `*.acme.com` | `http://api.acme.com:80/x` | **ALLOW** |
| `*.acme.com` | `api.acme.com:443` | **ALLOW** (F7′) |
| `*.acme.com` | `api.acme.com:80` | **ALLOW** (F7″) |
| `*.acme.com` | `https://api.acme.com/x?q=1#frag` | **ALLOW** — path/query/fragment irrelevant |

### 5.5 Nonstandard ports require an explicit entry (§1.1 rule 4)

| in_scope | target | expected |
|---|---|---|
| `*.acme.com` | `api.acme.com:8443` | **DENY** (lock) |
| `*.acme.com` | `https://api.acme.com:8443/x` | **DENY** (lock) |
| `api.acme.com:8443` | `api.acme.com:8443` | ALLOW (lock) |
| `api.acme.com:8443` | `https://api.acme.com:8443/x` | **ALLOW** (F8) |
| `api.acme.com:8443` | `api.acme.com:9443` | **DENY** — one port, not a range |
| `api.acme.com:8443` | `api.acme.com` | **DENY** — a port entry does not authorize the bare host |
| `*.acme.com` | `http://api.acme.com:8080/x` | **DENY** — 8080 is not standard for http |

### 5.5b CIDR and bare-IP entries authorize all ports (§1.1 rule 7)

Address-shaped entries are **port-blind on the allow side**. Contrast every row here with §5.5,
where the hostname-shaped equivalent is denied — that divergence is the specification, not an
inconsistency to resolve.

| in_scope | target | expected |
|---|---|---|
| `10.0.5.0/24` | `10.0.5.10` | ALLOW (lock) |
| `10.0.5.0/24` | `10.0.5.10:443` | ALLOW (lock) |
| `10.0.5.0/24` | `10.0.5.10:8443` | **ALLOW** — port-blind, unlike the hostname rule |
| `10.0.5.0/24` | `10.0.5.10:22` | **ALLOW** |
| `10.0.5.0/24` | `https://10.0.5.10/x` | **ALLOW** |
| `10.0.5.0/24` | `https://10.0.5.10:8443/x` | **ALLOW** |
| `10.0.5.10` | `10.0.5.10:9999` | **ALLOW** — bare-IP entry, same rule |
| `10.0.5.0/24` | `10.0.6.10:443` | **DENY** — outside the network |
| `2001:db8::/32` | `[2001:db8::1]:8443` | **ALLOW** |
| `2001:db8::/32` | `[2001:db9::1]:443` | **DENY** — outside the network |

**Cross-shape sanity (the asymmetry, asserted directly):** with `in_scope = ['10.0.5.0/24',
'*.acme.com']`, `10.0.5.10:8443` is **ALLOW** while `api.acme.com:8443` is **DENY**, in the same
call. A single test should pin both so a later "cleanup" cannot quietly unify them.

**Exclusions stay port-blind for every shape (rule 6 unaffected):** with
`in_scope = ['10.0.5.0/24']` and `excluded = ['10.0.5.10']`, every target in the first seven rows
above becomes **DENY**.

### 5.6 No authorization transfer via URL content (§1.1 rule 5)

| in_scope | target | expected |
|---|---|---|
| `*acme.com*` | `https://evil.net/?next=acme.com/x` | **DENY** (F4) |
| `*.acme.com` | `https://evil.net/redirect?to=api.acme.com` | **DENY** |
| `*.acme.com` | `https://api.acme.com.attacker.net/x` | **DENY** |
| `*.acme.com` | `x.acme.com.attacker.net` | **DENY** — suffix confusion |
| `*.acme.com` | `https://evil.net/#api.acme.com` | **DENY** — fragment |
| `*.acme.com` | `https://user:pass@evil.net/x` | **DENY** — userinfo is not the host |
| `*.acme.com` | `https://api.acme.com@evil.net/x` | **DENY** — the host is `evil.net`; see §8.6 |

### 5.7 Bundle id vs hostname (§7 FORK-T)

| in_scope | target | expected |
|---|---|---|
| `com.acme.*` | `com.acme.mobile` | ALLOW (lock) |
| `com.acme.*` | `com.acme.evil.attacker.net` | **DENY** (F5) — or escalated per §8.2 |
| `*.acme.com` | `com.acme.mobile` | **DENY** (lock) — a host glob must not catch a bundle id |

### 5.8 Structural properties

1. **Default-deny:** empty `in_scope` denies every target in §5.3–5.5.
2. **Exclusion-first ordering is structural, not incidental.** For every triple in §5.1–5.2, assert
   the deny genuinely came from the **exclusion**, not from a failed allow — e.g. by asserting the
   same target is ALLOW with the exclusion removed. *(The §7.9 lesson: a case that passes by
   default-deny proves nothing about exclusions. Revision 1's probe F passed for exactly that wrong
   reason.)*
3. **Pure and idempotent:** same inputs, same answer; no ordering or caching effects.
4. **No crash on junk:** empty string, whitespace, `"://"`, `"http://"`, a 4KB target, a pattern
   containing `/` that is not valid CIDR — all return a boolean, never raise.

### 5.9 Regression checks

- Every existing test in `tests/test_scope_guard.py` stays green **unmodified**. If one must
  change, that is a behaviour change outside this brief's intent — **stop and report** with the
  test name and why.
- `tests/test_invariants.py`, `test_schema_graph.py`, `test_ingest*.py`, `test_reconcile.py`,
  `test_validate_*.py`, `test_manifest.py` all stay green: scope feeds node creation everywhere, so
  a widened or narrowed matcher surfaces as fixture drift here first.
- Full suite: report new totals against the 475/1 and 17 baselines.
- **Live:** the CyberGym run must still earn **X-score 3/3**, exit 0, at the PR head. The range's
  manifest is already signed, so if the matcher changes its verdicts the score moves — this is the
  real end-to-end proof that allow did not narrow. Needs an **unproxied** host; in a proxied cloud
  container report **BLOCKED / INCOMPLETE** and never present hermetic tests as satisfying it.
  **If X-score drops, report it with the per-target scope verdicts — do not loosen §1.1 to recover
  the score.**

---

## 6. The live-use gate (verbatim for `DECISIONS.md` and issue #2)

KRONOS may be pointed at a live client target, or run in Beast mode, only when **all** hold:

1. This brief's PR is merged to `main` after reviewer diff approval.
2. Every §5 case is green, including §5.1 in full.
3. The live CyberGym run earns X-score 3/3, exit 0, at the merge commit on an unproxied host.
4. `manifest.py` carries a zero-line diff, so previously signed manifests still verify.
5. GitHub issue #2 is closed **with a link to the merge commit**, not closed as stale.

Until all five hold, KRONOS stays confined to CyberGym and other non-live engagements, and **S3
does not start.**

---

## 7. FORKs

**FORK-S — how a URL's path participates in matching.** (1) Only the URL's **host component** and
effective port are consulted; path, query and fragment never authorize. (2) Hostname patterns also
match URL paths.
→ **DEFAULT: (1).** Mandated by §1.1 rule 5; option 2 is F4. Note the interaction with CIDR
detection: `"/" in pattern` currently routes to the CIDR branch, so any URL-pattern handling must
not break `10.0.5.0/24`.

**FORK-T — bundle-id vs hostname disambiguation.** (1) Match bundle-id patterns against bundle-id
targets only, treating a dotted token as a bundle id only when it cannot be a hostname.
(2) Keep them interchangeable.
→ **DEFAULT: (1)**, but see §8.2 — this is the one rule I am not confident is decidable from the
string alone. If your analysis agrees it is not, **stop and report** rather than shipping a
heuristic that silently authorizes hostnames.

---

## 8. Open uncertainties — flag, do not silently resolve

**8.1 `scope_key` call sites.** `graph.py:140` passes `scope_key or id`. I verified that single call
site but did **not** audit every caller supplying a `scope_key`, so the full set of target strings
reaching the matcher is unknown. Enumerate the actual `scope_key` values passed anywhere in the
tree and report the list. If a shape appears that §4's taxonomy does not cover, stop and report
rather than extending the taxonomy by guess.

**8.2 Bundle id vs hostname is not cleanly decidable — the weakest point.**
`com.acme.mobile` and `com.acme.evil.attacker.net` are both dotted ASCII labels. Distinguishing
them from the string alone is heuristic; a public-suffix check would help but adds a dependency
guardrail 6 forbids. Report your proposed rule, its false-positive/false-negative direction, and
which §5.7 cases it decides, before treating F5 as closed. **If the honest answer is "cannot be
decided safely here," say so** — a documented limitation with a denied default is acceptable; a
heuristic that authorizes `com.acme.evil.attacker.net` is not.

**8.3 RESOLVED** — superseded by §1.1, ratified by the operator.

**8.4 IPv6 forms.** The bracketed `[addr]:port` form is probed. **Not** probed: zone indices
(`%eth0`), IPv4-mapped (`::ffff:10.0.0.5`), and compressed-vs-expanded equivalence
(`2001:db8::1` vs `2001:0db8:0000:…:0001`). Treat each as an open question: if an exclusion on one
form does not cover an equivalent form, that is an **F1-class bypass** and must be reported, not
quietly left.

**8.5 RESOLVED** — operator-ratified 2026-10-16: reading (a), a CIDR or bare-IP entry authorizes
**all ports** on a matching address. Encoded as §1.1 rule 7 with matrix §5.5b. Not provisional;
record it in `DECISIONS.md` as a ratified decision alongside §1.1.

**8.6 NEW — URL userinfo and host-confusion forms.** §5.6 includes
`https://api.acme.com@evil.net/x`, where the real host is `evil.net`. `urlsplit().hostname` handles
this correctly, but confirm it and report any form where parsing disagrees with what a browser or
an HTTP client would actually connect to. A parser/client disagreement here is a scope bypass.

---

## 9. Acceptance criteria

1. `manifest.py` zero-line diff; signed-manifest schema unchanged; a manifest signed **before** this
   brief still verifies — prove it with a test.
2. Every §5.1 case denies — no exclusion escapable by changing the target's representation.
3. Every §5.2 case denies — exclusion precedence intact, including over an explicit port entry.
4. §5.3 subdomain/apex semantics exactly as §1.1 rule 1.
5. Every §5.4 case allows — F6, F6b, F6c, F7′, F7″ fixed.
6. Every §5.5 case behaves as specified — nonstandard ports denied without an explicit entry, and
   F8 fixed so an explicit port entry covers its URL form.
6b. Every §5.5b case behaves as specified — address-shaped entries are port-blind on the allow
   side, including the cross-shape test pinning `10.0.5.10:8443` ALLOW against
   `api.acme.com:8443` DENY in the same call, and the port-blind-exclusion rows.
7. Every §5.6 case denies — no authorization transfer via path, query, fragment or userinfo.
8. §5.7 as specified, **or** F5 explicitly escalated per §8.2.
9. §5.8 structural properties hold, including the exclusion-not-default-deny assertion.
10. Existing `tests/test_scope_guard.py` green **unmodified**; whole suite green, totals reported.
11. Live X-score 3/3 exit 0 at the PR head, or **BLOCKED / INCOMPLETE** naming the environment.
12. Only §3's permitted files changed.
13. FORK-S and FORK-T recorded; §8.1, §8.2, §8.4, §8.6 each answered with evidence or escalated
    (§8.5 is resolved — do not reopen it).
14. RED-first demonstrated: for F1–F8, state that the test failed before the fix and name it.
15. `DECISIONS.md` records the FORK-2 resolution, §1.1 verbatim, and §6's gate verbatim.

---

## 10. Output expected back

- Branch + PR link (not merged); diff summary; suite totals before/after.
- Guardrail confirmation: `manifest.py` zero-line, permitted files only.
- The §5 matrix as a pass/fail table, with F1–F8 flagged RED-before / GREEN-after and every
  **(lock)** row confirmed un-regressed.
- `classify_target`'s taxonomy and detection order as implemented, plus how effective port and
  scheme are derived.
- FORK-S and FORK-T choices with reasons.
- An answer to each of §8.1, §8.2, §8.4, §8.6 — including an honest "cannot be decided safely"
  where that is the truth. §8.5 is ratified, not open.
- Explicit confirmation that §1.1 rule 7's shape asymmetry is implemented as specified and that no
  code path unifies address-shaped and hostname-shaped allow semantics.
- The live X-score line and exit code, or the BLOCKED / INCOMPLETE report.
- Whether issue #2's five gate conditions are met or explicitly not met.
