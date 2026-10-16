# SPEC_BRIEF10.1.md — Trailing-glob boundary rule (amends PR #12, pre-merge)

**Status:** build brief (stateless). Continue on the SAME branch as PR #12
(`claude/scope-guard-shape-aware-brief10`, head `fa6285fc19cb453ced10a544fef05e00aa8b1dff`) and
push to that PR. Do NOT open a new PR. **Do NOT merge PR #12.**
**Autonomy:** Balanced. One FORK (§7), pre-resolved. **Stop and report** rather than guessing on
anything not covered here — this is an authorization boundary.
**Method: TDD, RED first.** G1–G6 below are measured defects in PR #12 as it stands. Write each as
a failing test against the current branch head, confirm it fails, then fix.
**Role separation:** researcher wrote this; builder implements on the branch and never merges;
reviewer reads the diff against §8 before merge.

**KRONOS stays confined to CyberGym** — no live-client target, no Beast mode — until this fix is
implemented, independently reviewed, and merged. §6 restates the full gate.

---

## 0. Why this brief exists

PR #12 closed F1–F8 and is good work. Reviewer probing of the **branch head** found that the
`host*` pattern shape — the one CyberGym's own signed manifest actually uses — is still matched by
raw character prefix, so it escapes to lookalike domains. SPEC_BRIEF10's §5 matrix never covered a
*trailing* glob, so this is a gap in the brief as much as in the code.

Measured against `pr12` @ `fa6285f`:

| # | `in_scope` | target | PR #12 | required |
|---|---|---|---|---|
| **G1** | `api.acme.com*` | `api.acme.com.attacker.net` | ALLOW | **DENY** |
| **G2** | `api.acme.com*` | `api.acme.com-evil.net` | ALLOW | **DENY** |
| **G3** | `localhost*` | `localhost.attacker.net` | ALLOW | **DENY** |
| **G4** | `127.0.0.1*` | `127.0.0.1.attacker.net` | ALLOW | **DENY** |
| **G5** | `http://localhost*` | `http://localhost.attacker.net/x` | ALLOW | **DENY** |
| **G6** | `kronos-cybergym-*` | `kronos-cybergym-x.attacker.net` | ALLOW | **DENY** |

G1 and G2 are the headline: an operator who writes `api.acme.com*` authorizes any domain whose
name merely *starts with those characters*, including one an attacker can register. G3–G5 are the
same defect in the range's own pattern shapes. G6 is a bucket-name glob authorizing a hostname.

**This is the same class SPEC_BRIEF10 exists to close** (issue #2's class 1), surviving in the
pattern shape most likely to be written by hand.

**Critically, the live gate would not have caught it.** The reviewer ran PR #12's matcher against
CyberGym's real signed `in_scope` list: all nine range targets pass, so X-score would have held at
3/3. The leak lives in the path the range depends on, which is why §5.5 below makes the range's
own manifest a permanent test rather than relying on the score.

---

## 1. The decisions

### 1.1 The boundary rule (the fix)

**A trailing `*` on a host-shaped pattern expands only at a delimiter boundary.** The permitted
boundaries are `:` (port), `/` (path), and end-of-string. It must **never** expand across a `.`
into another DNS label, and never mid-label.

So `api.acme.com*` covers `api.acme.com`, `api.acme.com:<port>`, `https://api.acme.com/...` and
`https://api.acme.com:<port>/...` — and nothing else. `api.acme.com.attacker.net` crosses a label
(G1); `api.acme.com-evil.net` expands mid-label (G2). Both deny.

### 1.2 Port semantics — the explicit decision you asked for

This is the authorization trade-off, stated plainly.

**The conflict.** `api.acme.com*` currently admits nonstandard ports, and so does `localhost*` —
which is exactly what CyberGym needs, since its API is on **8091** and LocalStack on **4566**.
Meanwhile SPEC_BRIEF10 §1.1 rule 4 says a *bare* hostname entry authorizes standard ports only.
Those two cannot both be true of the same pattern unless the trailing `*` means something.

**Option A — a trailing `*` after a complete host means "this host, any port, any path."**
*(DEFAULT)*
- Preserves every CyberGym target with **no manifest edit and no re-signing**.
- Makes all-ports authorization an **explicit operator act** — you get it by typing `*`, never by
  accident. A bare `api.acme.com` still denies `:8443`, per §1.1 rule 4, unchanged.
- Bounded by §1.1: the widening is to **one host's ports**, never to another host. Combined with
  the boundary rule, `localhost*` means "localhost on any port" and cannot reach
  `localhost.attacker.net`.
- Cost: an operator who writes `api.acme.com*` intending "the website" also authorizes `:22`,
  `:3389`, `:5432`. That is a real widening, and it is why it must be documented in
  `README_scope.md` as the meaning of a trailing `*`.

**Option B — a trailing `*` is standard-port-only too, like a bare host entry.**
- Tighter and more uniform.
- **Breaks the range.** `localhost*` would stop matching `localhost:8091` and `127.0.0.1*` would
  stop matching `127.0.0.1:4566`, so chain 1 and the cloud chains all fall out of scope and
  **X-score goes to 0/3**. Recovering it needs `cybergym/generate_scope_manifest.py` edited and the
  manifest re-signed — and `cybergym/` is off-limits in §3.
- Rejected: it trades a documented, operator-chosen widening for a silent capability loss, and it
  cannot be implemented inside this brief's file boundary anyway.

**DEFAULT: Option A.** Record it in `README_scope.md` and `DECISIONS.md` as the stated meaning of a
trailing `*`, so an operator reading the docs knows that `host*` grants all ports on that host and
`host` does not.

### 1.3 Buckets and ARNs stay distinct from hostnames

`kronos-cybergym-*` must keep matching `kronos-cybergym-general-secrets` — that is **mid-label**
expansion, correct for a bucket name and forbidden for a hostname. So the boundary rule is selected
by the **target's** shape, not the pattern's text:

- Target is **hostname/URL/IP-shaped** → the boundary rule of §1.1 applies.
- Target is **bucket-name or ARN-shaped** → free glob expansion, as today.
- A bucket- or ARN-shaped **pattern** must never authorize a hostname-shaped **target** (G6), and a
  hostname pattern must never authorize a bundle id (already locked by SPEC_BRIEF10 §5.7).

This is the §8.1 escalation SPEC_BRIEF10 asked for and PR #12 folded into the `host` catch-all
instead. Make the ARN/bucket shape explicit in `classify_target` now.

---

## 2. Hard guardrails (carried from SPEC_BRIEF10, still binding)

1. **`src/kronos/manifest.py` zero-line diff.** The signed-manifest format does not change. A
   manifest signed before Brief #10 must still verify. **No manifest may need editing or
   re-signing to make this brief's tests pass** — if you reach that conclusion, stop and report.
2. **Excluded-first, default-DENY is absolute.** Exclusions are evaluated over **every** equivalent
   representation with **no** port gating (deny is broad); allows are port-gated per §1.1/§1.2
   (allow is narrow). The boundary rule applies to the **allow** side only — it must not narrow any
   exclusion.
3. **No allow may widen** beyond what §1.1–1.3 state. Every DENY row in §5 stays denied.
4. **Do not unify** address-shaped and hostname-shaped allow semantics (Brief #10 §1.1 rule 7).
5. `scope_key` is not the fix. The fix lives in `scope_guard.py`.
6. Stdlib only — `ipaddress`, `fnmatch`, `urllib.parse`. No new dependencies, no LLM.
7. Do not weaken or delete any existing test. Branch baseline: **551 passed / 1 skipped** in
   `tests/`, **17 passed** in `cybergym/cloud/`.
8. The three `_SCOPE_GUARD_SHA256` pins in `test_budget.py` / `test_cleanup.py` /
   `test_reconcile.py` must be **re-pinned again** to the new hash — reviewer has signed off on that
   pattern. Keep the assertion messages; do not delete the guards.

---

## 3. Permitted files

**May change:** `src/kronos/scope_guard.py`; `tests/test_scope_guard.py`;
`src/kronos/README_scope.md`; `DECISIONS.md`; and the three hash pins only, in
`tests/test_budget.py`, `tests/test_cleanup.py`, `tests/test_reconcile.py` (the constant and its
comment — nothing else in those files).

**Must NOT change:** `manifest.py`, `graph.py`, `lifecycle.py`, `schema.py`, `validate/`,
`reconcile/`, `ingest/`, `budget/`, `cleanup/`, `events.py`, and **everything under `cybergym/`** —
including `generate_scope_manifest.py`. The range's signed manifest is an input to this brief, not
a thing to adjust. Stop and report if you believe otherwise.

---

## 4. Design

Extend PR #12's `classify_target` with explicit `bucket_name` and `arn` shapes, and add a
pattern-side helper that answers: *does this pattern's trailing `*` expand to this target at a
legal boundary?* Keep both pure and individually tested.

Matching stays like-to-like. For a host-shaped target the glob expansion is boundary-anchored; for
a bucket/ARN target it is free. One function decides the boundary question for every caller — do
not inline the rule at several match sites.

---

## 5. Test matrix

### 5.1 The lookalike escapes (RED — must fail on `fa6285f` first)

| in_scope | target | expected |
|---|---|---|
| `api.acme.com*` | `api.acme.com.attacker.net` | **DENY** (G1) |
| `api.acme.com*` | `https://api.acme.com.attacker.net/x` | **DENY** (G1) |
| `api.acme.com*` | `api.acme.com-evil.net` | **DENY** (G2) |
| `api.acme.com*` | `api.acme.comevil.net` | **DENY** — mid-label, no separator |
| `localhost*` | `localhost.attacker.net` | **DENY** (G3) |
| `localhost*` | `localhosted.attacker.net` | **DENY** — mid-label |
| `127.0.0.1*` | `127.0.0.1.attacker.net` | **DENY** (G4) |
| `http://localhost*` | `http://localhost.attacker.net/x` | **DENY** (G5) |
| `kronos-cybergym-*` | `kronos-cybergym-x.attacker.net` | **DENY** (G6) |
| `arn:aws:s3:::kronos-cybergym-*` | `kronos-cybergym-x.attacker.net` | **DENY** |

### 5.2 Trailing-glob port semantics (§1.2 Option A)

| in_scope | target | expected |
|---|---|---|
| `api.acme.com*` | `api.acme.com` | ALLOW (lock) |
| `api.acme.com*` | `api.acme.com:443` | ALLOW (lock) |
| `api.acme.com*` | `api.acme.com:8443` | ALLOW (lock) — trailing `*` grants all ports |
| `api.acme.com*` | `api.acme.com:22` | ALLOW (lock) — documented consequence |
| `api.acme.com*` | `https://api.acme.com:8443/x` | ALLOW (lock) |
| `api.acme.com` | `api.acme.com:8443` | **DENY** (lock) — bare host stays standard-port-only |
| `*.acme.com` | `api.acme.com:8443` | **DENY** (lock) |

The contrast between rows 3 and 6 **is** §1.2. Pin both in one test so the distinction cannot be
flattened later.

### 5.3 CyberGym's real manifest — permanent regression test

Build a `ScopeGuard` from the **exact** `in_scope` list in
`cybergym/generate_scope_manifest.py` (copy the literal values into the test; do **not** import
from `cybergym/`, and do not modify that file), and assert every row:

| target | expected |
|---|---|
| `http://localhost:8091/internal/v1/export` | **ALLOW** — chain 1; a DENY here means X-score 0/3 |
| `http://localhost:8091/health` | **ALLOW** — S1's abstention arm |
| `http://127.0.0.1:8091/internal/v1/export` | **ALLOW** |
| `localhost:4566` | **ALLOW** — LocalStack |
| `127.0.0.1:4566` | **ALLOW** |
| `localhost` | **ALLOW** |
| `kronos-cybergym-general-secrets` | **ALLOW** — bucket, mid-label expansion |
| `kronos-cybergym-admin-secrets` | **ALLOW** |
| `arn:aws:s3:::kronos-cybergym-admin-secrets` | **ALLOW** |
| `localhost.attacker.net` | **DENY** |
| `127.0.0.1.attacker.net` | **DENY** |
| `kronos-cybergym-x.attacker.net` | **DENY** |
| `http://localhost.attacker.net:8091/x` | **DENY** |

This is the test that makes the range's own patterns a tripwire instead of a blind spot.

### 5.4 Exclusion precedence across equivalent representations (deny stays broad)

| in_scope | excluded | target | expected |
|---|---|---|---|
| `api.acme.com*` | `api.acme.com` | `api.acme.com:8443` | **DENY** |
| `api.acme.com*` | `api.acme.com` | `https://api.acme.com/x` | **DENY** |
| `localhost*` | `localhost` | `localhost:4566` | **DENY** |
| `*` | `10.0.0.5/32` | `https://10.0.0.5/admin` | **DENY** (Brief #10 F1 — must not regress) |
| `*` | `2001:db8::1/128` | `[2001:db8::1]:443` | **DENY** (F3 — must not regress) |
| `kronos-cybergym-*` | `kronos-cybergym-admin-secrets` | `kronos-cybergym-admin-secrets` | **DENY** |
| `arn:aws:s3:::kronos-cybergym-*` | `arn:aws:s3:::kronos-cybergym-admin-secrets` | `arn:aws:s3:::kronos-cybergym-admin-secrets` | **DENY** |

Assert each deny came from the **exclusion**, not from a failed allow — remove the exclusion and
the same target must ALLOW.

### 5.5 Valid in-scope URLs and hosts still work (no narrowing)

Re-run SPEC_BRIEF10's §5.3, §5.4, §5.5, §5.5b, §5.6, §5.7 **unchanged** — all must stay green. Call
out explicitly that `*.acme.com*` + `api.acme.com:8443` keeps its PR #12 verdict per §7.

### 5.6 Every caller shape reaching `ScopeGuard`

Re-run SPEC_BRIEF10 §8.1's enumeration against the branch head and turn it into a **permanent
test**: for every distinct target shape that can reach `is_in_scope` from anywhere in the tree —
node ids per type plus any `scope_key` passed at a call site — assert a classified shape and an
expected verdict under a representative manifest. Report the enumerated list in the PR. If a shape
appears that §1.3's taxonomy does not cover, **stop and report** rather than widening the catch-all
again.

### 5.7 Structural and robustness

Carry SPEC_BRIEF10 §5.8 forward unchanged: default-deny on empty `in_scope`; exclusion-is-structural;
purity; no crash on junk (`""`, whitespace, `"://"`, `"http://"`, a 4KB target, a `/`-bearing
non-CIDR pattern, a bare `*`, a pattern that is only `*`).

### 5.8 Regression

Branch baseline **551 passed / 1 skipped** and **17 passed**; report new totals. Existing
`test_scope_guard.py` cases from Brief #10 stay green — if one must change, that is a behaviour
change outside this brief's intent, so **stop and report** with the name and why.

**Live:** CyberGym must still earn **X-score 3/3**, exit 0, at the new branch head, on an
**unproxied** host. §5.3 is the hermetic proxy for it, but it is not a substitute: report
**BLOCKED / INCOMPLETE** if the live run cannot happen, and never present hermetic tests as
satisfying it. **If X-score drops, report it with the per-target scope verdicts — do not loosen
§1.1–1.3 to recover the score.**

---

## 6. Live-use gate (unchanged from SPEC_BRIEF10 §6, restated)

KRONOS may be pointed at a live client target, or run in Beast mode, only when **all** hold:

1. PR #12 — including this amendment — is merged to `main` after independent reviewer diff approval.
2. Every case in SPEC_BRIEF10 §5 **and** this brief's §5 is green.
3. The live CyberGym run earns X-score 3/3, exit 0, at the merge commit on an unproxied host.
4. `manifest.py` carries a zero-line diff, so previously signed manifests still verify.
5. GitHub issue #2 is closed **with a link to the merge commit**, not closed as stale.

Until all five hold, KRONOS stays on CyberGym and **S3 does not start.**

---

## 7. FORK

**FORK-U — a pattern with wildcards at both ends (`*.acme.com*`).** (1) Leave PR #12's verdict
unchanged — it currently DENIES `api.acme.com:8443`, and such a pattern is not treated as a host
pattern for trailing-glob purposes. (2) Harmonize it with §1.2 so it behaves like `api.acme.com*`
and allows all ports.
→ **DEFAULT: (1), unchanged.** Option 2 is a widening with no demonstrated need, and widening is
the dangerous direction here. Pin the current verdict in a test so the choice is deliberate rather
than incidental, and note in `README_scope.md` that a both-ends wildcard is not a host pattern.

---

## 8. Acceptance criteria

1. G1–G6 all DENY, each demonstrated RED on `fa6285f` before the fix and named in the report.
2. §5.2 green, with rows 3 and 6 pinned in one test proving the `host*` vs `host` distinction.
3. §5.3 green — CyberGym's real manifest patterns, including the four lookalike DENY rows — and
   implemented without importing from or modifying `cybergym/`.
4. §5.4 green, each deny attributed to the exclusion, with Brief #10's F1 and F3 un-regressed.
5. §5.5 — every Brief #10 matrix section still green, unchanged.
6. §5.6 caller-shape enumeration reported and pinned as a test; no new catch-all widening.
7. §5.7 structural and robustness cases green.
8. `manifest.py` zero-line diff; no manifest edited or re-signed anywhere.
9. Buckets/ARNs explicit in `classify_target`; a bucket/ARN pattern never authorizes a
   hostname-shaped target.
10. Only §3's permitted files changed; the three hash pins re-pinned and their guards intact.
11. FORK-U recorded; §1.2's Option A documented in `README_scope.md` **and** `DECISIONS.md` as the
    stated meaning of a trailing `*`.
12. Full suite green with totals reported; live X-score 3/3 exit 0 at the branch head, or an
    explicit **BLOCKED / INCOMPLETE** naming the environment.
13. PR #12 still **not merged**.

---

## 9. Output expected back

- Same branch / same PR (#12) updated; diff summary; suite totals before/after.
- G1–G6 as a RED-before / GREEN-after table.
- §5.3's CyberGym table as pass/fail, with the chain-1 row called out explicitly.
- The §5.6 caller-shape enumeration, as a list.
- `classify_target`'s taxonomy after adding `bucket_name`/`arn`, and the boundary-rule helper's
  signature and permitted boundaries.
- Confirmation that no file under `cybergym/` was touched and no manifest was re-signed.
- FORK-U choice; the `README_scope.md` wording for a trailing `*`.
- Live X-score line and exit code, or the BLOCKED / INCOMPLETE report.
- Confirmation that PR #12 remains open and unmerged.
