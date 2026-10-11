# Mobile Tooling Preflight (Brief #2)

Preflight run on the operator's local Kali VM before building the mobile
ingestion module. Captures what's actually installed and how it's invoked,
per the "JOTNAR lesson" (verify before building, don't assume).

## MobSF — primary analysis anchor (per decision D5)

- **Status:** Installed and running via Docker (image already pulled:
  `opensecurity/mobile-security-framework-mobsf:latest`, ~2.38GB).
- **Resolution:** initially not installed (FORK raised); operator fixed Docker
  group access (`void` added to `docker` group) and had the image pre-pulled.
  Went with Docker as primary per decision D5, resolving the FORK.
- **Container:** `docker run -d --name mobsf -p 8000:8000
  opensecurity/mobile-security-framework-mobsf:latest` — started detached,
  persists across reboots unless removed (no `--rm`).
- **Version:** MobSF v4.5.4.
- **Reachable at:** `http://localhost:8000` (REST API under `/api/v1/`).
- **Auth:** REST API key required via `Authorization` header. Stored locally
  in `.env` (gitignored, never committed) as `MOBSF_API_KEY`. Web UI default
  credentials are `mobsf/mobsf` (not used by this module — API-only).
- **Docker CLI caveat on this machine:** the `void` user's group membership
  was updated in `/etc/group` but the current shell session predates that
  change, so bare `docker` commands still get `permission denied`. Commands
  must be run via `sg docker -c "docker ..."` until a fresh login session
  picks up the new group. The ingestion module itself talks to MobSF over
  HTTP (not via the `docker` CLI), so this caveat only affects
  starting/stopping the container, not the parser's runtime behavior.
- **API smoke test:** `POST /api/v1/scans` with the API key returned HTTP 405
  (method/params mismatch, not an auth failure) — confirms the key is valid
  and the API is live.

## jadx — supplementary decompiler

- **Status:** Installed natively.
- **Version:** 1.5.6.
- **Invocation:** `jadx <input.apk> -d <output_dir>` (also available as a
  Python-importable path via subprocess; no native bindings).

## apktool — supplementary manifest/resource extractor

- **Status:** Installed natively.
- **Version:** 2.7.0-dirty.
- **Invocation:** `apktool d <input.apk> -o <output_dir>` — decodes
  `AndroidManifest.xml` to plain XML and unpacks `res/` for string/resource
  scanning.

## apkleaks — NOT installed

- **Status:** Not installed (Kali blocks system-wide `pip install` per PEP
  668; would need `pipx` or a venv).
- **Resolution:** not needed as a separate tool. Per decision D5, the
  "apkleaks-style" secret/endpoint extraction is implemented as a small
  in-repo regex-based supplementary extractor (see `src/kronos/ingest/mobile/
  light_extractors.py`), run against jadx/apktool output to fill gaps where
  MobSF's own findings are thin. This avoids an extra heavyweight dependency
  for a well-understood regex pass.

## Project Python environment

- **Status:** No venv existed before this brief. Created at `.venv/` (project
  root), gitignored.
- **Dependencies:** installed from `requirements.txt` (`kuzu==0.11.3`,
  `pydantic==2.13.5`, `cryptography==50.0.1`, `PyYAML==6.0.1`,
  `pytest==9.1.1`). All import correctly.
- **Brief #1 regression check:** full existing test suite re-run after venv
  setup — **58 passed**, 0 failed. Confirms Brief #1's foundation is sound on
  this machine before building on top of it.

## Summary for the mobile ingestion module

| Tool | Role | Status |
|---|---|---|
| MobSF | Primary static analysis anchor | ✅ Running, Docker, API key in `.env` |
| jadx | Supplementary decompilation | ✅ Native, v1.5.6 |
| apktool | Supplementary manifest/resource extraction | ✅ Native, v2.7.0 |
| light regex extractor (in-repo) | Fills gaps where MobSF is thin | To be built this brief |
