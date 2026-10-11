# Findings Graph Core + Validation Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build KRONOS's Kùzu-backed findings graph: per-engagement DB init, signed-manifest scope guard, the full node/edge schema, an evidence-gated validation lifecycle for SECRET and FINDING that makes confidence inflation structurally impossible, a read-only query interface (incl. cross-domain `find_paths`), and one reference ingester proving the ingestion contract end-to-end (mobile secret → leaks edge → chain to cloud).

**Architecture:** Each engagement gets one isolated Kùzu DB file. A `ScopeGuard` compiled from a signature- and window-verified manifest is the *only* place `in_scope` gets stamped, at node-creation time. A `lifecycle` module is the *only* code path allowed to change `SECRET.status` / `FINDING.status` / `confidence` — it enforces the transition table, the evidence gate, and the scope-anchor rule before writing, and derives confidence from status rather than accepting it as input. `query.py` is the only read surface agents will ever see. An `ingest()` dispatch contract turns raw tool output into upsert operations; only a hardcoded "reference" parser is implemented this brief.

**Tech Stack:** Python 3.11+ (runtime is 3.13), `kuzu` 0.11.x (embedded Cypher, confirmed: multi-pair `CREATE REL TABLE GROUP`, multi-statement `execute()`, `CREATE ... IF NOT EXISTS`, parameterized queries, variable-length paths with inline node predicates `[r* 1..n (r,n | WHERE n.in_scope = true)]`, and `ALL SHORTEST` are all supported in this version), `pydantic` v2 for the manifest model, `cryptography` (Ed25519) for manifest signatures, `PyYAML`, `pytest`.

**Spec:** [`SPEC.md`](../../../SPEC.md) (Brief #1)

## Global Constraints

- Python 3.11+; no network calls anywhere in this module.
- Graph store is Kùzu only, one DB file per engagement, no server — do not introduce Neo4j/SQLite.
- Scope is enforced in code at the data/tool boundary; `scope_guard(target, manifest)` is the only function that may stamp `in_scope`.
- SECRET.value_ref is a sha256 pointer — plaintext secret values are never written into the graph.
- Confidence is always derived from status via `derive_confidence`; no code path accepts a caller-supplied confidence value for SECRET/FINDING.
- `FINDING -> reported` requires `status == exploited` AND `>=1` EVIDENCE node. No exceptions.
- A SECRET anchors a reported finding only if `status == reachable` AND its `authenticates_to` target has `in_scope == true`.
- Out-of-scope nodes may be recorded but must never be able to anchor a finding or be returned as an action target.
- No LLM calls, no agents, no real parsers beyond the one reference ingester, no dynamic/Frida, no reporting/orchestration.
- Every non-trivial autonomous decision goes in `DECISIONS.md` at repo root.

## Review Focus

- **Malformed manifest YAML** (not just "unsigned") — spec only says "reject unsigned/invalid"; a bad YAML parse or missing required field must raise a clear `ManifestError`, not propagate a raw `yaml.YAMLError`/`KeyError`. Covered in Task 1.
- **Excluded-first glob ordering under overlap** — an in-scope wildcard (`*.example.com`) and a narrower excluded entry (`internal.example.com`) must deny the narrower target even though it also matches the broader allow glob. Covered in Task 2.
- **CIDR scope entries** — spec explicitly lists CIDR as a supported scope glob form; plain string globbing would silently mis-handle `10.0.0.0/24` vs `10.0.1.5`. Covered in Task 2.
- **Idempotent re-ingestion** — spec requires upserts to MERGE/dedup ("same host:port updates, never duplicates"); running `ingest()` + `apply_upserts()` twice on identical raw input must not create duplicate nodes/edges. Covered in Task 7.
- **Invalid/backward lifecycle transitions** — e.g. `SECRET: dead -> validated`, `FINDING: reported -> hypothesis`. These aren't named in the spec's 5 invariant tests but are exactly what "enforced, not just documented" implies; a silent no-op or silent acceptance is a gap. Covered in Task 4.

---

## File Structure

```
src/kronos/
  __init__.py
  manifest.py       # ScopeManifest model, canonicalize/sign/load_and_verify
  scope_guard.py     # ScopeGuard class + scope_guard(target, manifest)
  schema.py          # DDL constants + init_db()
  graph.py           # EngagementGraph: open/init, upsert_node/upsert_edge, execute()
  lifecycle.py        # transition tables, derive_confidence, advance_*_status, can_anchor_finding
  evidence.py         # store_evidence/get_evidence/attach_evidence (hash-addressed, immutable)
  query.py           # query_graph, get_evidence, find_paths, list_findings, list_secrets
  ingest.py          # NodeUpsert/EdgeUpsert, ingest(), apply_upserts(), reference ingester
  README.md          # package-level README (what/why, points at per-module READMEs)
tests/
  conftest.py
  test_manifest.py
  test_scope_guard.py
  test_schema_graph.py
  test_lifecycle.py
  test_evidence.py
  test_query.py
  test_ingest.py
  test_invariants.py   # the 5 named spec invariants, built up task by task
DECISIONS.md
requirements.txt / pyproject.toml
```

Module READMEs: `manifest.py`+`scope_guard.py` share one README (`src/kronos/README_scope.md`) since they're one trust boundary; `lifecycle.py` gets its own (the false-positive killer, deserves to stand alone); `graph.py`+`schema.py` share one; `query.py` and `ingest.py` each get a short one. Exact filenames decided and logged in DECISIONS.md — not a blocking choice.

## Global Interfaces (fixed now, used across tasks)

```python
# manifest.py
class ManifestError(Exception): ...
class ScopeManifest(pydantic.BaseModel):
    engagement_id: str; client: str; authorized_by: str
    window_start: datetime; window_end: datetime
    destructive_allowed: bool = False
    in_scope: list[str]; excluded: list[str]

def canonicalize(data: dict) -> bytes: ...
def sign_manifest(manifest_dict: dict, private_key: Ed25519PrivateKey) -> str: ...  # full YAML incl. signature:
def load_and_verify(yaml_text: str, public_key: Ed25519PublicKey) -> ScopeManifest: ...  # raises ManifestError

# scope_guard.py
class ScopeGuard:
    def __init__(self, manifest: ScopeManifest) -> None: ...
    def is_in_scope(self, target: str) -> bool: ...

def scope_guard(target: str, manifest: ScopeManifest) -> bool: ...  # exact spec name/signature

# schema.py
def init_db(db_path: str | Path) -> kuzu.Database: ...

# graph.py
class EngagementGraph:
    def __init__(self, db_path: str | Path, manifest: ScopeManifest) -> None: ...
    @classmethod
    def init_engagement(cls, db_path, manifest_yaml_text: str, public_key) -> "EngagementGraph": ...
    def upsert_node(self, type: str, id: str, props: dict, scope_key: str | None = None) -> None: ...
    def upsert_edge(self, label: str, from_id: str, from_type: str, to_id: str, to_type: str,
                     props: dict | None = None) -> None: ...  # Kuzu rel groups need both endpoint types
    def get_node(self, type: str, id: str) -> dict | None: ...
    def execute(self, query: str, params: dict | None = None): ...  # -> kuzu.QueryResult

# lifecycle.py
class LifecycleError(Exception): ...
def derive_confidence(entity_type: Literal["secret", "finding"], status: str, has_evidence: bool) -> int: ...
def advance_secret_status(graph: EngagementGraph, secret_id: str, new_status: str) -> None: ...
def advance_finding_status(graph: EngagementGraph, finding_id: str, new_status: str) -> None: ...
def can_anchor_finding(graph: EngagementGraph, secret_id: str) -> bool: ...

# evidence.py
def store_evidence(engagement_dir: Path, blob: bytes, kind: str) -> dict: ...  # {sha256, blob_path, kind, created_at}
def get_evidence(engagement_dir: Path, sha256: str) -> bytes: ...
def attach_evidence(graph: EngagementGraph, engagement_dir: Path, blob: bytes, kind: str,
                     target_type: Literal["finding", "secret"], target_id: str) -> str: ...  # -> sha256

# query.py
def query_graph(graph: EngagementGraph, node_type: str | None = None, filters: dict | None = None) -> list[dict]: ...
def find_paths(graph: EngagementGraph, from_type: str, to_type: str, max_hops: int = 5,
                only_in_scope: bool = True) -> list[dict]: ...  # [{nodes:[...ids], labels:[...], length:int}]
def list_findings(graph: EngagementGraph, status: str | None = None) -> list[dict]: ...
def list_secrets(graph: EngagementGraph, status: str | None = None) -> list[dict]: ...

# ingest.py
@dataclass
class NodeUpsert: type: str; id: str; props: dict; scope_key: str | None = None
@dataclass
class EdgeUpsert: label: str; from_id: str; to_id: str; props: dict | None = None

def ingest(raw_tool_output, tool_name: str, engagement: EngagementGraph) -> list[NodeUpsert | EdgeUpsert]: ...
def apply_upserts(engagement: EngagementGraph, upserts: list[NodeUpsert | EdgeUpsert]) -> None: ...
def ingest_reference_mobile_secret(bundle_id: str = "com.kronos.demo") -> list[NodeUpsert | EdgeUpsert]: ...
```

---

### Task 1: Project scaffolding + Manifest (signature & window verification)

**Files:**
- Create: `pyproject.toml`, `requirements.txt`
- Create: `src/kronos/__init__.py`, `src/kronos/manifest.py`
- Create: `tests/conftest.py`, `tests/test_manifest.py`, `tests/test_invariants.py`

**Interfaces:**
- Produces: `ManifestError`, `ScopeManifest`, `canonicalize`, `sign_manifest`, `load_and_verify` (see Global Interfaces). Produces pytest fixtures in `conftest.py`: `signing_keypair()` -> `(Ed25519PrivateKey, Ed25519PublicKey)`, `manifest_factory` -> callable `(**overrides) -> str` returning a signed YAML string with sane defaults (window covering "now", `in_scope=["*.example.com"]`, `excluded=[]`).

- [ ] **Step 1: Scaffold the package**

Create `pyproject.toml` (or `requirements.txt`, decide and log which) pinning `kuzu`, `pydantic`, `cryptography`, `PyYAML`, `pytest` to the versions already installed (`kuzu==0.11.3`, `pydantic==2.13.5`, `cryptography==50.0.1`, `PyYAML==6.0.1`, `pytest==9.1.1`). Create `src/kronos/__init__.py` (empty, or version string). Add a `pytest.ini`/`[tool.pytest.ini_options]` pointing `testpaths = ["tests"]` and `pythonpath` at `src`.

- [ ] **Step 2: Write `tests/conftest.py` fixtures**

```python
@pytest.fixture
def signing_keypair():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()

@pytest.fixture
def manifest_factory(signing_keypair):
    priv, _ = signing_keypair
    def _make(**overrides) -> str:
        from kronos.manifest import sign_manifest
        now = datetime.now(timezone.utc)
        data = {
            "engagement": {
                "id": "acme-2026", "client": "Acme Corp", "authorized_by": "Jane CISO",
                "window_start": (now - timedelta(days=1)).isoformat(),
                "window_end": (now + timedelta(days=30)).isoformat(),
                "destructive_allowed": False,
            },
            "scope": {"in_scope": ["*.acme.example.com"], "excluded": []},
        }
        data.update(overrides)
        return sign_manifest(data, priv)
    return _make
```
(Implementer fills in the exact nested-override merge if `overrides` targets a nested key — simplest correct behavior: shallow-merge top level, deep-merge `engagement`/`scope` dicts when both present.)

- [ ] **Step 3: Write the failing manifest tests**

```python
def test_valid_manifest_loads(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    yaml_text = manifest_factory()
    m = load_and_verify(yaml_text, pub)
    assert m.engagement_id == "acme-2026"
    assert m.in_scope == ["*.acme.example.com"]

def test_unsigned_manifest_rejected(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    yaml_text = manifest_factory().replace("signature:", "signature: # tampered\nsignature_x:")
    with pytest.raises(ManifestError):
        load_and_verify(yaml_text, pub)

def test_tampered_content_rejected(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    yaml_text = manifest_factory().replace("Acme Corp", "Evil Corp")
    with pytest.raises(ManifestError):
        load_and_verify(yaml_text, pub)

def test_expired_window_rejected(manifest_factory, signing_keypair):
    _, pub = signing_keypair
    now = datetime.now(timezone.utc)
    yaml_text = manifest_factory(engagement={
        "window_start": (now - timedelta(days=10)).isoformat(),
        "window_end": (now - timedelta(days=1)).isoformat(),
    })
    with pytest.raises(ManifestError):
        load_and_verify(yaml_text, pub)

def test_malformed_yaml_rejected(signing_keypair):
    _, pub = signing_keypair
    with pytest.raises(ManifestError):
        load_and_verify("not: valid: yaml: [", pub)

def test_wrong_public_key_rejected(manifest_factory):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    yaml_text = manifest_factory()
    wrong_pub = Ed25519PrivateKey.generate().public_key()
    with pytest.raises(ManifestError):
        load_and_verify(yaml_text, wrong_pub)
```

Add to `tests/test_invariants.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_manifest.py tests/test_invariants.py -v`
Expected: FAIL (`ModuleNotFoundError: kronos.manifest` or similar — nothing implemented yet).

- [ ] **Step 5: Implement `manifest.py`**

`canonicalize(data)`: `yaml.safe_dump(data, sort_keys=True, default_flow_style=False).encode("utf-8")` over the `{"engagement": {...}, "scope": {...}}` dict only (no `signature` key present in `data` at this point).

`sign_manifest(manifest_dict, private_key)`: build `canon = canonicalize(manifest_dict)`, `sig = base64.b64encode(private_key.sign(canon)).decode()`, then `yaml.safe_dump({**manifest_dict, "signature": sig}, sort_keys=True)`.

`load_and_verify(yaml_text, public_key)`:
1. `yaml.safe_load` wrapped in try/except -> `ManifestError("malformed manifest YAML")` on any `yaml.YAMLError` or non-dict result.
2. Require `signature` key present and a non-empty string -> else `ManifestError("missing signature")`.
3. Pop `signature`, re-canonicalize the remainder, `public_key.verify(base64.b64decode(sig), canon)` wrapped in try/except `InvalidSignature` -> `ManifestError("invalid signature")`.
4. Parse `engagement`/`scope` sub-dicts into `ScopeManifest` via pydantic, catching `pydantic.ValidationError` -> `ManifestError(str(e))`.
5. Check `window_start <= now() <= window_end` (timezone-aware UTC) -> else `ManifestError("outside authorization window")`.
6. Return the `ScopeManifest`.

`ScopeManifest` field `engagement_id` maps from YAML key `engagement.id` — use a pydantic validator/alias or a small adapter function `_flatten(raw: dict) -> dict` before model construction (decide and log).

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_manifest.py tests/test_invariants.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml requirements.txt src/kronos/__init__.py src/kronos/manifest.py tests/conftest.py tests/test_manifest.py tests/test_invariants.py
git commit -m "feat(manifest): signed scope manifest load + verify"
```

---

### Task 2: Scope Guard

**Files:**
- Create: `src/kronos/scope_guard.py`, `tests/test_scope_guard.py`

**Interfaces:**
- Consumes: `ScopeManifest` (Task 1).
- Produces: `ScopeGuard`, `scope_guard(target, manifest)` (Global Interfaces) — consumed by `graph.py` (Task 3) and `ingest.py` (Task 7).

- [ ] **Step 1: Write failing tests**

```python
def _m(in_scope, excluded):
    return ScopeManifest(engagement_id="e", client="c", authorized_by="a",
                          window_start=..., window_end=..., in_scope=in_scope, excluded=excluded)

def test_fqdn_glob_allows_match():
    assert scope_guard("api.acme.example.com", _m(["*.acme.example.com"], [])) is True

def test_default_deny_when_no_match():
    assert scope_guard("evil.com", _m(["*.acme.example.com"], [])) is False

def test_excluded_wins_over_in_scope_overlap():
    m = _m(["*.acme.example.com"], ["internal.acme.example.com"])
    assert scope_guard("internal.acme.example.com", m) is False
    assert scope_guard("api.acme.example.com", m) is True

def test_cidr_in_scope():
    m = _m(["10.0.0.0/24"], [])
    assert scope_guard("10.0.0.5", m) is True
    assert scope_guard("10.0.1.5", m) is False

def test_cidr_excluded_overrides():
    m = _m(["10.0.0.0/16"], ["10.0.5.0/24"])
    assert scope_guard("10.0.5.10", m) is False
    assert scope_guard("10.0.1.10", m) is True

def test_url_pattern_glob():
    m = _m(["https://api.acme.example.com/v1/*"], [])
    assert scope_guard("https://api.acme.example.com/v1/users", m) is True
    assert scope_guard("https://api.acme.example.com/v2/users", m) is False

def test_mobile_bundle_id_glob():
    m = _m(["com.acme.*"], [])
    assert scope_guard("com.acme.mobileapp", m) is True
    assert scope_guard("com.evil.app", m) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_scope_guard.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `scope_guard.py`**

`ScopeGuard.__init__` stores `manifest.excluded` and `manifest.in_scope` lists as-is (compiling is just keeping the raw glob strings — matching is cheap at this scale).

`_matches(pattern: str, target: str) -> bool`:
- If `"/"` in `pattern` and it parses via `ipaddress.ip_network(pattern, strict=False)`: try `ipaddress.ip_address(target)` — on success return containment; on failure (target isn't a bare IP) fall through to glob matching (so a CIDR pattern never matches a hostname string).
- Else: `fnmatch.fnmatchcase(target.lower(), pattern.lower())`.

`ScopeGuard.is_in_scope(target)`: if any excluded pattern matches -> `False`. Elif any in_scope pattern matches -> `True`. Else -> `False` (default deny).

`scope_guard(target, manifest)` = `ScopeGuard(manifest).is_in_scope(target)`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_scope_guard.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kronos/scope_guard.py tests/test_scope_guard.py
git commit -m "feat(scope): excluded-first glob/CIDR scope guard, default deny"
```

---

### Task 3: Kùzu Schema + EngagementGraph core

**Files:**
- Create: `src/kronos/schema.py`, `src/kronos/graph.py`, `tests/test_schema_graph.py`

**Interfaces:**
- Consumes: `ScopeManifest`, `ScopeGuard` (Tasks 1-2).
- Produces: `init_db`, `EngagementGraph` (Global Interfaces) — the only write path every later task builds on.

- [ ] **Step 1: Write failing tests**

```python
def test_init_db_creates_all_node_tables(tmp_path):
    db = init_db(tmp_path / "e.kz")
    conn = kuzu.Connection(db)
    for t in ["ENGAGEMENT","HOST","SERVICE","WEB_ENDPOINT","PARAMETER","API_ENDPOINT",
              "MOBILE_APP","MOBILE_COMPONENT","SECRET","IDENTITY","CLOUD_RESOURCE",
              "TECHNOLOGY","FINDING","EVIDENCE"]:
        r = conn.execute(f"MATCH (n:{t}) RETURN count(n)")
        assert r.has_next()

def test_init_db_is_idempotent(tmp_path):
    p = tmp_path / "e.kz"
    init_db(p); init_db(p)  # must not raise

def test_upsert_node_merges_not_duplicates(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_factory(), pub)
    g.upsert_node("HOST", "host:10.0.0.1", {"created_at": "2026-01-01T00:00:00Z"})
    g.upsert_node("HOST", "host:10.0.0.1", {"created_at": "2026-01-01T00:00:00Z"})
    r = g.execute("MATCH (n:HOST) RETURN count(n)")
    assert r.get_next()[0] == 1

def test_upsert_node_stamps_in_scope_via_scope_guard(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_factory(), pub)  # in_scope=["*.acme.example.com"]
    g.upsert_node("API_ENDPOINT", "api.acme.example.com", {})
    g.upsert_node("API_ENDPOINT", "api.evil.com", {})
    assert g.get_node("API_ENDPOINT", "api.acme.example.com")["in_scope"] is True
    assert g.get_node("API_ENDPOINT", "api.evil.com")["in_scope"] is False

def test_upsert_edge_merges_not_duplicates(tmp_path, manifest_factory, signing_keypair):
    _, pub = signing_keypair
    g = EngagementGraph.init_engagement(tmp_path / "e.kz", manifest_factory(), pub)
    g.upsert_node("MOBILE_APP", "com.acme.app", {})
    g.upsert_node("SECRET", "secret:abc", {}, scope_key="com.acme.app")
    g.upsert_edge("leaks", "com.acme.app", "secret:abc")
    g.upsert_edge("leaks", "com.acme.app", "secret:abc")
    r = g.execute("MATCH ()-[e:leaks]->() RETURN count(e)")
    assert r.get_next()[0] == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_schema_graph.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Design pass — write `schema.py` DDL**

Node tables (all get `id STRING PRIMARY KEY`, `in_scope BOOLEAN`, `created_at STRING`, `source STRING` — nullable where not applicable — plus the type-specific props below):
- `ENGAGEMENT(id, client, authorized_by, window_start, window_end, destructive_allowed)`
- `HOST(id, in_scope, created_at, source)`
- `SERVICE(id, in_scope, created_at, source, port INT64, protocol STRING)`
- `WEB_ENDPOINT(id, in_scope, created_at, source, url STRING, method STRING)`
- `PARAMETER(id, in_scope, created_at, source, name STRING, param_type STRING)`
- `API_ENDPOINT(id, in_scope, created_at, source, url STRING, method STRING)`
- `MOBILE_APP(id, in_scope, created_at, source, bundle_id STRING, platform STRING)`
- `MOBILE_COMPONENT(id, in_scope, created_at, source, component_type STRING, name STRING)`
- `SECRET(id, in_scope, created_at, source, value_ref STRING, kind STRING, status STRING, confidence INT64, scope_note STRING)`
- `IDENTITY(id, in_scope, created_at, source, name STRING, provider STRING)`
- `CLOUD_RESOURCE(id, in_scope, created_at, source, resource_type STRING, provider STRING)`
- `TECHNOLOGY(id, in_scope, created_at, source, name STRING, version STRING)`
- `FINDING(id, in_scope, created_at, source, title STRING, severity STRING, status STRING, confidence INT64)`
- `EVIDENCE(id, created_at, sha256 STRING, blob_path STRING, kind STRING)` — no `in_scope`/`source` (not a scope target; decide+log).

Edge groups (all `CREATE REL TABLE GROUP <label>(FROM x TO y, ...)`, pairs decided and logged in DECISIONS.md):
- `hosts`: HOST->SERVICE, CLOUD_RESOURCE->HOST, CLOUD_RESOURCE->SERVICE
- `exposes`: HOST->WEB_ENDPOINT, HOST->API_ENDPOINT, SERVICE->WEB_ENDPOINT, SERVICE->API_ENDPOINT
- `has_param`: WEB_ENDPOINT->PARAMETER, API_ENDPOINT->PARAMETER
- `contains`: MOBILE_APP->MOBILE_COMPONENT
- `leaks`: MOBILE_APP->SECRET, MOBILE_COMPONENT->SECRET, API_ENDPOINT->SECRET, WEB_ENDPOINT->SECRET
- `references`: MOBILE_APP->API_ENDPOINT, MOBILE_COMPONENT->API_ENDPOINT, WEB_ENDPOINT->API_ENDPOINT, FINDING->SECRET, FINDING->EVIDENCE
- `authenticates_to`: SECRET->API_ENDPOINT, SECRET->CLOUD_RESOURCE, SECRET->HOST, IDENTITY->API_ENDPOINT, IDENTITY->CLOUD_RESOURCE
- `grants`: IDENTITY->CLOUD_RESOURCE
- `shares_cred_with`: SECRET->SECRET
- `depends_on`: SERVICE->SERVICE, API_ENDPOINT->SERVICE, CLOUD_RESOURCE->CLOUD_RESOURCE
- `vulnerable_to`: HOST->FINDING, SERVICE->FINDING, WEB_ENDPOINT->FINDING, API_ENDPOINT->FINDING, CLOUD_RESOURCE->FINDING, MOBILE_APP->FINDING, MOBILE_COMPONENT->FINDING
- `resolves_to`: HOST->HOST, API_ENDPOINT->HOST, WEB_ENDPOINT->HOST
- `chains_to`: API_ENDPOINT->HOST, API_ENDPOINT->CLOUD_RESOURCE, HOST->CLOUD_RESOURCE, SERVICE->CLOUD_RESOURCE, FINDING->FINDING
- `evidences`: EVIDENCE->FINDING, EVIDENCE->SECRET

Write every `CREATE NODE TABLE IF NOT EXISTS` / `CREATE REL TABLE GROUP IF NOT EXISTS` as one `SCHEMA_DDL` multi-statement string (confirmed supported). `init_db(db_path)`: `Path(db_path).parent.mkdir(parents=True, exist_ok=True)`, `db = kuzu.Database(str(db_path))`, `kuzu.Connection(db).execute(SCHEMA_DDL)`, return `db`.

- [ ] **Step 4: Implement `graph.py`**

`EngagementGraph.__init__(db_path, manifest)`: `self.db = init_db(db_path)`, `self.conn = kuzu.Connection(self.db)`, `self.scope = ScopeGuard(manifest)`, `self.manifest = manifest`.

`init_engagement(cls, db_path, manifest_yaml_text, public_key)`: `manifest = load_and_verify(manifest_yaml_text, public_key)`, `g = cls(db_path, manifest)`, upsert the `ENGAGEMENT` node from `manifest` fields (in_scope not applicable — set `True` constant, log decision), return `g`.

`upsert_node(type, id, props, scope_key=None)`: compute `in_scope = True` for `ENGAGEMENT`/`EVIDENCE` (not scope targets); else `self.scope.is_in_scope(scope_key or id)`. Build a parameterized `MERGE (n:{type} {{id: $id}}) ON CREATE SET n.in_scope=$in_scope, ... ON MATCH SET ...` — use `SET n += $props` style per-key `SET` statements built from `props` keys (Kùzu requires explicit property names, not a generic map-merge into node props at the Cypher level for arbitrary keys — implementer composes a `SET` clause per key present in `props`, keeping `in_scope` always driven by the scope guard, never by `props`).

`upsert_edge(label, from_id, from_type, to_id, to_type, props=None)`: Kùzu rel-table-group MERGE needs both endpoint node *types* to pick the right internal pair, so the caller supplies them explicitly rather than having the graph layer guess by scanning every table. Build a parameterized `MATCH (a:{from_type} {{id:$from_id}}), (b:{to_type} {{id:$to_id}}) MERGE (a)-[r:{label}]->(b)` and, if `props` given, a `SET` clause per key. Log the exact signature as a decision in `DECISIONS.md` (already reflected in this plan's Global Interfaces block).

`get_node(type, id)`: `MATCH (n:{type} {{id: $id}}) RETURN n.*` -> dict of column name to value, or `None` if no row.

`execute(query, params=None)`: `return self.conn.execute(query, params or {})`.

- [ ] **Step 5: Run to verify pass**

Run: `pytest tests/test_schema_graph.py -v`
Expected: PASS

- [ ] **Step 6: Write `src/kronos/README_graph.md`** (schema + graph module, future-maintainer level: table list, edge-pair table, why MERGE-by-id is the dedup strategy, why `in_scope` is never caller-settable).

- [ ] **Step 7: Commit**

```bash
git add src/kronos/schema.py src/kronos/graph.py src/kronos/README_graph.md tests/test_schema_graph.py
git commit -m "feat(graph): Kuzu schema DDL + EngagementGraph upsert core"
```

---

### Task 4: Validation Lifecycle (the false-positive killer)

**Files:**
- Create: `src/kronos/lifecycle.py`, `src/kronos/README_lifecycle.md`, `tests/test_lifecycle.py`
- Modify: `tests/test_invariants.py`

**Interfaces:**
- Consumes: `EngagementGraph` (Task 3), its corrected `upsert_edge(label, from_id, from_type, to_id, to_type, props=None)` signature.
- Produces: `LifecycleError`, `derive_confidence`, `advance_secret_status`, `advance_finding_status`, `can_anchor_finding` — consumed by `evidence.py` (Task 5) and `query.py`/tests (Task 6-7).

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_secret_transition_extracted_to_validated_ok(engagement_graph):
    g = engagement_graph
    g.upsert_node("SECRET", "s1", {"value_ref":"sha256:aaa","kind":"api_key","status":"extracted"})
    advance_secret_status(g, "s1", "validated")
    assert g.get_node("SECRET","s1")["status"] == "validated"

def test_secret_cannot_skip_validated(engagement_graph):
    g = engagement_graph
    g.upsert_node("SECRET", "s1", {"value_ref":"x","kind":"api_key","status":"extracted"})
    with pytest.raises(LifecycleError):
        advance_secret_status(g, "s1", "reachable")

def test_secret_cannot_leave_dead(engagement_graph):
    g = engagement_graph
    g.upsert_node("SECRET", "s1", {"value_ref":"x","kind":"api_key","status":"extracted"})
    advance_secret_status(g, "s1", "dead")
    with pytest.raises(LifecycleError):
        advance_secret_status(g, "s1", "validated")

def test_finding_reported_requires_exploited_and_evidence(engagement_graph):
    g = engagement_graph
    g.upsert_node("FINDING", "f1", {"title":"t","severity":"high","status":"hypothesis"})
    with pytest.raises(LifecycleError):
        advance_finding_status(g, "f1", "reported")  # wrong status
    advance_finding_status(g, "f1", "reachable")
    advance_finding_status(g, "f1", "exploited")
    with pytest.raises(LifecycleError):
        advance_finding_status(g, "f1", "reported")  # exploited but NO evidence yet

def test_finding_reported_terminal(engagement_graph):
    g = engagement_graph
    g.upsert_node("FINDING", "f1", {"title":"t","severity":"high","status":"hypothesis"})
    advance_finding_status(g, "f1", "reachable")
    advance_finding_status(g, "f1", "exploited")
    # simulate evidence directly via the edge (Task 5 wires attach_evidence; here we poke the graph)
    g.upsert_node("EVIDENCE", "ev1", {"sha256":"abc","blob_path":"x","kind":"screenshot"})
    g.upsert_edge("evidences", "ev1", "EVIDENCE", "f1", "FINDING")
    advance_finding_status(g, "f1", "reported")
    with pytest.raises(LifecycleError):
        advance_finding_status(g, "f1", "hypothesis")

def test_out_of_scope_secret_cannot_anchor_finding(engagement_graph):
    g = engagement_graph  # in_scope=["*.acme.example.com"]
    g.upsert_node("API_ENDPOINT", "api.evil.com", {})
    g.upsert_node("SECRET", "s1", {"value_ref":"x","kind":"api_key","status":"extracted"})
    advance_secret_status(g, "s1", "validated")
    g.upsert_edge("authenticates_to", "s1", "SECRET", "api.evil.com", "API_ENDPOINT")
    advance_secret_status(g, "s1", "reachable")
    assert can_anchor_finding(g, "s1") is False
    assert g.get_node("SECRET", "s1")["scope_note"] is not None  # recorded as a note

def test_confidence_cannot_exceed_status_cap(engagement_graph):
    g = engagement_graph
    g.upsert_node("FINDING", "f1", {"title":"t","severity":"high","status":"hypothesis"})
    assert g.get_node("FINDING","f1")["confidence"] < 7
    advance_finding_status(g, "f1", "reachable")
    assert g.get_node("FINDING","f1")["confidence"] < 9
    advance_finding_status(g, "f1", "exploited")
    assert g.get_node("FINDING","f1")["confidence"] >= 9

def test_derive_confidence_pure_function_table():
    assert derive_confidence("finding", "hypothesis", False) < 7
    assert derive_confidence("secret", "validated", False) in (7, 8)
    assert derive_confidence("finding", "reachable", True) >= 9
    assert derive_confidence("finding", "exploited", True) == 10
    assert derive_confidence("secret", "dead", False) == 0
```

Add to `tests/test_invariants.py`:
```python
def test_invariant_no_evidence_finding_cannot_be_reported(engagement_graph):
    g = engagement_graph
    g.upsert_node("FINDING", "f1", {"title":"t","severity":"high","status":"hypothesis"})
    advance_finding_status(g, "f1", "reachable")
    advance_finding_status(g, "f1", "exploited")
    with pytest.raises(LifecycleError):
        advance_finding_status(g, "f1", "reported")

def test_invariant_out_of_scope_secret_cannot_anchor_finding(engagement_graph):
    g = engagement_graph
    g.upsert_node("API_ENDPOINT", "api.evil.com", {})
    g.upsert_node("SECRET", "s1", {"value_ref":"x","kind":"api_key","status":"extracted"})
    advance_secret_status(g, "s1", "validated")
    g.upsert_edge("authenticates_to", "s1", "SECRET", "api.evil.com", "API_ENDPOINT")
    advance_secret_status(g, "s1", "reachable")
    assert can_anchor_finding(g, "s1") is False

def test_invariant_confidence_cannot_exceed_status_cap(engagement_graph):
    assert derive_confidence("finding", "hypothesis", False) < 7
    assert derive_confidence("secret", "extracted", True) < 7  # evidence doesn't rescue an unvalidated secret
    assert derive_confidence("secret", "validated", False) in (7, 8)
```

Add `conftest.py` fixture `engagement_graph(tmp_path, manifest_factory, signing_keypair)` -> `EngagementGraph` via `init_engagement`, reused from here on by every later task's tests.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_lifecycle.py tests/test_invariants.py -v`
Expected: FAIL (module not found / fixture missing).

- [ ] **Step 3: Implement `lifecycle.py`**

Transition tables:
```python
SECRET_TRANSITIONS = {
    "extracted": {"validated", "dead"},
    "validated": {"reachable", "dead"},
    "reachable": {"dead"},
    "dead": set(),
}
FINDING_TRANSITIONS = {
    "hypothesis": {"reachable", "discarded"},
    "reachable": {"exploited", "discarded"},
    "exploited": {"reported", "discarded"},
    "reported": set(),
    "discarded": set(),
}
```

`derive_confidence(entity_type, status, has_evidence)`: fixed constants (document each as a decision): `exploited -> 10`; `reported -> 10`; `reachable and has_evidence -> 9`; `reachable and not has_evidence -> 7`; `validated -> 7`; `extracted -> 3`; `hypothesis -> 3`; `dead -> 0`; `discarded -> 0`. Raise `ValueError` on an unrecognized `(entity_type, status)` pair (defensive — should be unreachable given the transition tables gate status values).

`_evidence_count(graph, target_type: Literal["finding","secret"], target_id) -> int`: `graph.execute("MATCH (e:EVIDENCE)-[:evidences]->(n:{TABLE} {{id:$id}}) RETURN count(e)", {"id": target_id})` where `{TABLE}` is `"FINDING"` or `"SECRET"`.

`can_anchor_finding(graph, secret_id)`: fetch secret status; if not `"reachable"` -> `False`. Else query `MATCH (s:SECRET {id:$id})-[:authenticates_to]->(t) RETURN t.in_scope` across the group's target tables (Kùzu allows an untyped `(t)` on the far end of a rel-group match — implementer confirms via a quick local check analogous to the earlier prototype; if an untyped target isn't directly supported, union the explicit `API_ENDPOINT|CLOUD_RESOURCE|HOST` target queries). Return `True` if any row has `in_scope == True`.

`advance_secret_status(graph, secret_id, new_status)`: look up current `status`; validate `new_status in SECRET_TRANSITIONS[current]` else raise `LifecycleError(f"invalid SECRET transition {current} -> {new_status}")`. If `new_status == "reachable"`: compute `scope_note`: if the secret has `>=1` `authenticates_to` edge and **none** of its targets are in-scope, set `scope_note = "reachable target(s) out-of-scope; recorded only, not actionable"`; else `scope_note = None`. Compute `has_evidence = _evidence_count(graph,"secret",secret_id) > 0`, `confidence = derive_confidence("secret", new_status, has_evidence)`. Write `status`, `confidence`, `scope_note` via a direct `SET` Cypher call (lifecycle is the only place allowed to touch these three fields — do not route through `upsert_node`'s generic props path for `status`/`confidence` to keep the enforcement chokepoint singular; implementer adds a small private `_set_secret_fields`/`_set_finding_fields` helper in this module rather than exposing a generic setter on `EngagementGraph`).

`advance_finding_status(graph, finding_id, new_status)`: look up current status; validate against `FINDING_TRANSITIONS`. If `new_status == "reported"`: re-check `current == "exploited"` (already guaranteed by the transition table, but the rule is stated independently in the spec, so assert it explicitly with its own error message) and `_evidence_count(graph,"finding",finding_id) >= 1` else raise `LifecycleError("cannot report finding without evidence")`. Then check anchor secrets: `MATCH (f:FINDING {id:$id})-[:references]->(s:SECRET) RETURN s.id`; if that list is non-empty, require `any(can_anchor_finding(graph, sid) for sid in secret_ids)` else raise `LifecycleError("finding's only secret anchor(s) are not reachable+in-scope")`. Compute `has_evidence` and `confidence = derive_confidence("finding", new_status, has_evidence)`, write `status`+`confidence`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_lifecycle.py tests/test_invariants.py -v`
Expected: PASS

- [ ] **Step 5: Write `src/kronos/README_lifecycle.md`** — state machines as a diagram-in-prose, the confidence table verbatim, and a one-paragraph "why this can't be bypassed" (single write chokepoint, no generic status setter exposed).

- [ ] **Step 6: Commit**

```bash
git add src/kronos/lifecycle.py src/kronos/README_lifecycle.md tests/test_lifecycle.py tests/test_invariants.py tests/conftest.py
git commit -m "feat(lifecycle): evidence-gated SECRET/FINDING status machine, derived confidence"
```

---

### Task 5: Evidence Store

**Files:**
- Create: `src/kronos/evidence.py`, `tests/test_evidence.py`

**Interfaces:**
- Consumes: `EngagementGraph` (Task 3).
- Produces: `store_evidence`, `get_evidence`, `attach_evidence` — consumed by `query.py` (Task 6) and by lifecycle-driving tests/ingestion (Task 7).

- [ ] **Step 1: Write failing tests**

```python
def test_store_evidence_is_content_addressed(tmp_path):
    info = store_evidence(tmp_path, b"hello world", "screenshot")
    assert info["sha256"] == hashlib.sha256(b"hello world").hexdigest()
    assert Path(info["blob_path"]).read_bytes() == b"hello world"

def test_store_evidence_idempotent_same_content(tmp_path):
    info1 = store_evidence(tmp_path, b"hello", "log")
    info2 = store_evidence(tmp_path, b"hello", "log")
    assert info1["sha256"] == info2["sha256"]

def test_get_evidence_roundtrip(tmp_path):
    info = store_evidence(tmp_path, b"payload", "pcap")
    assert get_evidence(tmp_path, info["sha256"]) == b"payload"

def test_get_evidence_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        get_evidence(tmp_path, "0"*64)

def test_attach_evidence_creates_node_and_edge(engagement_graph, tmp_path):
    g = engagement_graph
    g.upsert_node("FINDING", "f1", {"title":"t","severity":"high","status":"hypothesis"})
    sha = attach_evidence(g, tmp_path, b"poc output", "poc", "finding", "f1")
    r = g.execute("MATCH (e:EVIDENCE)-[:evidences]->(f:FINDING {id:'f1'}) RETURN e.sha256")
    assert r.get_next()[0] == sha
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_evidence.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `evidence.py`**

`store_evidence(engagement_dir, blob, kind)`: `sha = hashlib.sha256(blob).hexdigest()`; `path = Path(engagement_dir)/"evidence"/sha`; create parent dir; if `path` doesn't exist, write `blob` to it; if it does exist, read it back and assert it matches `blob` (defends the "immutable" property — raise `ValueError` on mismatch, which should be unreachable given content-addressing but documents the invariant). Return `{"sha256": sha, "blob_path": str(path), "kind": kind, "created_at": datetime.now(timezone.utc).isoformat()}`.

`get_evidence(engagement_dir, sha256)`: `path = Path(engagement_dir)/"evidence"/sha256`; raise `FileNotFoundError` if missing; else return `path.read_bytes()`.

`attach_evidence(graph, engagement_dir, blob, kind, target_type, target_id)`: `info = store_evidence(engagement_dir, blob, kind)`; `graph.upsert_node("EVIDENCE", info["sha256"], {"sha256": info["sha256"], "blob_path": info["blob_path"], "kind": kind, "created_at": info["created_at"]})`; `graph.upsert_edge("evidences", info["sha256"], "EVIDENCE", target_id, "FINDING" if target_type=="finding" else "SECRET")`; return `info["sha256"]`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_evidence.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kronos/evidence.py tests/test_evidence.py
git commit -m "feat(evidence): hash-addressed immutable evidence store"
```

---

### Task 6: Query Interface

**Files:**
- Create: `src/kronos/query.py`, `tests/test_query.py`

**Interfaces:**
- Consumes: `EngagementGraph` (Task 3), `get_evidence` (Task 5, re-exported).
- Produces: `query_graph`, `get_evidence` (re-export), `find_paths`, `list_findings`, `list_secrets` — the only read surface later agent work (out of scope this brief) will use.

- [ ] **Step 1: Write failing tests**

```python
def test_query_graph_filters_by_type_and_prop(engagement_graph):
    g = engagement_graph
    g.upsert_node("HOST", "h1", {})
    g.upsert_node("API_ENDPOINT", "api.acme.example.com", {})
    rows = query_graph(g, node_type="HOST")
    assert {r["id"] for r in rows} == {"h1"}

def test_list_findings_by_status(engagement_graph):
    g = engagement_graph
    g.upsert_node("FINDING", "f1", {"title":"a","severity":"low","status":"hypothesis"})
    g.upsert_node("FINDING", "f2", {"title":"b","severity":"high","status":"hypothesis"})
    advance_finding_status(g, "f2", "reachable")
    assert {r["id"] for r in list_findings(g, status="hypothesis")} == {"f1"}
    assert {r["id"] for r in list_findings(g, status="reachable")} == {"f2"}

def test_list_secrets_by_status(engagement_graph):
    g = engagement_graph
    g.upsert_node("SECRET", "s1", {"value_ref":"x","kind":"api_key","status":"extracted"})
    assert {r["id"] for r in list_secrets(g, status="extracted")} == {"s1"}

def test_find_paths_returns_seeded_mobile_to_cloud_chain(engagement_graph):
    g = engagement_graph
    g.upsert_node("MOBILE_APP", "com.acme.app", {"bundle_id":"com.acme.app"})
    g.upsert_node("SECRET", "s1", {"value_ref":"x","kind":"api_key","status":"extracted"}, scope_key="com.acme.app")
    g.upsert_node("API_ENDPOINT", "api.acme.example.com", {})
    g.upsert_node("CLOUD_RESOURCE", "cr:acme-bucket", {}, scope_key="api.acme.example.com")
    g.upsert_edge("leaks", "com.acme.app", "MOBILE_APP", "s1", "SECRET")
    g.upsert_edge("authenticates_to", "s1", "SECRET", "api.acme.example.com", "API_ENDPOINT")
    g.upsert_edge("chains_to", "api.acme.example.com", "API_ENDPOINT", "cr:acme-bucket", "CLOUD_RESOURCE")
    paths = find_paths(g, "MOBILE_APP", "CLOUD_RESOURCE", max_hops=5)
    assert len(paths) >= 1
    assert paths[0]["nodes"][0] == "com.acme.app"
    assert paths[0]["nodes"][-1] == "cr:acme-bucket"

def test_find_paths_only_in_scope_excludes_out_of_scope_hop(engagement_graph):
    g = engagement_graph
    g.upsert_node("MOBILE_APP", "com.acme.app", {})
    g.upsert_node("API_ENDPOINT", "api.evil.com", {})  # out of scope
    g.upsert_node("CLOUD_RESOURCE", "cr:x", {}, scope_key="api.evil.com")
    g.upsert_edge("references", "com.acme.app", "MOBILE_APP", "api.evil.com", "API_ENDPOINT")
    g.upsert_edge("chains_to", "api.evil.com", "API_ENDPOINT", "cr:x", "CLOUD_RESOURCE")
    assert find_paths(g, "MOBILE_APP", "CLOUD_RESOURCE", max_hops=5, only_in_scope=True) == []
```

Add to `tests/test_invariants.py`:
```python
def test_invariant_find_paths_returns_seeded_mobile_to_cloud_chain(engagement_graph):
    # same seeding as test_find_paths_returns_seeded_mobile_to_cloud_chain
    ...
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_query.py tests/test_invariants.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `query.py`**

`query_graph(graph, node_type=None, filters=None)`: if `node_type` given, run `MATCH (n:{node_type}) RETURN n.*` and apply `filters` as an exact-match `WHERE` clause built from parameterized keys; if `node_type` is `None`, iterate the fixed list of all node table names and union results (documented as O(num_tables), fine at this scale). Return list of row-dicts.

`list_findings(graph, status=None)` = `query_graph(graph, "FINDING", {"status": status} if status else None)`. `list_secrets` analogous with `"SECRET"`.

`get_evidence = evidence.get_evidence` (re-export; `query.py` additionally needs `engagement_dir`, so its wrapped signature is `get_evidence(engagement_dir, sha256)` identical to Task 5 — just imported here per the spec's named interface list).

`find_paths(graph, from_type, to_type, max_hops=5, only_in_scope=True)`: build
```
f"MATCH p=(a:{from_type})-[* 1..{max_hops} (r,n | WHERE n.in_scope = true)]->(b:{to_type}) RETURN [n IN nodes(p)|n.id] AS ids, [r IN rels(p)|label(r)] AS lbls, length(p) AS len ORDER BY len"
```
when `only_in_scope`; drop the `(r,n | WHERE ...)` predicate (plain `[*1..{max_hops}]`) when not. Also filter `WHERE a.in_scope = true AND b.in_scope = true` in both cases (confirmed via Review Focus: an out-of-scope endpoint must never appear as a path terminus even if `only_in_scope=False` is used for diagnostics — decide and log that `only_in_scope` governs intermediate hops only, endpoints are always scope-checked). Map result rows to `{"nodes": ids, "labels": lbls, "length": len}`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_query.py tests/test_invariants.py -v`
Expected: PASS

- [ ] **Step 5: Write `src/kronos/README_query.md`** (the 4+1 functions, why `find_paths` is the differentiator query, the in-scope-endpoints-always rule).

- [ ] **Step 6: Commit**

```bash
git add src/kronos/query.py src/kronos/README_query.md tests/test_query.py tests/test_invariants.py
git commit -m "feat(query): query_graph/find_paths/list_findings/list_secrets read API"
```

---

### Task 7: Ingestion Contract + Reference Ingester (worked example)

**Files:**
- Create: `src/kronos/ingest.py`, `src/kronos/README_ingest.md`, `tests/test_ingest.py`

**Interfaces:**
- Consumes: `EngagementGraph.upsert_node`/`upsert_edge` (Task 3).
- Produces: `ingest`, `apply_upserts`, `ingest_reference_mobile_secret`, `NodeUpsert`, `EdgeUpsert`.

- [ ] **Step 1: Write failing tests**

```python
def test_ingest_reference_mobile_secret_shape():
    ups = ingest_reference_mobile_secret()
    assert any(isinstance(u, NodeUpsert) and u.type == "MOBILE_APP" for u in ups)
    assert any(isinstance(u, NodeUpsert) and u.type == "SECRET" for u in ups)
    assert any(isinstance(u, EdgeUpsert) and u.label == "leaks" for u in ups)

def test_ingest_dispatches_reference_tool(engagement_graph):
    ups = ingest(raw_tool_output=None, tool_name="reference", engagement=engagement_graph)
    assert len(ups) >= 3

def test_ingest_unknown_tool_raises(engagement_graph):
    with pytest.raises(NotImplementedError):
        ingest(raw_tool_output={}, tool_name="nmap", engagement=engagement_graph)

def test_apply_upserts_writes_nodes_and_edges(engagement_graph):
    g = engagement_graph
    ups = ingest_reference_mobile_secret()
    apply_upserts(g, ups)
    r = g.execute("MATCH (a:MOBILE_APP)-[:leaks]->(s:SECRET) RETURN a.id, s.id")
    assert r.has_next()

def test_apply_upserts_is_idempotent_no_duplicates(engagement_graph):
    g = engagement_graph
    ups = ingest_reference_mobile_secret()
    apply_upserts(g, ups)
    apply_upserts(g, ups)  # re-run identical raw input
    r = g.execute("MATCH (a:MOBILE_APP)-[:leaks]->(s:SECRET) RETURN count(*)")
    assert r.get_next()[0] == 1
```

Add to `tests/test_invariants.py` (the find_paths invariant now exercised via the real ingester end to end, demonstrating the worked example):
```python
def test_invariant_ingested_reference_example_produces_mobile_to_secret_chain(engagement_graph):
    g = engagement_graph
    apply_upserts(g, ingest_reference_mobile_secret())
    paths = find_paths(g, "MOBILE_APP", "SECRET", max_hops=2)
    assert len(paths) >= 1
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_ingest.py tests/test_invariants.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `ingest.py`**

`NodeUpsert`/`EdgeUpsert` as `@dataclass(frozen=True)`.

`ingest_reference_mobile_secret(bundle_id="com.kronos.demo")`:
```python
secret_id = f"secret:{hashlib.sha256(bundle_id.encode()).hexdigest()[:16]}"
return [
    NodeUpsert("MOBILE_APP", bundle_id, {"bundle_id": bundle_id, "platform": "android", "source": "static"}),
    NodeUpsert("SECRET", secret_id, {"value_ref": "sha256:"+hashlib.sha256(b"demo-key").hexdigest(),
                                      "kind": "api_key", "status": "extracted", "source": "static"},
               scope_key=bundle_id),
    EdgeUpsert("leaks", bundle_id, secret_id),
]
```

`apply_upserts(engagement, upserts)`: for each item, if `NodeUpsert`: `engagement.upsert_node(item.type, item.id, item.props, scope_key=item.scope_key)`; if `EdgeUpsert`: resolve `from_type`/`to_type` by looking up which node table currently holds `from_id`/`to_id` (small helper scanning the fixed table list via `get_node`), then call `engagement.upsert_edge(item.label, item.from_id, from_type, item.to_id, to_type, item.props)`.

`ingest(raw_tool_output, tool_name, engagement)`: `if tool_name == "reference": return ingest_reference_mobile_secret()`; else `raise NotImplementedError(f"parser for tool_name={tool_name!r} not implemented; real parsers are a later brief")`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_ingest.py tests/test_invariants.py -v`
Expected: PASS

- [ ] **Step 5: Run the FULL test suite**

Run: `pytest -v`
Expected: PASS, all tests across every task green, including all 5 named invariant tests in `tests/test_invariants.py`.

- [ ] **Step 6: Write `src/kronos/README_ingest.md`** (the upsert contract, MERGE/dedup guarantee, how a real future parser plugs in).

- [ ] **Step 7: Commit**

```bash
git add src/kronos/ingest.py src/kronos/README_ingest.md tests/test_ingest.py tests/test_invariants.py
git commit -m "feat(ingest): upsert contract + reference mobile-secret ingester"
```

---

### Task 8: DECISIONS.md, top-level README wiring, final review

**Files:**
- Create: `DECISIONS.md`
- Modify: `README.md` (point "Build" section at the real `pip install -r requirements.txt && pytest` flow if it changed), `src/kronos/README.md` (top-level package README linking the per-module ones)

**Interfaces:** None (documentation + verification task).

- [ ] **Step 1: Write `DECISIONS.md`**

One entry per autonomous call made across Tasks 1-7: manifest canonicalization format, pubkey-path-is-explicit-not-auto-discovered, `ENGAGEMENT`/`EVIDENCE` always `in_scope=True`, the full edge-pair table (schema.py), the `references: FINDING->SECRET` anchor-edge semantics, the confidence constant table, strict linear lifecycle transitions (no skipping `reachable`), `scope_note` field for out-of-scope-anchor secrets, `find_paths` endpoints always scope-checked even when `only_in_scope=False`, `upsert_edge`'s corrected 5-arg signature, file/module naming. Each entry: *Decision*, *Why*, *Reversibility*.

- [ ] **Step 2: Run full suite + lint sanity pass**

Run: `pytest -v` and skim `git diff --stat` across the branch for anything that looks accidental (stray prototype files, temp DBs). Expected: clean full pass, no stray files staged.

- [ ] **Step 3: Commit**

```bash
git add DECISIONS.md README.md src/kronos/README.md
git commit -m "docs: record autonomous decisions, wire up top-level README"
```

- [ ] **Step 4: Push branch and open PR**

```bash
git push -u origin claude/sweet-gauss-x4l1wi
```
Open a PR whose description contains: this plan (link or inline), a summary of what was built per task, any `FORK:` items raised during implementation (expected: none required escalation per the escalation contract — note this explicitly if true), and the exact test command (`pytest -v`) plus expected result.

---

## Self-Review Notes

- **Spec coverage:** every Deliverable (schema, graph layer, reference ingester, 5 invariant tests, DECISIONS.md, per-module READMEs) maps to a task; every hard lifecycle rule (1-4) and the scope guard's excluded-first/default-deny rule has an explicit test.
- **Signature consistency:** `upsert_edge`'s 5-arg form (`label, from_id, from_type, to_id, to_type, props=None`) — needed because Kuzu rel groups require both endpoint types to pick the right internal table — is now fixed in the Global Interfaces block and used consistently in every task's test code and implementation notes (Tasks 3-7).
- **Proportion:** kept function bodies to algorithm sketches (confidence table, Cypher templates, transition tables) rather than full transcripts; signatures, test names, and fixed constants are exact since those are the cross-task contracts.
