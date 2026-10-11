# KRONOS

**Single-operator, autonomous penetration-testing framework for authorized external-client engagements.**

Code name: *Cyber Buddy*. Successor to the author's earlier framework, JOTNAR.

> ⚠️ **Authorized use only.** KRONOS is built for penetration testing against
> targets you own or are explicitly authorized (in writing) to test. Scope is
> enforced in code via a signed engagement manifest — see the scope guard. Using
> this against systems you are not authorized to test is illegal.

---

## What makes KRONOS different

Existing AI pentest frameworks (PentAGI, RedAmon, Shannon, PentestGPT, PentestAgent)
operate within a single domain at a time — web tools find web bugs, infra tools find
infra bugs. None of them treat **mobile as a first-class source domain**, and none
model attack chains that cross domains.

KRONOS's differentiator is **cross-domain correlation**: it models and validates
attack chains that run


e.g. a hardcoded key extracted from a mobile app → authenticates to an undocumented
API endpoint → leaks an internal host → which holds an over-privileged cloud role.
That chain is invisible to every single-domain tool. Modeling and *validating* it
end-to-end is the entire reason KRONOS exists.

## Design goals

| Goal | How |
|------|-----|
| **Stronger** | Cross-domain findings graph with mobile as a first-class domain |
| **More Effective** | Autonomous recon → analyze → validate loop; the LLM queries a structured graph, never raw tool dumps |
| **Less False-Positive** | Validation-gated findings: *no evidence, no report*. Reachability + evidence-derived confidence, enforced in code |

## Architecture (high level)

- **Findings graph (Kùzu)** — embedded, Cypher-compatible, one isolated DB file per
  engagement. The single source of truth; everything queries it. *Core dependency —
  built first.*
- **Validation lifecycle** — secrets and findings move through explicit states
  (`extracted → validated → reachable`; `hypothesis → reachable → exploited → reported`).
  Confidence is derived from state, so inflation is structurally impossible.
- **Scope guard** — a signed engagement manifest is the only authorization object;
  scope is enforced at the code/data boundary, never via prompt wording.
- **Mobile ingestion** — static-first (MobSF-orchestrated); dynamic (Frida) pre-wired
  as a schema slot for later escalation on obfuscated targets.

## Status

Early development. Build order:

| Component | Status |
|-----------|--------|
| Graph core + validation lifecycle (`SPEC.md`) | **In progress** |
| Seeded cross-domain test range | Planned |
| Mobile static ingestion (MobSF) | Planned |

## Build

The current build spec is in [`SPEC.md`](./SPEC.md). Graph core is pure Python
(Kùzu + pytest), no external tooling required.

```bash
pip install kuzu pytest
pytest
```

## Benchmark — CyberGym v1.0

KRONOS is measured against a composite that can't hide a weak dimension:


reported alongside cost, with each dimension controlled against an ancestor
(Effectiveness vs JOTNAR; Precision vs validation-gate-off; Cross-domain vs
RedAmon/PentAGI/Shannon on the same seeded range). "Battle-proven" requires both a
controlled-benchmark pass *and* a live track record of externally-triaged findings
on authorized bug-bounty programs.

## License

TBD — private, single-operator project.
