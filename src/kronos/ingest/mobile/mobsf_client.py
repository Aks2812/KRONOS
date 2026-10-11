"""Minimal MobSF REST API client (SPEC_BRIEF2: "MobSF is the analysis
anchor. Prefer orchestrating MobSF... over reimplementing decompilation").

Treats every MobSF response as untrusted (SPEC_BRIEF2 security lens): this
module only ever pulls out specific, known JSON fields by name — it never
passes a MobSF response dict through wholesale to anything that builds
graph props. A crafted/compromised MobSF response can, at worst, cause this
client to find nothing useful; it cannot inject arbitrary keys into the
graph (see parser.py, which only ever reads the named fields this module
returns, never arbitrary dict contents).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

_DEFAULT_TIMEOUT = 10
_SCAN_TIMEOUT = 300  # static analysis of a real APK can take a while


class MobSFUnreachable(RuntimeError):
    """Raised when MobSF can't be reached at all (connection refused,
    DNS failure, timeout) — distinct from a reachable-but-erroring MobSF,
    so callers can decide whether to degrade gracefully (unreachable) or
    treat a real API error as noteworthy."""


class MobSFClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = _DEFAULT_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self.api_key}

    def is_reachable(self) -> bool:
        try:
            requests.get(self.base_url, timeout=self.timeout)
        except requests.RequestException:
            return False
        return True

    def upload(self, apk_path: str | Path) -> str:
        """Uploads the APK, returns MobSF's file hash (its handle for the
        rest of the scan workflow)."""
        apk_path = Path(apk_path)
        with apk_path.open("rb") as fh:
            resp = requests.post(
                f"{self.base_url}/api/v1/upload",
                headers=self._headers(),
                files={"file": (apk_path.name, fh, "application/vnd.android.package-archive")},
                timeout=self.timeout,
            )
        resp.raise_for_status()
        data = resp.json()
        file_hash = data.get("hash")
        if not file_hash:
            raise RuntimeError(f"MobSF upload response had no 'hash' field: {data!r}")
        return str(file_hash)

    def scan(self, file_hash: str) -> None:
        """Triggers static analysis for an already-uploaded file. Blocking —
        MobSF's /api/v1/scan endpoint runs the scan synchronously."""
        resp = requests.post(
            f"{self.base_url}/api/v1/scan",
            headers=self._headers(),
            data={"hash": file_hash},
            timeout=_SCAN_TIMEOUT,
        )
        resp.raise_for_status()

    def report_json(self, file_hash: str) -> dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/api/v1/report_json",
            headers=self._headers(),
            data={"hash": file_hash},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()


def extract_secrets_from_report(report: dict[str, Any]) -> list[dict[str, str]]:
    """Pulls only the named fields this module trusts out of a MobSF JSON
    report's hardcoded-secrets finding (MobSF's own field name varies by
    version; checks the documented ones defensively). Returns plain
    {"source_field": ..., "value": ...} dicts — never the raw report dict
    itself, and never a key name taken from report content."""
    out: list[dict[str, str]] = []
    secrets = report.get("secrets")
    if isinstance(secrets, list):
        for entry in secrets:
            if isinstance(entry, str):
                out.append({"source_field": "secrets", "value": entry})
    return out


def extract_endpoints_from_report(report: dict[str, Any]) -> list[dict[str, str]]:
    """Same trust model as extract_secrets_from_report: only known field
    names, only string values, never the raw dict passed through."""
    out: list[dict[str, str]] = []
    urls = report.get("urls")
    if isinstance(urls, list):
        for entry in urls:
            if isinstance(entry, dict):
                url_list = entry.get("urls")
                if isinstance(url_list, list):
                    out.extend({"source_field": "urls", "value": u} for u in url_list if isinstance(u, str))
            elif isinstance(entry, str):
                out.append({"source_field": "urls", "value": entry})
    return out
