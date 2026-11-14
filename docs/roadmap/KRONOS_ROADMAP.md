# KRONOS Product Roadmap

Roadmap-Version: 1 (Beta-Entry)
Derived: 2026-11-13, from the S1–S8 sequence in the KRONOS research record
(`docs/research/KRONOS_RESEARCH_RECORD.md`, stage table) and operator decisions D1–D9 on
`B54_COMPLETION_DECISION_PACKET`. This artifact is pinned as `SRC-ROADMAP` in
`docs/governance/KRONOS_DONE.md` and is authoritative for roadmap ordering under contract §13.2/§13.4.

Precedence preserved (research record, goals section): **G3 constrains G1 and G2** — each G1 domain
step carries its two-armed (G3) validation in the same step; **G1 before G2** — breadth first, then
autonomy over that breadth.

Status column is relative to live main `78dcb76` (derived 2026-11-13; see the live-main gap map in the
research record and `B54_COMPLETION_DECISION_PACKET.md` §4). "COMPLETE (hermetic)" means implemented
and tested without any live/manifest-bounded run.

| Order | Item | Milestones | From | Goal | Status vs main 78dcb76 |
|---|---|---|---|---|---|
| R1 | Negative controls + CyberGym denial fidelity | BE-G3-1, BE-G3-2 | S1 | G3 | COMPLETE |
| R2 | Ingestion contract, canonical keys, event stream | BE-G1-1 | S2 | G1, G3 | COMPLETE |
| R3 | Infra ingestion + two-armed validation | BE-G1-2 | S3, S4 | G1, G3 | COMPLETE |
| R4 | Web ingestion + two-armed validation | BE-G1-3 | S5, S6 | G1, G3 | COMPLETE |
| R5 | Transitive invalidation / staleness | BE-G3-4 | S7 | G3 | COMPLETE |
| R6 | Evidence-gate / abstention hardening | BE-G3-3 | S1/G3 invariant | G3 | COMPLETE |
| R7 | Cloud ingestion → `CLOUD_RESOURCE`, `IDENTITY` | BE-G1-6 | RR coverage gap (Cloud ingestion absent) | G1, G3 | MISSING |
| R8 | Standalone API ingestion (not mobile-sourced) | BE-G1-5 | RR coverage gap (API mobile-sourced only) | G1, G3 | MISSING |
| R9 | Five-domain integrated engagement run | BE-G1-7 | RR first-usable-milestone | G1, G3 | MISSING |
| R10 | Committed evaluation evidence for R9 | BE-G3-5 | S1/§7.2 CyberGym | G3 | MISSING |
| R11 | Agent layer Inc 1–4 + control spine | BE-G2-1..BE-G2-5 | S8 | G2 | COMPLETE (hermetic) |
| R12 | Live driver/executor on an authorized real run | BE-G2-6 | S8 Inc 3 (CyberGym range only) | G2 | BLOCKED (PARTIAL) |

## Decision bindings (operator D1–D9)

- **D9 ordering:** R7 = cloud ingestion, R8 = standalone API ingestion, R9 = five-domain integration,
  R10 = committed evaluation evidence. **R12 is BLOCKED until R9 and R10 pass.**
- **D7:** the next product increment is **R7 (BE-G1-6, cloud ingestion)**, using the existing
  provider-neutral cloud-validator fixture/schema as the initial hermetic source — no provider
  credentials, no SDK calls, no live cloud access.
- **D2:** the G2 agent layer (R11) merged ahead of G1 completion; accepted retroactively. Live agent
  execution (R12 / BE-G2-6) does not proceed until R9 (BE-G1-7) and R10 (BE-G3-5) are satisfied.
- **D3:** Beta-Entry requires R10 (BE-G3-5) and R12 (BE-G2-6) satisfied by **one authorized,
  manifest-bounded CyberGym/lab run with committed evidence**; no public-target run is required for Beta.
- **D4:** mobile-sourced API evidence does not satisfy R8; standalone API ingestion is required.

## Open items (not yet started)

R7, R8, R9, R10 are open. R12 is blocked on R9+R10. Each requires its own GATE-1-approved SPEC_BRIEF
before implementation; this roadmap authorizes none of them — it only fixes ordering and dependencies.
