# KRONOS project instructions

`docs/governance/KRONOS_RND_CONTRACT.md` is authoritative: the sole binding R&D governance.

Instruction precedence, highest first:

1. Maintainer (human) GATE-1/GATE-2 authorization. Above all; the loop cannot self-authorize.
2. `docs/governance/KRONOS_RND_CONTRACT.md`. Sole binding R&D governance.
3. `docs/loop/KRONOS_LOOP_ARCHITECTURE_v7.md` and `docs/loop/CE.md`. Historical provenance only; non-binding where they overlap #2; retained unchanged.
4. `.claude/RAILS.md`. Enforcement rails; they operationalize #2.
5. `.claude/agents/*`, `.claude/commands/kronos-continue.md`. Role and command definitions.
6. Global `~/.claude` baseline. Project instructions override it.
