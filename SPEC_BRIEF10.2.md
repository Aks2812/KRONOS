# SPEC_BRIEF10.2.md — Explicit-port URL patterns must obey the boundary rule (amends PR #12)

**Status:** build brief (stateless), narrow. Continue on the SAME branch as PR #12
(`claude/scope-guard-shape-aware-brief10`, head `d0e5232ddb45a61789d619b839e540dc5c5f0e96`) and
push to that PR. Do NOT open a new PR. **Do NOT merge PR #12 until the reviewer approves this
amendment's diff.**
**Autonomy:** Balanced. No FORKs — one defect, one fix. **Stop and report** if the fix would change
any behaviour beyond §2's table.
**Method: TDD, RED first.** H1's four cases must fail on `d0e5232` before the fix.
**Role separation:** researcher wrote this; builder implements on the branch and never merges;
reviewer reads the diff against §6.

**Scope note — H2 is NOT in this brief.** The dot-free-host classification defect (every
single-label hostname gets `bucket_name` semantics) needs `graph.py` in its allowlist and gets its
own architecture brief. This brief fixes H1 only. **FORK-2 remains incomplete and issue #2 stays
open** until H2 also closes; KRONOS stays on CyberGym and S3 does not start.

---

## 0. Why this brief exists

Brief #10.1 landed correctly — G1–G6 are independently verified DENY on `d0e5232`, guardrails are
clean, and the live X-score is 3/3. But the build made a carve-out to keep nine pre-existing tests
green, documented in the code itself at `src/kronos/scope_guard.py:448–451`:

> `rest` must carry no colon either: an entry that already pins an explicit port before the star
> (e.g. an existing `http://host:8091*`) is unambiguous as written and **stays on the literal
> whole-string path unchanged**

That literal path is `fnmatch` on the raw string, so a `scheme://host:port*` pattern escapes the
boundary rule. Measured on `d0e5232` with `in_scope = ['http://localhost:8091*']`:

| # | target | observed | required |
|---|---|---|---|
| **H1a** | `http://localhost:8091@evil.net/x` | **IN SCOPE** | **DENY** — `urlsplit().hostname` is `evil.net` |
| **H1b** | `http://localhost:8091.attacker.net/x` | **IN SCOPE** | **DENY** |
| **H1c** | `http://localhost:80915/x` | **IN SCOPE** | **DENY** — port 80915 ≠ 8091 |
| **H1d** | `http://localhost:8091evil.net/x` | **IN SCOPE** | **DENY** |

H1a is the userinfo form that Brief #10 §5.6 and §8.6 explicitly pinned for every other pattern
shape, re-opened for this one. A credential could be sent to `evil.net` under an authorization
written for localhost.

**Blast radius, measured:** the leak needs a pattern with an explicit port. CyberGym's signed
manifest uses `http://localhost*` and `http://127.0.0.1*` with no port, and those correctly deny
all four — verified. So **the range and X-score are unaffected**, and exclusions still override on
the leaking shape (also verified). This is a latent defect in a shape operators and the test suite
both write, not a live break.

**The carve-out was probably unnecessary.** `_matches_explicit_port_pattern` already does the
structured comparison this needs for the non-URL `host:port` shape — it extracts the target's host
and port via `_host_port_scheme` and compares them. Routing `scheme://host:port*` through the same
structured comparison should satisfy the nine tests, because they all target
`http://localhost:8091/...` paths, and a path is exactly what an explicit-port pattern should still
allow. Verify that rather than assume it.

---

## 1. The rule

A pattern of the form `scheme://host:port*` means: **that scheme, that host, that exact port, any
path and query** — compared structurally, never by raw string prefix.

- The target's host comes from `urlsplit().hostname` — so userinfo (`user@host`) resolves to the
  real host, matching what an HTTP client would connect to (Brief #10 §8.6).
- The port must equal the pattern's port exactly. A target whose port fails to parse (because the
  "port" is `8091.attacker.net` or `8091evil.net`) has no port and therefore does not match.
- Path, query and fragment are unrestricted once scheme, host and port match (Brief #10 §1.1 rule
  3 — scope is host-level, not path-level).
- **Exclusions stay broad.** As an exclusion, the same pattern remains port-blind and
  representation-blind per Brief #10 §1.1 rule 6 — this change must not narrow any exclusion.

---

## 2. Required behaviour (the whole specification)

With `in_scope = ['http://localhost:8091*']`:

| target | expected |
|---|---|
| `http://localhost:8091/internal/v1/export` | **ALLOW** (lock — chain 1; the nine tests depend on it) |
| `http://localhost:8091/health` | **ALLOW** (lock) |
| `http://localhost:8091/x?q=1#f` | **ALLOW** — path/query/fragment unrestricted |
| `http://localhost:8091` | **ALLOW** — bare, port matches |
| `http://localhost:8091@evil.net/x` | **DENY** (H1a) |
| `http://localhost:8091.attacker.net/x` | **DENY** (H1b) |
| `http://localhost:80915/x` | **DENY** (H1c) |
| `http://localhost:8091evil.net/x` | **DENY** (H1d) |
| `http://localhost:9091/x` | **DENY** — different port |
| `http://localhost/x` | **DENY** — a port entry does not authorize the portless form (Brief #10 §5.5) |
| `https://localhost:8091/x` | **DENY** — scheme must match |
| `http://127.0.0.1:8091/x` | **DENY** — different host |

Exclusion side, with `in_scope = ['*']` and `excluded = ['http://localhost:8091*']`:

| target | expected |
|---|---|
| `http://localhost:8091/x` | **DENY** |
| `http://localhost:9091/x` | **DENY** — exclusions are port-blind (rule 6) |
| `http://localhost/x` | **DENY** — exclusions are representation-blind |

---

## 3. Hard guardrails

1. `src/kronos/manifest.py` zero-line diff. No manifest edited or re-signed. Nothing under
   `cybergym/` touched.
2. `graph.py`, `lifecycle.py`, `schema.py`, `validate/`, `reconcile/`, `ingest/`, `budget/`,
   `cleanup/`, `events.py` all zero-diff. **H2 is out of scope here** — do not attempt it.
3. Every Brief #10 and #10.1 matrix case stays green, G1–G6 included. Re-run them.
4. Exclusions must not narrow. §2's exclusion table is the check.
5. **The nine pre-existing tests using `http://localhost:8091*` must pass UNMODIFIED** —
   `tests/test_negative_controls.py` (2), `tests/test_validate_candidates.py` (1),
   `tests/test_validate_runner.py` (6). If any needs editing, the fix is wrong: **stop and report**
   with the test name and the failure.
6. Stdlib only. Deterministic. No LLM.
7. Branch baseline: **591 passed / 1 skipped** in `tests/`, **17 passed** in `cybergym/cloud/`.
8. Re-pin the three `_SCOPE_GUARD_SHA256` constants (and their comments only) in
   `test_budget.py` / `test_cleanup.py` / `test_reconcile.py`. Keep the guards and messages.
9. **Stop and report rather than broaden.** Every escape in this thread came from a pattern
   matching more than intended.

---

## 4. Permitted files

`src/kronos/scope_guard.py` · `tests/test_scope_guard.py` · `src/kronos/README_scope.md` ·
`DECISIONS.md` · and the three hash-pin constants only, in `tests/test_budget.py`,
`tests/test_cleanup.py`, `tests/test_reconcile.py`.

Anything else: **stop and report**.

---

## 5. Tests

1. H1a–H1d as RED tests on `d0e5232` first; confirm each fails, then fix. Name them in the report.
2. §2's full allow/deny table, both halves, as a parametrized matrix.
3. The nine pre-existing explicit-port tests, unmodified and green.
4. Brief #10 and #10.1 matrices re-run green — explicitly confirm G1–G6 still DENY.
5. Robustness on this path: `http://localhost:*`, `http://:8091*`, `http://localhost:abc*`,
   `http://localhost:8091:9091*` — each returns a boolean, never raises, and never ALLOWs a target
   whose real host differs from the pattern's.
6. Full suite; report totals against the 591/1 and 17 baselines.
7. **Live:** CyberGym **X-score 3/3, exit 0** at the new branch head, on an unproxied host. If it
   drops, report with the per-target scope verdicts — do **not** loosen §1 to recover it.

---

## 6. Acceptance criteria

1. H1a–H1d DENY, each demonstrated RED-before / GREEN-after and named.
2. §2's allow rows ALLOW and deny rows DENY, both tables.
3. The nine pre-existing tests pass unmodified.
4. G1–G6 and every Brief #10/#10.1 case still green.
5. Exclusions un-narrowed — §2's exclusion table green.
6. `manifest.py` zero-diff; nothing under `cybergym/` touched; §3.2's modules zero-diff.
7. Only §4's files changed; the three hash pins re-pinned with guards intact.
8. Full suite green, totals reported; live X-score 3/3 exit 0, or **BLOCKED / INCOMPLETE** naming
   the environment.
9. `README_scope.md` documents what `scheme://host:port*` means, next to the trailing-`*` entry.
10. PR #12 still **open and unmerged**; H2 confirmed untouched and still open.

---

## 7. Output expected back

- Commit SHA pushed; diff summary; confirmation only §4's files changed.
- H1a–H1d RED-before / GREEN-after table.
- §2's two tables as pass/fail.
- Explicit confirmation the nine pre-existing tests were **not** modified — and if any had to be,
  stop instead and report it.
- Confirmation G1–G6 still DENY on the new head.
- Full test totals before/after; `git status --porcelain`; the literal `X-SCORE:` line and exit code.
- Confirmation that PR #12 remains open, unmerged, and that H2 was not touched.
