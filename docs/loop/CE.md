Initialize the KRONOS R&D pipeline in the repository at:

`/home/void/Void-Projects/KRONOS-Artifacts/KRONOS-void/`

First inspect the existing `CLAUDE.md`, `CE.md`, `.claude/` files, repository state, and the documented five-step workflow. Treat existing project rules as authoritative. Preserve local changes and existing safeguards. If the path or required files are unavailable, stop and report that.

## Team

Use these roles:

- **Opus orchestrator:** the primary Claude Code session. It owns research coordination, task planning, checkpoints, gates, and final verification. It dispatches the other agents; don’t create an unused orchestrator subagent.
- **Sonnet researcher:** read-only codebase research; returns cited findings to the orchestrator.
- **Sonnet builder:** implements only files and changes allowed by a GATE-1-approved brief.
- **Haiku reviewer:** independently reviews the approved brief and diff, then reports evidence and test results.

Create the three subagent definitions in `.claude/agents/`. Give the orchestrator’s primary session the supported delegation capability. Keep role descriptions concise and specific about when to delegate.

The researcher must not be told to write `context.txt` while its tools are read-only. Prefer having it return findings for the orchestrator to save. The reviewer may run only project-approved local tests; don’t describe it as read-only if it has Bash access, and don’t give it unrestricted shell access. Use the existing permission controls to enforce tool and file boundaries.

## Pipeline state

Create `.claude/pipeline/` with the step folders required by the existing five-step contract. Before adding state files, identify their owner, format, and purpose from `CE.md` and `CLAUDE.md`. The orchestrator owns task and checkpoint state; agents must not independently overwrite shared state.

GATE-1 is my approval of a brief. Do not label reviewer output `gate1.json`. Use the existing contract’s names and schema, or propose a clear review-evidence filename if none exists.

## Workflow and limits

The outer supervisor loads the contract and checkpoint, starts or resumes work, collects results, verifies progress, and chooses the documented outcome: continue, retry, replan, escalate, success, or fail. Use Claude Code’s native tool cycle for each agent’s inner decide–act–observe loop; don’t build a second tool executor.

Keep all KRONOS R&D coordination in this Kali Claude Code workspace. Preserve the project’s approval gates, usage-limit stop and manual `continue` resume, iteration bounds, and scope controls. Keep testing within the currently authorized environment; do not enable live-target work or expand scope.

## Changes and verification

Make only the necessary pipeline directories, state templates, agent definitions, and minimal `CLAUDE.md`/`CE.md` updates. Validate that the agent files load, their models and tools are available, and permissions match their roles. Do not modify KRONOS product code, signed scope data, or external repository settings, and do not start the R&D task cycle yet.

When finished, report the files changed, the five-step role/state mapping, the verified agent configuration, and any unresolved setup issue.
