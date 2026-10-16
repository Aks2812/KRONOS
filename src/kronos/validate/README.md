# Secret validation (Brief #3, Brief #8)

Advances a `SECRET` through the lifecycle Brief #1 fixed, by actually
testing it:

```
extracted  --(real successful auth, differentially proven)-->  validated
validated  --(authenticates_to target is in_scope)-->  reachable
```

`advance_secret_status` (`kronos.lifecycle`) is the only thing that ever
changes a `SECRET`'s status/confidence — this package calls it, never
re-implements it.

## Negative-control validation (Brief #8) — closing the single-arm FP

Before Brief #8, "real successful auth" meant a SINGLE arm: one 2xx (HTTP)
or one successful `ListObjectsV2` (cloud) was treated as proof on its own.
That is a real, reproducible false positive: CyberGym's own `GET /health`
returns `200 {"status": "ok"}` with **no auth required at all** — point
the old validator at it with a garbage secret and it reported the secret
live. On AWS-faithful error codes (Brief #7), `cloud_validator.py`'s old
`except (ClientError, BotoCoreError): live=False` collapse had the mirror
problem: it could never tell *no-credential* from *wrong-credential* from
*valid-credential-denied-this-bucket*, so it could never turn `AccessDenied`
into the positive evidence it actually is once denial codes are faithful.

Both validators now run a **differential**, not a single arm, and hand it
to `kronos.validate.controls.run_differential` — the one chokepoint that
decides the classification (mirrors the `scope_guard`/`advance_secret_status`
pattern: one rule, not reimplemented per caller):

| Kind | Arms | A↔B/C purpose |
|---|---|---|
| HTTP (`http_validator.py`) | A canonical (real secret), B negative control (derived, guaranteed-invalid, same shape) | does the target discriminate at all? |
| Cloud (`cloud_validator.py`) | A canonical, B bad-secret (real access key + derived wrong secret), C unknown-key (derived access key) | does it verify signatures? does it know this key? |

Classification (`kronos.validate.types.ValidationOutcome.classification`):
`live_discriminated`, `not_live`, `authenticated_not_authorized`,
`indiscriminate_target`, `self_request_malformed`, `inconclusive`. Only
`live_discriminated` sets `live=True` — enforced structurally in
`ValidationOutcome.__post_init__`, not just by convention: constructing
`live=True` with `discriminated=False` (or any classification other than
`"live_discriminated"`) raises `ValueError` immediately, for any caller,
forever.

**`authenticated_not_authorized` (FORK-M):** on the cloud matrix, `A
AccessDenied, B SignatureDoesNotMatch, C InvalidAccessKeyId` proves the
credential is genuinely real — the signature verified — but this
particular bucket denies it. The runner advances the secret to
`validated` (never further), attaches the (secret-free) arm evidence, and
writes **no** `authenticates_to` edge for that candidate. This is exactly
Brief #7 §0's over-privilege signal, now actually usable.

**Abstention (`not_live`, `indiscriminate_target`, `self_request_malformed`,
`inconclusive`):** never advances the secret, never attaches evidence,
never writes an edge — the secret stays exactly where it was.
`self_request_malformed` (any arm getting 400 `AuthorizationHeaderMalformed`)
is surfaced loudly in `detail`/`classification` but is never treated as a
target signal — it means *our own* request was broken, the false-negative
guard Brief #7 §3.1a exists to make possible.

**Negative-control derivation** (`derive_negative_control`,
`kronos.validate.controls`): deterministic (HMAC with a fixed
`KRONOS-NEGATIVE-CONTROL` domain-separation label — never random, never a
hardcoded sentinel a target could fingerprint), shape-preserving
(digit/upper/lower character classes preserved position-by-position,
punctuation kept literal), and structurally guaranteed to differ from the
real value at every varying position. Never logged, never equal to a real
secret, and arm evidence (`kronos.validate.controls.ArmResult`) carries
only labels/success/status/error-code — never a credential value.

**Budget (FORK-J):** `validation_attempts` still costs 1 per *candidate*
(unchanged); `tool_invocations` now costs the arm count for that secret's
kind — **2× for HTTP, 3× for cloud** — charged atomically, before the
validator call that runs the whole differential, so a `BudgetExceeded`
can never land mid-differential and leave a half-proof.

## Running it

```python
from kronos.validate import run_validation_pass

attempts = run_validation_pass(
    graph,              # an EngagementGraph, post-ingestion
    engagement_dir,     # the same dir store_evidence/get_evidence use
    cloud_proxy_endpoint="http://localhost:4567",  # omit to skip cloud candidates entirely
    http_hints={                                    # optional, per-endpoint overrides
        "http://example.com/admin": {"method": "POST", "header_name": "X-Api-Key"},
    },
)
```

Every `SECRET` with `status == "extracted"` is tried against its
candidate targets (`candidates.py`): `API_ENDPOINT`s the same
app/component also `references` (joined via the `leaks`/`references`
edges Brief #2's ingester already writes), and every `CLOUD_RESOURCE` in
the engagement (a credential's privilege is what's being tested, not
assumed — this is what lets an over-privileged credential's *second*
authorization surface as a real `authenticates_to` edge, not just a
missed check).

## The two invariants this package holds under adversarial input

1. **Scope-gated before any call.** `candidate.in_scope` is checked
   before the matching validator is even invoked — an out-of-scope
   target never gets a network/boto3 call, not just a withheld status
   change. `test_credential_is_never_sent_to_an_out_of_scope_target`
   proves this by mocking the validator callable itself and asserting
   zero calls.
2. **No live without real proof.** `ValidationOutcome.live` only comes
   from an actual HTTP/boto3 round trip (`http_validator.py` /
   `cloud_validator.py`); a connection error, timeout, or non-2xx/
   `AccessDenied` is "not live," never a crash and never a guess.

## Dispatch is by decoded VALUE shape, not `SECRET.kind`

Brief #2's mobile ingester only ever tags `kind` as `"api_key"`/
`"api_key_obfuscated"` — it never distinguishes a cloud credential pair.
`registry.classify_validator_kind` looks at the *decoded* secret value
itself: an `access_key:secret_key`-shaped pair (left >=8 chars, right
>=6 chars, split on the first `:`) dispatches to
`cloud_validator.validate_cloud_credential`; anything else non-empty
dispatches to `http_validator.validate_api_token`; empty/unknown shape
gets no validator and the secret stays `extracted`.

## Files

- `types.py` — `CandidateTarget`, `ValidationOutcome` (structurally
  enforces the `live` ⟹ `discriminated` invariant, Brief #8).
- `controls.py` — `derive_negative_control`, `run_differential`: the one
  chokepoint for negative-control derivation and differential
  classification (Brief #8).
- `registry.py` — `classify_validator_kind`, `get_validator`.
- `http_validator.py` — the api_key/token/bearer validator (two-armed
  differential, Brief #8).
- `cloud_validator.py` — the aws/cloud-credential-pair validator
  (three-armed differential, Brief #8).
- `candidates.py` — candidate-target discovery from existing edges.
- `runner.py` — `run_validation_pass`, the orchestrator and the sole
  place scope-gating + lifecycle advancement happen for this brief.
