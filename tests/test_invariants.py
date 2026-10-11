"""The 5 spec-named invariant tests (Brief #1 Deliverables #4).

These are safety invariants, not coverage theater: each one pins down a
hard rule from SPEC.md's VALIDATION LIFECYCLE / SCOPE GUARD sections that
must be enforced in code, not just documented. They are added task by
task, as each task's work makes the behavior they pin down possible.
"""

from datetime import datetime, timedelta, timezone

import pytest

from kronos.manifest import ManifestError, load_and_verify


def test_invariant_expired_or_unsigned_manifest_rejected(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    now = datetime.now(timezone.utc)
    expired = manifest_factory(engagement={
        "window_start": (now - timedelta(days=10)).isoformat(),
        "window_end": (now - timedelta(days=1)).isoformat(),
    })
    with pytest.raises(ManifestError):
        load_and_verify(expired, pub)

    tampered = manifest_factory().replace("Acme Corp", "Evil Corp")
    with pytest.raises(ManifestError):
        load_and_verify(tampered, pub)
