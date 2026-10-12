# Engagement cleanup / teardown registry (`kronos.cleanup`)

A generalization of what the CyberGym orchestrator already did ad-hoc
in a `finally` block: every ephemeral artifact an engagement creates —
Docker containers/networks/volumes, temp files, temp credential files,
spawned processes — gets registered once, and one chokepoint
(`CleanupRegistry.teardown_all()`) guarantees it's disposed of. Built
because an authorized external-client engagement must leave **nothing
behind**, and because the next layer (autonomous agents spawning their
own containers/processes) needs this plumbing to already exist
(SPEC_BRIEF6 §0).

## Design north star

**Best-effort, never silently swallowed, budget-exempt.** A teardown
failure is recorded on a `TeardownReport`, not hidden — but it never
blocks the rest of the cleanup, and it never crashes the orchestrator.
Teardown runs whether the engagement finished cleanly, raised, or blew
through its budget; it has no dependency on spare budget to do its job.

## Modules

- **`registry.py`** — `CleanupRegistry`, the chokepoint.
  `register(kind, handle, teardown, *, detail)` appends an artifact and
  the zero-arg callable that disposes it; registration order is
  preserved. `teardown_all()` disposes everything in **LIFO** order
  (reverse of creation), catching each item's error independently so
  one failure never blocks the rest, and returns a `TeardownReport`
  (per item: kind, detail, outcome `done`/`already_gone`/`failed`,
  error if any). It's idempotent — a second call reports every
  already-disposed item as `already_gone` without re-invoking its
  teardown callable, while a previously-`failed` item is retried (its
  disposal genuinely never happened the first time). The
  context-manager form, `with CleanupRegistry() as reg:`, runs
  `teardown_all()` on exit **even when the body raises** — the
  artifacts still get cleaned up, then the original exception
  propagates unchanged. This is the crash-safety mechanism (FORK-G).
- **`kinds.py`** — teardown-callable factories for each tracked kind:
  `remove_container`/`remove_network`/`remove_volume` (raw `docker rm
  -f`/`network rm`/`volume rm`, treating "no such object" as
  already-gone, not a failure), `compose_down` (wraps an existing
  `compose(*args)` helper — e.g. the CyberGym range's own — as a single
  teardown callable; `docker compose down` is already a no-op on an
  already-down stack), `remove_file`/`remove_dir` (plain filesystem
  cleanup), `shred_credential_file` (overwrites a temp credential file
  with random bytes before unlinking it — removed from disk, not just
  logged), and `terminate_process` (pre-wired for the agent layer;
  nothing spawns long-lived processes today).
- **`write_teardown_report(engagement_dir, report)`** — writes the
  report to the engagement dir, alongside the budget ledger snapshot.

## Why teardown can't be blocked by the budget (FORK-F)

Nothing under `src/kronos/cleanup/` imports `kronos.budget`, calls
`BudgetLedger.charge`, or can raise `BudgetExceeded`. This is mechanical,
not just a convention — `tests/test_cleanup.py` greps the whole module
tree for it, the same way `tests/test_budget.py` proves budget
enforcement never reaches into the lifecycle's forward mutator. An
engagement that burns its entire budget still gets a full, normal
teardown: `BudgetExceeded` propagating out of the engagement body is
exactly the "body raises" case the context-manager form exists for,
not a special case cleanup has to detect.

## Why the context manager, not `atexit`/signal handlers (FORK-G)

Teardown is tied to the *engagement's* scope — created when the
engagement's `CleanupRegistry` is, torn down when its `with` block
exits — not to the whole process's lifetime. That makes it
deterministic and directly testable (register artifacts, raise, assert
teardown happened) without needing to kill the interpreter to exercise
the crash path. `atexit`/signal handlers are unreliable under a hard
kill and awkward to unit-test, so they're not used as the primary
mechanism here.

## Integration: `cybergym/kronos_validation_run.py`

The orchestrator's old ad-hoc `finally: compose("down", "-v")` is
replaced by a `CleanupRegistry`: the Docker range is registered
(`compose_down(compose)`) right after `docker compose up` succeeds, the
engagement body runs inside `with registry:`, and on exit — happy path,
`BudgetExceeded`, or any other exception — `teardown_all()` runs
exactly once per registered artifact, no second competing teardown
path left anywhere in the script. The resulting `TeardownReport` is
written to the engagement dir next to `budget_ledger.json`.
