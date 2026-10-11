"""The API tier (SPEC_BRIEF05 "API tier"). Deliberately split into:

- DOCUMENTED endpoints (/health, /items/{id}) — ordinary REST surface,
  visible in the OpenAPI schema at /docs and /openapi.json. This is what
  the ancestor-control runbook points RedAmon/PentAGI/Shannon at: a
  normal web API they CAN scan, so the mobile-origin chains are the only
  delta between them and KRONOS (SPEC_BRIEF05 "ALSO SHIP — the
  ancestor-control runbook").
- The UNDOCUMENTED endpoint (/internal/v1/admin/export) — Chain 1's
  target. `include_in_schema=False` keeps it out of /openapi.json
  entirely; it's only discoverable by extracting it from the mobile
  app's planted resources, which is exactly the point.

Real accept/reject, not a stub: the undocumented endpoint actually checks
the header against CHAIN1_API_KEY and returns 401 for anything else.
"""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException

# Chain 1's planted secret (SPEC_BRIEF05 "at least one plaintext
# secret"). Must match tests/fixtures-equivalent value planted into
# cybergym/mobile/apk_src/res/values/strings.xml and ground_truth.yaml —
# selftest.py asserts all three stay in sync.
CHAIN1_API_KEY = "CYBERGYM_FIXTURE_CHAIN1_API_KEY_4d2f8a91"

app = FastAPI(title="cybergym-api", description="CyberGym lab API tier (local-only, deliberately vulnerable)")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/items/{item_id}")
def get_item(item_id: int) -> dict:
    """An ordinary documented endpoint — present so the ancestor-control
    comparison has something normal for RedAmon/PentAGI/Shannon to find,
    same as KRONOS would. Not part of any planted chain."""
    return {"item_id": item_id, "name": f"item-{item_id}"}


@app.post("/internal/v1/admin/export", include_in_schema=False)
def admin_export(x_cybergym_key: str | None = Header(default=None)) -> dict:
    """Chain 1's target: an undocumented endpoint only discoverable from
    the mobile app's planted base URL + path. Real accept/reject —
    returns the "export" only for the exact planted key, 401 otherwise."""
    if x_cybergym_key != CHAIN1_API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing X-Cybergym-Key")
    return {"export": "chain-1 target reached", "classification": "internal-only"}
