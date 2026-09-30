# Adaptive Parallelism Policy

Default worker count: **1**.

Parallelism exists to reduce wall-clock time. It is not a utilization target.

## Decision table

| Mode | Workers | Use when |
| --- | ---: | --- |
| DIRECT | 0 | tiny local edit; delegation overhead exceeds implementation |
| SINGLE | 1 | one coherent implementation stream; default substantial task |
| PARALLEL-2 | 2 | two independent streams with clean ownership |
| PARALLEL-3 | 3 | three independent streams with isolation and clear time benefit |

## Required conditions for parallel writers

All must be true:

1. streams can start immediately without waiting for each other;
2. file/module ownership can be made explicit;
3. workers do not edit the same shared mutable surface;
4. each stream has independent acceptance criteria;
5. integration can be performed as one bounded pass afterward.

## Do not parallelize concurrent writes to

- the same source file or component;
- the same DB migration/schema change;
- shared generated artifacts;
- package lock files when both streams may change dependencies;
- the same central routing/config table;
- an interface while another worker depends on the not-yet-final interface.

When these surfaces are unavoidable, keep one writer and use extra workers only for read-only investigation/review.

## Isolation policy

For two or more writers, require one Git worktree/branch per worker at the same
clean committed baseline. Give the integrator its own worktree. If safe isolated
dispatch is unavailable, use one writer. Worktrees share Git objects; they are
not a security sandbox. See `WORKTREE_PROTOCOL.md`.

Example:

```text
main
  |
  +-- worktree/task-a  -> worker A
  +-- worktree/task-b  -> worker B
  +-- worktree/task-c  -> worker C
```

A worker may create a local commit in its isolated worktree only when its dispatch explicitly authorizes `LOCAL_COMMIT: yes` for later integration. Local commit permission never includes push/publish/deploy.

## Integration

With multiple writers, run one DeepSeek integration pass before Sol review.

Integrator inputs:

- completed worker task IDs (completion is not root acceptance);
- worktree/branch paths;
- local commit SHAs or patch locations;
- global acceptance criteria;
- integration verification commands;
- no-touch constraints.

Integrator output:

- STATUS
- integrated summary
- integrated changed paths
- conflicts resolved
- conflicts requiring Sol/user
- verification commands/results
- unresolved risks

Do not make Sol review each worker separately unless the integrator identifies a concrete issue.

## Failure behavior

- One blocked stream does not automatically cancel independent successful streams.
- Do not spawn replacement agents reflexively.
- Diagnose why a stream blocked before retrying.
- Keep the overall correction budget to one focused correction phase, including
  reintegration of its deltas, unless the user explicitly asks to continue.
- Wait for every dispatched stream, stop/close completed children, and then start
  one integrator. A partial result cannot satisfy the original global criteria.
- Do not delegate from workers/integrators. Keep at most three active children.
