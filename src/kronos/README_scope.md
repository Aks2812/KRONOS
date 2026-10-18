# Scope guard (SPEC_BRIEF10 / FORK-2: shape-aware matching; SPEC_BRIEF10.1: trailing-glob boundary rule; SPEC_BRIEF10.2: explicit-port URL patterns; SPEC_BRIEF10.3: node-type-aware dispatch; SPEC_BRIEF10.4: scope_key dispatch, evidence-only shape families, path-blind exclusions, FORK-2's closing piece)

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

## SPEC_BRIEF10.2 — `scheme://host:port*` means exactly that host, that port

A trailing `*` in a pattern that already names an explicit port
(`http://localhost:8091*`, the shape CyberGym's own 8091/4566
nonstandard ports made necessary) is **not** the same shape as the
bare-host trailing glob in §1.2 above, and §10.1's build left it on
`_matches_url_pattern`'s literal whole-string `fnmatch` — matching by
raw character prefix, which an attacker can satisfy without ever
owning `localhost`: a userinfo form
(`http://localhost:8091@evil.net/x`, where `evil.net` is the real
host), a lookalike "port" (`http://localhost:8091.attacker.net/x`,
`http://localhost:8091evil.net/x`), or a different numeric port that
merely shares the same leading digits (`http://localhost:80915/x`) all
share that literal prefix.

**The fix:** `scheme://host:port*` means that scheme, that host, that
**exact** port, any path/query/fragment — compared structurally, never
by raw string prefix:

- The target's host comes from `urlsplit().hostname`, so userinfo
  resolves to the real host — the same structural comparison
  `_matches_explicit_port_pattern` already used for the non-URL
  `host:port` pattern shape, routed through the identical
  `_host_port_scheme` helper.
- The port must equal the pattern's port exactly. A target whose
  "port" fails to parse (`8091.attacker.net`, `8091evil.net`, or simply
  out of range like `80915`) has no port at all under
  `urlsplit().port` and therefore never matches.
- The scheme must also match exactly (`https://` never satisfies an
  `http://...*` entry).
- Path, query and fragment stay unrestricted once scheme, host and
  port all match (§1.1 rule 3 — scope is host-level).
- **As an exclusion**, this pattern stays port-blind and scheme-blind
  (§1.1 rule 6, deny is broad): `excluded = ["http://localhost:8091*"]`
  still denies `http://localhost:9091/x` and `http://localhost/x`, not
  only the exact-port form.

**H2 — out of scope, deliberately.** The same brief that reported this
also measured that every single-label bare hostname (`localhost`,
`kronos-cybergym-general-secrets`) gets `classify_target`'s
`bucket_name` shape, which is a separate, broader defect needing
`graph.py` in its file allowlist. SPEC_BRIEF10.2 fixes the
explicit-port URL pattern shape only; H2 has its own, not-yet-written
brief, and **FORK-2/issue #2 stays open** until it also closes.

## SPEC_BRIEF10.3 (FORK-2's final piece) — node-type-aware dispatch

Two defects remained after #10.2, both traced to one root cause: the
matcher only ever had the *target string* to classify, and a dot-free
bare token (`localhost`, `kronos-cybergym-general-secrets`) is
genuinely ambiguous from the string alone -- both get `classify_target`'s
`"bucket_name"` shape (§1.3), which is correct for a bucket and wrong
for a hostname. `localhost*` wrongly authorized `localhostevil` and
`localhost-evil` (**H2**); `jenkins*` would do the same to
`jenkins-prod` for any internal single-label hostname. Separately,
`excluded = ["http://localhost:8091*"]` denied the URL form of that
host but not its bare `localhost:8091`/`localhost` forms (**H3**) --
Brief #10 §1.1 rule 6 ("every port, scheme, path, *and
representation*") was under-implemented across shape boundaries.

**The fix: `node_type` is now a required keyword argument** on both
`ScopeGuard.is_in_scope` and the module-level `scope_guard` -- the one
signal that *does* disambiguate `localhost` (a `HOST`) from
`kronos-cybergym-general-secrets` (a `CLOUD_RESOURCE`), carried from
`graph.py`'s own `upsert_node(type, id, props, scope_key)` call, which
already has it. No default, no permissive fallback: an unrecognised,
empty, or `None` `node_type` denies unconditionally, before any
pattern is even consulted (`NODE_TYPE_SHAPES.get(node_type)` falsy ->
immediate `False`). A permissive-by-omission path is exactly how H2
happened, so this one has none.

**`NODE_TYPE_SHAPES`** (owned by `scope_guard.py`, not `graph.py` --
the guard owns scope policy, the graph only reports what kind of node
it is holding) is each node type's permitted target-shape family:

| node type | permitted shapes | evidence |
|---|---|---|
| `HOST` | `host`, `ip`, `host_port`, `ip_port` | `canonical.py`: HOST ids ARE the hostname/IP text |
| `SERVICE` | `host`, `ip`, `host_port`, `ip_port` | SPEC.md's `host:port`/`ip:port` dedup convention |
| `WEB_ENDPOINT` | *(none)* | SPEC_BRIEF10.4 §1.2/FORK-W: corrected from 10.3's `{"url"}`, which was assigned by analogy to API_ENDPOINT (§0.3 D2) -- no production ingester exists, and its only documented key (`canonical_key_for_web_endpoint`) is a *merge* key (`reconcile/runner.py:84`), never a node id, classifying as `"unknown"` anyway |
| `API_ENDPOINT` | `url` | `ingest/mobile/parser.py:276`: `id=found.url` |
| `CLOUD_RESOURCE` | `bucket_name`, `arn` | `validate/candidates.py`'s `_all_cloud_resources`; **the only type with free mid-token glob expansion** |
| `MOBILE_APP` | `host` | `id=bundle_id`, a dotted token `classify_target` resolves to `"host"` (never literal `"bundle_id"` -- FORK-T) |
| `MOBILE_COMPONENT` | `host` | `id=f"{bundle_id}/{component.name}"`, same dotted-token shape |
| `SECRET` | *(none)* | SPEC_BRIEF10.4 §1.1/§1.2/FORK-Y: corrected from 10.3's `{"host"}`, which was fitted to make the scope_key path work rather than evidence about SECRET's own id (§0.3 D1) -- now that `is_in_scope` tells id and scope_key apart, SECRET's own sha256-derived id matches no shape family here; every real call site sets `scope_key=bundle_id` regardless, so this denies nothing in production |
| `PARAMETER` | *(none)* | §1.4: an opaque name, never glob-authorized regardless of shape |
| `IDENTITY` | *(none)* | FORK-W(2): zero production `upsert_node` call sites, no id convention ever established |
| `TECHNOLOGY` | *(none)* | FORK-W(2): same |
| `FINDING` | *(none)* | FORK-W(2): same -- and its one documented id formula (`canonical_key_for_finding`) is itself unreachable today, no ingester populates it |
| `ENGAGEMENT` / `EVIDENCE` | *(absent)* | `graph.py`'s `_ALWAYS_IN_SCOPE_TYPES`/`_NO_IN_SCOPE_COLUMN_TYPES` bypass this guard entirely, unchanged |

`classify_target` itself is untouched -- still a pure, node-type-blind
function. `_effective_shape(target, node_type)` is the new, thin layer
in front of it: a dot-free raw `"bucket_name"` shape is corrected back
to `"host"` for every node type except `CLOUD_RESOURCE`. This is what
lets `kronos-cybergym-*` keep matching
`kronos-cybergym-general-secrets` under `CLOUD_RESOURCE` while
`localhost*` stops over-matching under `HOST` -- the exact two cases
H2 could not tell apart from the string alone.

**Exclusions stay completely independent of `node_type`** (§1.3) --
checked first, before the type gate even runs, so a type mismatch (or
an unrecognised type) never causes an exclusion to be skipped. Fixing
H3 meant widening the *exclusion* side of the two pattern shapes that
had a hard `shape != "url"` gate (`_matches_explicit_port_url_pattern`,
`_matches_trailing_host_glob`'s `scheme://host*` case) to accept any
host-ish shape and compare host identity alone, scheme- and
port-blind -- including the dot-free `"bucket_name"` raw shape, which
needed `_host_port_scheme` taught to treat it as a plain host text too
(exclusion-only; the allow side never sees `"bucket_name"` as `shape`
at all, since it is always pre-corrected by `_effective_shape` first).

**FORK-V (DEFAULT 1, taken):** the module-level `scope_guard(target,
manifest)` helper also gained a required `node_type` kwarg, matching
`is_in_scope` -- fail-closed by construction beats a second,
permissive-by-omission path with its own rules. This is a **documented
conflict with SPEC.md's "SCOPE GUARD" section**, which still reads
`scope_guard(target, manifest)` (two positional arguments, no type);
SPEC.md is outside this brief's file list, so the conflict is recorded
here rather than resolved by editing it.

**FORK-W (DEFAULT 1 with evidence, but (2) taken for all three
candidates):** `SECRET`/`IDENTITY`/`TECHNOLOGY`/`FINDING` were each
checked against this branch's actual source rather than assigned a
family by analogy. `SECRET` has real evidence (see table) and got a
family; `IDENTITY`/`TECHNOLOGY`/`FINDING` have none at all -- zero
production `upsert_node` call sites, grep-verified -- so each denies
unconditionally rather than guessing.

## SPEC_BRIEF10.4 (FORK-2's closing piece) — scope_key dispatch, evidence-only shape families, path-blind exclusions

seq 5 independent review of 10.3's PR (#13) returned FAIL: 6 regressions in
`tests/`, traced to two real defects in 10.3's own §1.2 table (D1/D2 --
see `DECISIONS.md`), plus one deny-side gap 10.3's own §1.3 fix left
half-implemented.

### §1.1 — `scope_key` is gated by its own shape, independent of `node_type`

**D1:** `graph.py:140` gates `scope_key or id` -- a *string*, not
necessarily an id. 10.3's `NODE_TYPE_SHAPES` table is, by its own
prose, about how a type's **id** is actually produced; when the string
is a `scope_key` instead, that table does not describe it at all. 10.3
worked around this once (SECRET's row was fitted to the shape its
scope_key carries, not evidence about its id -- see table above), which
is a per-row patch, not a fix for the structural problem.

**The fix:** `is_in_scope` (and the module-level `scope_guard`) now
take a second required keyword argument, `target_kind` (`"id"` or
`"scope_key"`), carried all the way from `graph.py`'s own `scope_key or
id` resolution (§1.5 -- that precedence itself is unchanged, this is
purely a one-kwarg addition at the one call site). When the target is
a `scope_key`, the node-type shape-family filter (`NODE_TYPE_SHAPES`)
is never consulted at all -- a scope_key is gated purely on its own
shape (`_scope_key_shape`), computed independently of `node_type`.
Everything else is unchanged: boundary rule, standard-port gate, the
`CLOUD_RESOURCE`-only mid-token expansion, and excluded-first
default-deny all still apply on the id path exactly as before; an
unrecognised, empty, or `None` `node_type` still denies before any
pattern is consulted, on *either* path (fail-closed, §2.4).

`_scope_key_shape` differs from `_effective_shape` in exactly one way:
with no `node_type` signal to consult, a dot-free string's ambiguous
`"bucket_name"` classification always resolves to `"host"` (the
boundary-rule-governed reading), never `"bucket_name"`'s free
mid-token expansion -- this is strictly a change to *which table
governs which string*, never a widening of any pattern rule
(guardrail §9). A `CLOUD_RESOURCE` whose `scope_key` is `localhost`
becomes governed by the host boundary rule: narrower than the
bucket-glob treatment the identical string gets on the id path, never
looser. An unambiguous shape (an explicit `arn:...` scope_key, for
instance -- exactly what CyberGym's own validation run uses, §0.4)
passes straight through and keeps its free glob expansion unaffected.

### §1.2 — no row may be assigned by analogy; no evidence means an empty family

**D2:** 10.3's `WEB_ENDPOINT` row (`{"url"}`) was assigned by analogy
to `API_ENDPOINT`'s real evidence, FORK-W's exact violation. Measured:
there is no production `WEB_ENDPOINT` ingester anywhere in `src/` or
`cybergym/`; its only documented key, `canonical_key_for_web_endpoint`,
is a *merge* key consumed by `reconcile/runner.py:84`, never a node
id; and that key's own shape classifies as `"unknown"`, not `"url"`.

This generalises 10.3's own FORK-W rule (already applied to
`IDENTITY`/`TECHNOLOGY`/`FINDING`) into the table's construction rule,
with no exception: every row must be cited to a verified producing
call site; a canonical/merge key is never citable evidence for an id;
a type with no production producer and no established id convention
gets `frozenset()`, denying unconditionally. `WEB_ENDPOINT` and
`SECRET` (§1.1, once the scope_key justification was gone) both become
`frozenset()` under this rule -- see the table above for the full,
per-row account.

### §1.3 — exclusions are shape-, port-, scheme- **and path-blind**, closing 10.3's own H3 fix

10.3's H3 fix widened an exclusion's cross-shape host-identity
comparison for the *simple* explicit-port and trailing-glob pattern
shapes, but a URL exclusion pattern that itself carries a path
(`http://localhost:8091/internal/*`) still fell through to
`_matches_url_pattern`'s literal, path-aware `fnmatch` -- so a *more*
specific exclusion pattern produced a *narrower* deny than the
path-free form of the identical pattern already gave: measured,
`http://localhost:8091/internal/*` let `localhost`,
`localhost:8091`, and `http://localhost:8091/other` all through, even
though `http://localhost:8091*` already denied every one of them.

**The fix:** on the exclusion side only, such a pattern is reduced to
its host/address identity -- scheme, port, path, query, and fragment
(FORK-Z, DEFAULT yes) are all discarded via `urlsplit().hostname`,
exactly like every other exclusion shape in this module -- and
compared against any host-ish identity the target carries. The allow
side is **completely unchanged**: `_matches_url_pattern`'s literal,
path-aware behaviour still governs an explicit allow entry that spells
a path out (this is not a FORK-S bypass -- FORK-S governs what an
*implicit* pattern may infer from a URL target, never what an operator
explicitly wrote).

### FORK-X / FORK-Y / FORK-Z

- **FORK-X (DEFAULT, taken):** the id/scope_key distinction is carried
  as a new *required* keyword argument, `target_kind` -- no default,
  so no call site can silently fall back to the wrong table.
- **FORK-Y (DEFAULT, taken):** `SECRET`'s row is re-derived to
  `frozenset()` rather than kept at `{"host"}` -- its real id shape
  (sha256-derived) matches no pattern family this module has, and
  every production SECRET call site sets `scope_key` regardless, so
  this denies nothing real.
- **FORK-Z (DEFAULT yes, taken):** the exclusion-side host-identity
  comparison also discards a URL pattern's query/fragment, by the same
  rule-6 reasoning. In practice this required no extra code:
  `urlsplit().hostname` never included them to begin with.

### The live-use gate (§6, byte-verbatim from SPEC_BRIEF10.5)

<!-- BEGIN SPEC_BRIEF10.5 §6 GATE (byte-verbatim; tests/test_scope_guard.py compares) -->
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
<!-- END SPEC_BRIEF10.5 §6 GATE -->

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
