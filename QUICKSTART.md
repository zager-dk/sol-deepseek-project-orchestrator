# Quickstart

From a clean checkout to one finished, reviewed bundle.

## 1. Install

```bash
python scripts/install.py --project ~/code/my-project --codex-home ~/.codex --hooks
python scripts/verify_install.py --project ~/code/my-project --codex-home ~/.codex --self-test
```

Expect a plan, then a summary with `created` counts, then a verification pass
with `errors: 0`. If you get exit code 3, read the conflict list and re-run with
`--force`.

## 2. Restart Codex and trust the hooks

Reopen Codex so it picks up the new skill and the `deepseek_worker` agent. If you
installed hooks, run `/hooks`, review the project entries, and trust them.

## 3. Fill in the state file

Open `.codex/PROJECT_STATE.md` in your project and replace the placeholders:

- **Project intent** - one paragraph, what the product is for;
- **Current milestone** - the one thing being finished now, with a definition of
  done;
- **Architecture / contracts** - the facts a new chat must not rediscover the
  hard way;
- **Verification baseline** - the commands that define "healthy".

Keep it under a screen or two. It is memory, not documentation.

## 4. Ask for the work

Ask normally, and let the skill handle the shape:

```text
Add CSV export to the report page. Use the orchestrator workflow.
```

What the root should do next:

1. read `.codex/PROJECT_STATE.md` (or receive it from the hook);
2. inspect just enough of the repository to fix scope and contracts;
3. dispatch one brief to `deepseek_worker`;
4. wait once;
5. review the diff and the evidence in one batch;
6. send at most one batched correction;
7. accept, update `PROJECT_STATE.md`, and answer you.

## 5. What a good dispatch looks like

```text
GOAL
Add CSV export to the report page.

SCOPE
- a route that streams the current report as CSV
- a download control on the report page
- tests for the happy path and the 401 path

NON-GOALS
- no other export formats, no changes to the report query

ACCEPTANCE CRITERIA
- GET /reports/:id/export.csv returns text/csv with a header row and one row per record
- unauthenticated requests still return 401

VERIFICATION
- run the repository test and lint commands for the touched package

RETURN FORMAT
- STATUS / SUMMARY / CHANGED / VERIFICATION / RISKS / DECISIONS
```

The full template lives in `skill/references/DELEGATION_CONTRACT.md`, and
`examples/worker-brief-example.md` has a filled version with notes.

## 6. What you should not have to supervise

- which model ran which step;
- how many correction cycles happened (zero or one);
- whether the worker polled for progress (it should not);
- the command names in the verification report.

If you find yourself relaying messages between two agents, the workflow is being
used wrong.

## 7. When a task is too small

Say so, or just ask for it plainly. Formatting, a one-line fix, or a copy change
should be done directly by the root. The architecture document explains the
threshold in [the small-task exception](ARCHITECTURE.md#small-task-exception).

## 8. Try adaptive work after one successful single-worker task

Install with `--adaptive` and verify with `--adaptive --self-test`. Keep the
same prompt style: the root chooses 1, 2, or 3 workers and explains its choice
briefly. Ask for parallel work only when independent streams exist. The root
freezes shared contracts, gives writers isolated paths with disjoint ownership,
waits for all outputs, and starts one DeepSeek integrator. Sol reviews one
consolidated result and uses at most one correction phase total.

See [parallel-work-example.md](examples/parallel-work-example.md) and
[WORKTREE_PROTOCOL.md](skill/references/WORKTREE_PROTOCOL.md) for a complete
example, explicit local-commit authority, and safe workspace preparation.
If the root cannot dispatch inside the isolated writable paths, keep one writer.
Do not paste keys or move secret files into those workspaces.

## 9. Before ending a session

The root updates `.codex/PROJECT_STATE.md` if anything durable changed. If the
`Stop` hook notices repository changes and a stale state file, it asks for one
extra pass. Answer it with a real state update, or with one line saying nothing
durable changed.

That is the whole loop. Next session, the state file orients the new chat in
seconds instead of replaying history.
