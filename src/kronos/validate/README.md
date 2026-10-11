# Secret validation (Brief #3)

Advances a `SECRET` through the lifecycle Brief #1 fixed, by actually
testing it:

```
extracted  --(real successful auth)-->  validated
validated  --(authenticates_to target is in_scope)-->  reachable
```

`advance_secret_status` (`kronos.lifecycle`) is the only thing that ever
changes a `SECRET`'s status/confidence — this package calls it, never
re-implements it.

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

- `types.py` — `CandidateTarget`, `ValidationOutcome`.
- `registry.py` — `classify_validator_kind`, `get_validator`.
- `http_validator.py` — the api_key/token/bearer validator.
- `cloud_validator.py` — the aws/cloud-credential-pair validator.
- `candidates.py` — candidate-target discovery from existing edges.
- `runner.py` — `run_validation_pass`, the orchestrator and the sole
  place scope-gating + lifecycle advancement happen for this brief.
