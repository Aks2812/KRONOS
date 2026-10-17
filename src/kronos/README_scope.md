# Scope guard (SPEC_BRIEF10 / FORK-2: shape-aware matching; SPEC_BRIEF10.1: trailing-glob boundary rule)

`scope_guard.py` is the ONLY scope-authorization mechanism (SPEC.md
"SCOPE GUARD"). Every node gets `in_scope` stamped on it at creation by
calling `is_in_scope` on a flat, untyped pattern list — exclusions
first (hard deny), then allows, default deny. No other code path may
set `in_scope` directly.

Before this brief, `_matches` used one untyped `fnmatch` mechanism for
every pattern and every target, regardless of what kind of thing either
one actually was. That both under-matched exclusions (an excluded
`10.0.0.5` did not deny `https://10.0.0.5/admin` — the URL and the bare
IP just look like different strings to `fnmatch`) and over-matched
allows (a loose glob written to compensate for that under-matching,
like `*acme.com*`, is itself matchable by an attacker-controlled
string). GitHub issue #2 is the architectural record; the fix below is
issue #2's **option (c)**: dispatch on the target's *apparent shape*,
compared like-to-like against the pattern. **Option (b)** — typed
scope-entry prefixes — was explicitly rejected: it would have required
a signed-manifest schema change, and `manifest.py` is a zero-line diff
in this brief (guardrail 1). The pattern list stays a flat list of
plain strings forever; all the new intelligence is in how a string is
*interpreted*, never in how it is stored.

## The taxonomy (`classify_target`)

```
TargetShape = "url" | "ip" | "ip_port" | "host" | "host_port"
            | "bundle_id" | "arn" | "bucket_name" | "unknown"
```

Detection order (each step rules out every later one):

1. Empty/whitespace-only → `unknown`.
2. Starts with the literal `"arn:"` → `arn` (SPEC_BRIEF10.1 §1.3).
   Unambiguous — no hostname, IP, or bundle id is ever spelled this
   way — checked before any of the shapes below are even attempted.
3. `[addr]` or `[addr]:port`, `addr` a valid IP literal (zone indices
   and IPv4-mapped forms included — `ipaddress` accepts both natively)
   → `ip_port` if a port follows, else `ip`.
4. Exactly one `:`, left side alone a valid IP, right side all digits
   → `ip_port` (the `"ip:port"` node-id shape SPEC.md's own dedup
   convention produces; never fires for a bare IPv6 literal, which has
   more than one colon).
5. The whole string parses directly as an IP address → `ip`.
6. `urlsplit()` gives an `http`/`https` scheme with a non-empty
   `netloc` → `url`. (A string like `"api.acme.com:443"` is *not*
   mistaken for a URL here — `urlsplit` happily treats `"api.acme.com"`
   as a bogus scheme, which the explicit `scheme in ("http", "https")`
   check rejects.)
7. Exactly one `:`, right side all digits (the left side is never an IP
   by this point) → `host_port`.
8. Contains `"://"` but `urlsplit` found no netloc (`"http://"`,
   `"://"`) → `unknown`.
9. No `"."` at all → `bucket_name` (SPEC_BRIEF10.1 §1.3). The one shape
   this module can tell apart from a multi-label hostname/lookalike
   domain by the string alone: every lookalike this module denies
   introduces its new label with a literal `.` (an attacker always
   registers `<something>.attacker.net`), so "no dot anywhere" is a
   safe, conservative signal that a trailing-glob pattern may keep
   expanding freely against this target — it only ever *relaxes*
   matching back to the module's pre-SPEC_BRIEF10.1 behavior, never
   narrows an existing allow or exclusion.
10. Anything else → `host`.

`classify_target` never returns `bundle_id`, even though it stays in
the taxonomy. See **FORK-T** below for why.

## §1.1 — the governing scope-intent rule

Operator-ratified, not re-litigated by this module:

1. **Subdomain, not apex.** `*.acme.com` matches `api.acme.com` and
   `a.b.acme.com` (any depth) but not `acme.com` itself. Want the apex?
   Add it as its own entry.
2. **Standard ports are 80 (http) / 443 (https).** A hostname entry
   authorizes the bare host, the host at a standard port, and
   `http`/`https` URLs on those ports — implicit or explicit.
3. **Path/query/fragment are irrelevant once the host is authorized.**
   Scope is host-level, not path-level.
4. **Nonstandard ports need an explicit `host:port` entry.** That entry
   then authorizes both the bare `host:port` and its URL form (F8).
5. **No authorization transfer via URL content (FORK-S).** Only the
   URL's host component and effective port are ever consulted — never
   path, query, fragment, or userinfo.
6. **Allow is narrow; deny is broad — deliberately asymmetric.** An
   excluded host is excluded on every port, scheme, path, and
   representation, regardless of how the exclusion entry is written.
   This must never be "harmonized" with rule 2/4's allow-side limit.
7. **A CIDR or bare-IP entry authorizes ALL ports (rule 7, resolving
   §8.5).** `10.0.5.0/24` authorizes `10.0.5.10`, `:443`, `:8443`,
   `:22`, and `https://10.0.5.10/x` alike — an IP range in a signed SOW
   is network-level authorization, not web-tier intent, so it does not
   inherit rule 4's standard-port limit. **Address-shaped and
   hostname-shaped allow semantics are NOT unified.** That asymmetry —
   `10.0.5.10:8443` ALLOW next to `api.acme.com:8443` DENY in the same
   manifest — is the specification, not an inconsistency to clean up
   later.

## FORK-S — what a URL target may authorize from

**DEFAULT (1) taken:** only the URL's host component and effective
port are consulted; path, query, fragment, and userinfo never
authorize anything. This is what actually closes F4 (`*acme.com*` must
not match `https://evil.net/?next=acme.com/x`) and the related
redirect/fragment/userinfo rows in §5.6 — none of them are matched
against the raw URL string unless the *pattern itself* is URL-shaped
(contains `"://"`), in which case the operator explicitly opted into
literal, path-aware matching (e.g. an explicit
`"https://host/v1/*"` entry, or CyberGym's own
`"http://localhost*"` covering its nonstandard port). That one
carve-out is not a FORK-S bypass — FORK-S governs what an *implicit*
hostname/glob pattern may infer from a URL target, not what an
operator spelled out directly.

## FORK-T — bundle id vs. hostname

The *issue*: `com.acme.mobile` (a real bundle id) and
`com.acme.evil.attacker.net` (an attacker's hostname) are both bare
dotted ASCII tokens — syntactically indistinguishable. §8.2 asks
whether this is safely decidable from the target string alone, and the
honest answer, confirmed against CyberGym's own fixture
(`com.kronos.cybergym.lab`, which contains nothing — no underscore, no
unusual character — that would let a cheap stdlib check tell it apart
from a hostname) is **no**. `classify_target` therefore never attempts
it: every bare token folds into `host` (§8.2's "cannot be decided
safely, denied by default" is the preferred answer, not a heuristic
that could authorize a hostname).

**DEFAULT (1) taken, but resolved on the *pattern* side instead of the
target side.** A trailing-`.*` pattern (`com.acme.*`, one literal
wildcard, at the end, no leading `*.`) is read as a bundle-id-style
entry whose wildcard may consume **exactly one further label — never a
multi-label hostname-style suffix**:

- `com.acme.*` / `com.acme.mobile` → remainder `"mobile"`, no dot → **ALLOW**.
- `com.acme.*` / `com.acme.evil.attacker.net` → remainder
  `"evil.attacker.net"`, has dots → **DENY** (F5, closed).

This rule only engages when the *target* is `host`-shaped (a bare
token) — a bundle id is never URL- or port-shaped in this codebase's
data model, so a trailing-`.*` pattern tested against any other target
shape (e.g. the pre-existing, unrelated `"10.0.*"` glob against an
`ip_port` target) falls through to the same plain, unrestricted glob
match it always used. This is a deliberate, narrower implementation of
option (1) than "classify the target as bundle_id" — it reaches the
exact same acceptance-matrix outcomes without ever guessing whether a
given string "really" is a bundle id.

## SPEC_BRIEF10.1 — the trailing-glob boundary rule

PR #12 (the section above) still matched a trailing `*` on a
host-shaped pattern by raw character prefix: `api.acme.com*` matched
`api.acme.com.attacker.net` and `api.acme.com-evil.net` alike — an
attacker-registerable domain, authorized by a pattern the operator
wrote thinking it meant "this one host." This is the one pattern
shape CyberGym's own signed manifest actually uses
(`localhost*`/`127.0.0.1*`/`http://localhost*`, to cover its
nonstandard 8091/4566 ports with no manifest edit), so it's the shape
most likely to be written by a real operator too.

**§1.1 — the boundary rule (operator-ratified, governing).** A
trailing `*` on a hostname/URL/IP-shaped target expands only at a
delimiter boundary: `:` (port), `/` (path), or end-of-string. It
never expands across a `.` into another DNS label, and never
mid-label. `api.acme.com*` covers `api.acme.com`,
`api.acme.com:<port>`, `https://api.acme.com/...`, and
`https://api.acme.com:<port>/...` — and nothing else.

**§1.2 — port semantics, Option A (operator-ratified DEFAULT).** A
trailing `*` after a complete host means *"this host, any port, any
path"* — deliberately wider than a bare host entry (rule 2 above,
standard ports only). The operator gets all-ports authorization by
typing `*`, never by accident, and the widening is bounded to that one
host by the boundary rule. **This is the documented meaning of a
trailing `*`:** writing `api.acme.com*` also authorizes `:22`, `:3389`,
`:5432` on that host — a real widening, taken on purpose so CyberGym's
own in-scope entries keep working with zero manifest edits. A bare
`api.acme.com` (no trailing `*`) still denies `:8443`, unchanged.

Option B (a trailing `*` is standard-port-only too, like a bare host)
was rejected: it breaks CyberGym's range (`localhost*` would stop
matching `:8091`), and recovering it needs `generate_scope_manifest.py`
edited and the manifest re-signed — both off-limits here.

**§1.3 — buckets and ARNs stay distinct from hostnames.**
`kronos-cybergym-*` must keep matching
`kronos-cybergym-general-secrets` — mid-label expansion, correct for a
bucket name, forbidden for a hostname. The boundary rule is therefore
selected by the *target's* shape (`classify_target`), never the
pattern's text: a hostname/URL/IP-shaped target gets §1.1's boundary
rule; a `bucket_name`/`arn`-shaped target keeps free glob expansion, as
before this amendment. A bucket/ARN pattern can never authorize a
hostname-shaped target as a result — its glob expansion is never even
attempted against one.

## FORK-U — a pattern with wildcards at both ends

`*.acme.com*` (leading subdomain wildcard AND a trailing one).
**DEFAULT (1) taken, unchanged:** PR #12's existing verdict is pinned
as-is — it already denies `api.acme.com:8443` (the `*.`-prefix path
checks for a literal trailing `*` in the hostname, which never occurs
in a real target, so it always falls through to deny) — and such a
pattern is **not** treated as a host pattern for trailing-glob
purposes; §1.2's "any port" rule does not apply to it. Option (2),
harmonizing it with §1.2 so it behaves like `api.acme.com*`, was
rejected: it is a widening with no demonstrated need, and widening is
the dangerous direction here.

## Exclusion vs. allow: the one asymmetry that must never be unified

| | Address-shaped pattern | Hostname-shaped pattern |
|---|---|---|
| **As an allow** | Port-blind (rule 7) | Port-gated: standard ports only, or the pattern's own explicit port (rules 2/4) |
| **As an exclusion** | Port-blind (rule 7, unaffected by exclusion/allow) | Port-blind (rule 6: deny is broad) |

An address-shaped pattern is *always* port-blind, allow or deny alike.
A hostname-shaped pattern is port-blind **only** as an exclusion —
narrow as an allow, broad as a deny. Collapsing either distinction
("a bare IP behaves like a hostname," or "allow and deny should be
symmetric") reintroduces exactly the bypass/over-match classes this
brief closes.

## Files

- `scope_guard.py` — `classify_target`, the per-shape match helpers,
  `_matches`, `ScopeGuard`, `scope_guard`. The six-brief (#4–#9)
  zero-line-diff streak on this file ends here, as intended.
- `manifest.py` — untouched; the signed-manifest schema does not
  change (guardrail 1). A manifest signed before this brief still
  verifies — see `tests/test_scope_guard.py`'s literal pre-captured
  signed-manifest fixture.
