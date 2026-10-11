"""Lightweight, regex-based secret/endpoint extraction over decoded mobile
app text (resource strings, decompiled source) — an "apkleaks-style"
supplement used to fill gaps where MobSF's own findings are thin (SPEC_BRIEF2
"MobSF is the analysis anchor... supplement with lighter targeted
extractors"). This is NOT a general secret scanner: it looks at structured
(resource_name -> value) pairs and flags names that look secret-ish or
values that look URL-ish, nothing more.

Security note (SPEC_BRIEF2 "Security lens on the parser"): every value here
comes from an untrusted APK. This module only ever *reads* text and returns
plain dicts with a small, fixed set of keys (never the raw input dict
itself, never anything attacker-controlled used as a dict key) — the
caller (parser.py) is responsible for building NodeUpsert.props from named,
known-safe fields only, never by spreading a result dict directly. That is
what keeps a crafted resource value from ever reaching the graph as a
privileged prop (in_scope/status/confidence) — see
test_hostile_input in test_mobile_ingest.py.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass

# Resource names that suggest a secret/credential. Deliberately broad but
# bounded — this is a heuristic supplement, not the primary analysis path.
_SECRET_NAME_RE = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|credential|auth[_-]?key|access[_-]?key)",
    re.IGNORECASE,
)

_URL_RE = re.compile(r"https?://[^\s\"'<>]+")

# A conservative Base64 candidate: 16+ chars of the b64 alphabet, correctly
# padded. Deliberately does not try to be clever about unpadded/urlsafe
# variants — a missed obfuscated secret is far safer than a false-positive
# decode of ordinary text that happens to be in the b64 alphabet.
_B64_RE = re.compile(r"^[A-Za-z0-9+/]{16,}={0,2}$")

# Hard caps so a maliciously huge or deeply-crafted value can't make this
# module do unbounded work or blow up memory — hostile input must not crash
# the parser (SPEC_BRIEF2 security lens).
_MAX_VALUE_LEN = 20_000
_MAX_URLS_PER_TEXT = 200


@dataclass(frozen=True)
class FoundSecret:
    resource_name: str
    raw_value: str
    decoded_value: str
    obfuscation: str  # "none" | "base64"


@dataclass(frozen=True)
class FoundEndpoint:
    resource_name: str | None
    url: str


def _try_base64_decode(value: str) -> str | None:
    """Return the decoded text if `value` is plausibly a Base64-obfuscated
    secret (decodes cleanly to printable text), else None. Never raises —
    hostile/garbled input just fails to decode, which is a normal, expected
    outcome here, not an error."""
    if not _B64_RE.match(value):
        return None
    try:
        decoded_bytes = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        decoded_text = decoded_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not decoded_text.isprintable() or not decoded_text:
        return None
    return decoded_text


def extract_secrets_from_resources(resources: dict[str, str]) -> list[FoundSecret]:
    """Scan a resource_name -> value mapping (e.g. parsed strings.xml) for
    entries whose NAME looks secret-ish. Does not infer secrets from value
    shape alone (too many false positives) — matches SPEC_BRIEF2's listed
    source ("hardcoded API keys/tokens/credentials found in strings.xml").

    Detects both plaintext values and Base64-obfuscated ones (Brief #2
    scope: Base64 only; split/concatenated-string obfuscation is a tracked
    follow-up, see tests/fixtures/README.md).
    """
    found: list[FoundSecret] = []
    for name, value in resources.items():
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        if not _SECRET_NAME_RE.search(name):
            continue
        value = value[:_MAX_VALUE_LEN]
        decoded = _try_base64_decode(value)
        if decoded is not None:
            found.append(FoundSecret(resource_name=name, raw_value=value, decoded_value=decoded, obfuscation="base64"))
        else:
            found.append(FoundSecret(resource_name=name, raw_value=value, decoded_value=value, obfuscation="none"))
    return found


def extract_endpoints_from_resources(resources: dict[str, str]) -> list[FoundEndpoint]:
    """Scan resource values for http(s) URLs (SPEC_BRIEF2: "base URLs and
    API endpoints referenced in the app (including undocumented/internal
    hosts)"). Bounded per-value match count so a crafted value packed with
    thousands of fake URLs can't cause unbounded output."""
    found: list[FoundEndpoint] = []
    for name, value in resources.items():
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        value = value[:_MAX_VALUE_LEN]
        for match in list(_URL_RE.finditer(value))[:_MAX_URLS_PER_TEXT]:
            found.append(FoundEndpoint(resource_name=name, url=match.group(0)))
    return found
