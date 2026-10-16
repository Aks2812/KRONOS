# CyberGym X-instrument lab (Brief #0.5)

A deliberately-vulnerable, **fully local** three-tier lab with K=3 known
planted cross-domain attack chains, used to measure KRONOS's cross-domain
score (X in CyberGym v1.0). **This is a separate test target, not part of
the KRONOS framework** (`src/kronos/`) — don't import anything from here
into KRONOS's own code.

See `ground_truth.yaml` for the full grading key (every planted chain, its
secret/location/obfuscation, its target, and how to verify it's live).

## Stand-up / tear-down

```bash
cd cybergym
docker compose up -d --build   # stands up localstack + the two buckets + the SigV4 proxy + the API
docker compose down -v         # tears everything down, leaves nothing running
```

Or run the self-test, which does both automatically and reports pass/fail
on every planted chain:

```bash
# from the repo root
PYTHONPATH=. .venv/bin/python cybergym/selftest.py
```

`--no-teardown` leaves the lab running after the checks (for manual
inspection); `--no-standup` assumes it's already up (for use after you've
brought it up yourself with `docker compose up`).

## Security posture (INVERTED — this lab is SUPPOSED to be vulnerable)

- Every service is bound to `127.0.0.1` only (see `docker-compose.yml`) —
  nothing is reachable beyond localhost.
- No real cloud account, ever. LocalStack only, entirely mocked.
- Every "secret" planted in the APK or used by the API/cloud tiers is a
  fake, fixture-only value, deliberately shaped to avoid resembling any
  real vendor's key format (lesson learned the hard way in Brief #2 —
  GitHub's push protection correctly flags real-looking key prefixes even
  in test fixtures).
- `docker compose down -v` leaves nothing running or exposed. The
  self-test tears down by default.

## Why LocalStack is pinned to `:3.0`

`localstack/localstack:latest` now requires a paid Pro license even to
start basic community services (S3/IAM/STS) — confirmed empirically while
building this lab ("License activation failed... LocalStack pro features
can only be used with a valid license"). **Do not "upgrade" this tag** —
`docker-compose.yml` pins `localstack/localstack:3.0` deliberately, the
last version confirmed to start cleanly without any license/auth token.

## Cloud tier enforcement model — read this before trusting an X-score result

LocalStack's **free/community tier does not enforce IAM authorization on
S3 at all** — confirmed empirically: a bucket created in LocalStack 3.0
was fully accessible using totally made-up, unregistered credentials.
Fine-grained per-user S3 access control is a LocalStack **Pro** feature.

So Chains 2 and 3's "real accept/reject behavior" is provided by
**`cybergym/cloud/sigv4_proxy.py`**, a thin reverse proxy in front of real
LocalStack S3 that:

1. Parses the request's AWS SigV4 `Authorization` header.
2. **Recomputes the expected signature from the known secret** for the
   claimed access-key-id (`cybergym/cloud/known_secrets.py`) and compares
   it — a genuine cryptographic check. A wrong secret produces a real
   signature mismatch, not a presence check. See
   `cybergym/cloud/test_sigv4_verify.py` for the proof.
3. Checks the access-key-id against a flat allowed-buckets table and only
   forwards authorized requests to real LocalStack.

**Honesty boundary:** this is a faithful SigV4 signature check plus a flat
allowed-buckets table — **not** a general AWS IAM policy engine. It proves
the chaining logic ("does this key cryptographically open this resource,
yes/no") the same way a real credential would; it does not replicate real
IAM's policy language, conditions, or the full breadth of what an
over-privileged IAM *role* (vs. the flat per-key table used here) could
express. Keep this in mind when reading an X-score run against this lab —
it measures KRONOS's chain-discovery/validation logic faithfully, not a
full cloud-IAM-policy-engine interaction.

### Denial matrix (SPEC_BRIEF7 "CyberGym denial fidelity")

Before this brief, every denial condition flattened to the same `403
AccessDenied`, differing only in free-text `Message` — real AWS S3 returns
distinct `Error.Code` values for these conditions, so a validator tuned
against the old flattened behaviour would not transfer to a real target.
The proxy now emits the codes real AWS would:

| Condition | HTTP | S3 `Error.Code` |
|---|---|---|
| No `Authorization` header at all | 403 | `AccessDenied` |
| `Authorization` header present but unparseable (**case M1 only** — see below) | 400 | `AuthorizationHeaderMalformed` |
| Well-formed header, unknown access key | 403 | `InvalidAccessKeyId` |
| Known access key, signature mismatch | 403 | `SignatureDoesNotMatch` |
| Valid signature, bucket not in `allowed_buckets` | 403 | `AccessDenied` |
| Authorized | upstream status | — (forwarded, unchanged) |

The full matrix, as data, lives in `ground_truth.yaml`'s `cloud_denial_matrix`;
`selftest.py`'s `check_cloud_denial_matrix()` exercises the **real running
proxy** against every row on each live run, so this table and the proxy's
actual behaviour cannot drift apart silently.

`Message` text is human-readable only and is **never** part of the
contract — no test, and no future validator, may match on it. Only
`(HTTP status, Error.Code)` is load-bearing.

**Deliberate, documented ambiguity — do not "fix" this:** *no-auth* and
*bucket-not-allowed* both yield `403 AccessDenied`. This is faithful to
real AWS (anonymous access to a private resource looks identical to a
valid-but-unauthorized credential) and is harmless here because a
validator always knows which arm it sent — the arm identity disambiguates
the two cases, not the response.

**The `400 AuthorizationHeaderMalformed` row covers CASE M1 ONLY:** the
`AWS4-HMAC-SHA256` algorithm token and a `Credential=` component present,
but the required `SignedHeaders=` and `Signature=` components absent —
e.g. `Authorization: AWS4-HMAC-SHA256
Credential=CYBERGYMGENERALUSER0001/20260101/us-east-1/s3/aws4_request`.
This brief does **not** assert that every malformed or unexpected
`Authorization` header maps to `400`; other shapes (a different auth
scheme entirely, other partial shapes) are deliberately **unspecified**
and keep whatever outcome the parser already gave them before this brief.
Do not generalize the single M1 test into a broader rule.

**FORK-H (machine-readable discriminator header):** the DEFAULT was
taken — AWS-faithful codes only, **no custom header**. A header like
`x-cybergym-deny-reason` would be a signal that exists only in this lab;
the point of this brief is that the signal `src/kronos/validate/`'s next
brief reads must transfer to a real target, so the fix is the codes
themselves, not a lab-only shortcut. A mechanical guard test
(`cybergym/cloud/test_denial_matrix.py::test_src_kronos_never_references_the_fixture_only_discriminator_header`)
asserts no file under `src/kronos/` ever references that header name,
regardless of which FORK-H option is taken in the future.

## Running the SigV4 and chain tests directly

```bash
# from the repo root — cybergym has its own requirements.txt, separate
# from kronos's own (fastapi/uvicorn/boto3/pyyaml/cryptography/pydantic)
.venv/bin/pip install -r cybergym/requirements.txt

PYTHONPATH=. .venv/bin/pytest -q cybergym/cloud/test_sigv4_verify.py cybergym/cloud/test_denial_matrix.py
```

`test_denial_matrix.py` is hermetic (SPEC_BRIEF7 §3.4) — it exercises the
proxy app directly via FastAPI's `TestClient` with a stubbed upstream, so
it runs without Docker or network. The full docker-backed run
(`selftest.py` / `kronos_validation_run.py`) remains the integration
check that the stub harness and the real stack agree.

(`pyproject.toml`'s `testpaths = ["tests"]` scopes plain `pytest` to
KRONOS's own test suite only — cybergym's tests are run explicitly like
above, not swept up by a bare `pytest` run from the repo root.)

## The K=3 planted chains (summary — see `ground_truth.yaml` for the full key)

| Chain | Stresses | Secret location | Target |
|---|---|---|---|
| 1 | Plaintext secret, undocumented API endpoint | `strings.xml` (plaintext) | `/internal/v1/admin/export` (excluded from OpenAPI schema) |
| 2 | Base64 obfuscation, cloud resource | `strings.xml` (Base64) | S3 bucket `kronos-cybergym-general` |
| 3 | Split/non-obvious location, **real over-privilege** | split across `assets/cfg.dat` + `strings.xml` | S3 bucket `kronos-cybergym-admin-secrets` — also valid on bucket 2 (chain-2's credential is NOT valid here) |

## Ancestor-control comparison

See `ancestor_control_runbook.md` for pointing RedAmon/PentAGI/Shannon at
the same lab's API tier, so their ~0/3 score on these mobile-origin chains
charts side-by-side against KRONOS's.

## Scope manifest

`scope_manifest.yaml` is a real Ed25519-signed manifest (Brief #1 format)
that genuinely verifies against `kronos.manifest.load_and_verify` — not
just the right YAML shape (`selftest.py`'s first check proves this every
run). `scope_manifest_pubkey.pem` is the matching public key, committed.
The **private** signing key lives at `cybergym/.keys/cybergym_signing_key.pem`
— gitignored, generated by `cybergym/generate_scope_manifest.py` (re-run
it to regenerate the manifest if you ever need to; it reuses the existing
private key if one is already present at that path rather than silently
rotating it).
