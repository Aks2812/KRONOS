"""The ground-truth table the SigV4 proxy checks requests against. This is
the ONLY place the lab's cloud credentials/authorization rules are
defined — ground_truth.yaml's cloud entries must match this exactly (a
self-test assertion enforces that, so they can't drift apart silently).

NOT a general IAM policy engine — a flat access_key_id -> (secret,
allowed buckets) table. See cybergym/README.md "Cloud tier enforcement
model" for why this is the honest scope.
"""

from __future__ import annotations

KNOWN_SECRETS: dict[str, dict] = {
    "CYBERGYMGENERALUSER0001": {
        "secret_access_key": "cybergym-fixture-general-secret-7f3a9c1e",
        "allowed_buckets": {"kronos-cybergym-general"},
    },
    "CYBERGYMADMINUSER0001": {
        # Over-privileged by design (Chain 3): allowed on BOTH buckets,
        # unlike the general user above which is scoped to one.
        "secret_access_key": "cybergym-fixture-admin-secret-b82d4f60",
        "allowed_buckets": {"kronos-cybergym-general", "kronos-cybergym-admin-secrets"},
    },
}
