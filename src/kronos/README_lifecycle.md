# Validation Lifecycle (`lifecycle.py`)

The false-positive killer. "No evidence, no report."

## State machines

```
SECRET:   extracted -> validated -> reachable -> dead
                 \__________________________^      ^
                  (any of extracted/validated/reachable can go -> dead)

FINDING:  hypothesis -> reachable -> exploited -> reported
               \____________\____________\__> discarded
                (any of hypothesis/reachable/exploited can go -> discarded)
```

Both machines are strictly linear going forward — a SECRET can't jump
`extracted -> reachable` without passing through `validated`, and a
FINDING can't jump `hypothesis -> exploited` without passing through
`reachable`. `reported` and `discarded` (FINDING) and `dead` (SECRET) are
terminal: nothing transitions out of them. This is stricter than SPEC.md
strictly requires but matches its intent — reachability is supposed to be
a real precondition for exploitation, not a label you can skip. See
`DECISIONS.md` if a later brief needs a shortcut path.

## Confidence table (the only values `derive_confidence` ever returns)

| status                          | confidence |
|----------------------------------|:----------:|
| `exploited` / `reported`         | 10         |
| `reachable`, has evidence        | 9          |
| `reachable`, no evidence yet     | 7          |
| `validated`                      | 7          |
| `extracted` / `hypothesis`       | 3          |
| `dead` / `discarded`             | 0          |

SPEC.md pins the `exploited`/`reachable+evidence` (9-10), `validated`
(7-8), and `hypothesis`/`extracted` (<7) brackets explicitly. It's silent
on plain `reachable` without evidence yet, and on `dead`/`discarded`;
this module fills both gaps at the floor of the next bracket down (7) and
at 0 respectively — see `DECISIONS.md` for why.

## Why this can't be bypassed

`EngagementGraph` has no generic "set status" or "set confidence" method.
The only two functions that ever change these fields —
`advance_secret_status` and `advance_finding_status` — are this module's,
and both run every hard rule before writing anything:

- a transition not listed in `SECRET_TRANSITIONS`/`FINDING_TRANSITIONS`
  raises `LifecycleError` before any write happens;
- `reported` independently re-checks `status == exploited` and
  `>= 1 EVIDENCE node` (SPEC.md rule 1), even though the transition table
  alone already guarantees the former;
- `reported` additionally requires that if the finding has any
  `references -> SECRET` anchors at all, at least one of them is
  `can_anchor_finding` (status `reachable` AND has an in-scope
  `authenticates_to` target) — SPEC.md rule 2;
- `confidence` is computed by `derive_confidence`, a pure function with no
  parameter for an arbitrary override — there is no code path through
  which a caller's number ever reaches the database.

A SECRET whose only `authenticates_to` target is out-of-scope still
becomes `reachable` (it's real, it gets recorded) but `scope_note` gets
stamped with a reason and `can_anchor_finding` returns `False` for it
forever after — SPEC.md rule 4. It exists in the graph; it can never
anchor a report.
