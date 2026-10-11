# Mobile static ingestion (Brief #2)

Entry point: `parser.ingest_mobile_static(apk_path, engagement, mobsf_client=None)`
— targets Brief #1's fixed ingestion contract exactly (`list[NodeUpsert |
EdgeUpsert]`, written by the existing `apply_upserts()`). Wired into
`kronos.ingest.ingest()` under `tool_name="mobile_static"`.

## Pipeline

1. `apktool d` — decode the APK (manifest + resources as plain XML).
2. `manifest_parser.parse_manifest` — bundle id, platform, components +
   `exported` (explicit `android:exported` attribute, or implied by an
   `<intent-filter>` when absent; defaults to `False` otherwise).
3. `jadx` (best-effort; a decompile failure or empty/dex-less APK is a
   normal outcome, not fatal).
4. `light_extractors` — regex/name-heuristic scan over resource strings
   (and decompiled source, endpoints only) for secrets and endpoints.
   Detects Base64-obfuscated secrets; split/concatenated-string
   obfuscation is a tracked follow-up (see `tests/fixtures/README.md`).
5. MobSF (if an `MobSFClient` is passed and reachable) — upload, scan,
   fetch JSON report; its secret/endpoint findings are merged with the
   light extractors' (deduped by value), never replacing them. An
   unreachable or erroring MobSF degrades gracefully to light-extractor
   results only — never a crash.
6. Build the upsert list: `MOBILE_APP`, `MOBILE_COMPONENT` (+`contains`
   edges), `SECRET` (+`leaks`), `API_ENDPOINT` (+`references`), `EVIDENCE`
   (+`evidences`) — every node `source="static"`, every `SECRET` enters at
   `status="extracted"` only.

## Security boundary (the one that matters most)

Every `NodeUpsert.props` dict here is built from named, fixed fields —
never by spreading an extracted/MobSF-returned dict directly. A crafted
APK/resource value cannot inject `in_scope`/`confidence`/`status`/or any
other key into the graph through this module; Brief #1's `upsert_node`
allowlist is the backstop even if a future bug tried. See
`test_hostile_input_graph_injection_blocked_by_construction` in
`tests/test_mobile_ingest.py` for the precise, non-overclaiming proof of
what's forbidden-always (`confidence`/`in_scope`) versus create-only-by-
design (`status`).

## Evidence

Each extracted secret's supporting blob (its decoded value) is stored via
Brief #1's `evidence.store_evidence` (hash-addressed) and wired in as an
ordinary `EVIDENCE` `NodeUpsert` + `evidences` `EdgeUpsert` — reusing the
existing upsert-list contract rather than calling `evidence.attach_evidence`
directly against a live graph, so evidence-writing stays inside the same
compute-then-apply flow as every other write this module makes.
