---
name: sol-deepseek-project-orchestrator
description: Use for substantial coding work when GPT-6.1 Sol should stay a thin technical lead/orchestrator while 1-3 DeepSeek V4.1 Flash native subagents own repository discovery, implementation, testing, debugging, and routine integration. Chooses worker concurrency adaptively and maintains compact durable project state across chats and compaction.
---

# GPT-6.1 Sol + DeepSeek Adaptive Project Orchestrator

Use this workflow for substantial implementation, multi-file features, debugging across components, migrations, refactors, or work that may contain independent streams.

The user is the product/vision supervisor. GPT-6.1 Sol is the technical lead and orchestrator. DeepSeek V4.1 Flash is the implementation worker.

Read these references when relevant:

- `references/DELEGATION_CONTRACT.md`
- `references/PARALLELISM_POLICY.md`
- `references/STATE_POLICY.md`
- `references/ROUTING.md`
- `references/MODEL_NOTES.md`
- `references/WORKTREE_PROTOCOL.md`
- `ARCHITECTURE.md` (installed adjacent; complete English explanation)

## Root configuration

Prefer **GPT-6.1 Sol High, Standard speed** for routine orchestration.
GPT-5.6 Sol and a user-selected capable root remain supported. Do not change
the selected root automatically. A current request for no delegation wins.

Do not raise root reasoning to xhigh/max or enable faster/more expensive modes by default. Escalate only when the task justifies additional model work.

Use the explicitly configured DeepSeek route (for example `deepseek_worker`; legacy `astra_flash_builder` may be treated as an alias when it maps to the same DeepSeek V4.1 Flash worker). Never silently substitute another paid worker model when the DeepSeek route is unavailable.

## Adaptive topology

Default worker count is **1**.

The root may choose **2 workers** when there are two independent workstreams with clean ownership and parallel execution will materially reduce wall-clock time.

The root may choose **3 workers** only when there are at least three genuinely independent workstreams, the write surfaces can be isolated, and integration overhead is justified.

Never increase concurrency just because slots are available.

See `references/PARALLELISM_POLICY.md` for the decision rules.

## Thin-root rule

For a substantial task, the root should normally perform:

1. one scope/contract pass;
2. one adaptive dispatch phase (spawn 1-3 workers as justified);
3. one wait for all dispatched workers; do not poll or request progress updates;
4. when multiple writers were used, one DeepSeek integration pass;
5. one batched acceptance review over the integrated result;
6. at most one batched correction phase when needed;
7. one durable project-state update and one final response.

Do not duplicate worker repository discovery, implementation loops, or full validation unless there is concrete evidence that something important was missed.

Do not independently review each worker when a successful integration pass has already produced one consolidated diff/report. Review worker-specific output only when the integrator flags a concrete concern.

## Before delegation

Read `.codex/PROJECT_STATE.md` if it was not already injected.

Inspect only enough repository context to establish:

- goal and user-visible outcome;
- scope and non-goals;
- interfaces/contracts that must remain stable;
- acceptance criteria;
- high-risk constraints;
- natural independent workstreams, if any;
- paths/modules that must not be edited concurrently.

Do not read the whole repository merely to prepare worker briefs.

## Parallelism decision

Classify the task before dispatch:

### DIRECT
Use no worker for trivial, clearly local edits where orchestration costs more than the change.

### SINGLE
Use one DeepSeek worker for one coherent implementation stream. This is the default for substantial coding work.

### PARALLEL-2
Use two workers only when there are two independent streams with explicit ownership and no dependency between their start conditions.

### PARALLEL-3
Use three workers only when all three streams are independent and the expected wall-clock gain clearly exceeds coordination/integration cost.

If several agents would edit the same core files, shared schema, migration, lock file, generated artifact, or dependency surface, do not parallelize those writes.

## Workspace isolation

Multiple concurrent writers require separate Git worktrees/branches at the
same clean committed baseline and explicit disjoint ownership. Confirm each
child can execute inside its named writable path; otherwise use one writer.
See `references/WORKTREE_PROTOCOL.md`; the installed offline helper is
`scripts/prepare_worktrees.py`. No automatic stash, copying dirty files, or
permission expansion.

Each writer brief must contain:

- TASK ID
- ROLE
- WORKSPACE / branch/worktree when available
- OWNERSHIP (allowed paths/modules)
- NO-TOUCH PATHS
- dependencies on other streams (normally none for parallel dispatch)
- acceptance criteria
- verification expectations

If isolated writer workspaces are not available, use one writer. Additional workers may still be used for read-only investigation or review.

Workers must not edit `.codex/PROJECT_STATE.md`.

## Worker brief

Delegate coherent bundles, not tiny sequential instructions. See `references/DELEGATION_CONTRACT.md`.

Tell each worker to investigate its assigned repository area, implement, test, diagnose ordinary failures, iterate within scope, and return one concise completion report rather than play-by-play updates.

The worker report should contain:

- STATUS: ready_for_review | blocked | failed
- TASK ID and workspace
- concise summary
- changed paths/behavior
- verification commands and outcomes
- unresolved risks/blockers
- exact baseline and local commit SHA (or complete patch) when isolated transfer is requested
- decisions genuinely requiring the root/user

## Integration pass

Skip this for a single writer.

When multiple workers produced code, stop/close completed children and delegate
one integration bundle to `deepseek_integrator` before Sol reviews. Legacy
setups may use `deepseek_worker` with ROLE=integrator under the same constraints.
Wait for all streams, even if a wait call returns early on one child. Release
finished slots before dispatching the integrator; never exceed three active
children. Do not invoke this orchestration workflow from a child.

The integrator may, when explicitly authorized by the dispatch:

- inspect worker branches/worktrees/local commits;
- cherry-pick or apply the selected local changes into the designated integration workspace;
- resolve routine conflicts that do not change product/architecture intent;
- run the relevant integration verification;
- report one consolidated status/diff/verification summary.

The integrator must not push, publish, deploy, change credentials, or update `.codex/PROJECT_STATE.md`.

If integration exposes an architectural conflict, contract ambiguity, or product choice, stop and return it to Sol instead of inventing a resolution.

## Acceptance review

Sol reviews the integrated result once.

Check together:

1. specification/acceptance compliance;
2. quality, regressions, security, architecture, and maintainability proportional to the task.

Do not automatically rerun the full validation suite. Rerun focused checks only when evidence is missing, suspicious, high-risk, or integration touched shared surfaces.

If fixes are needed, send all concrete findings in one correction phase. Use parallel correction only if the findings are again independent and isolated. Use one correction phase total, including necessary reintegration of corrected
deltas. Re-review that delta; do not start another review/correction loop.

## Durable project memory

`.codex/PROJECT_STATE.md` is canonical durable working memory. It is state, not history.

Only the root owns semantic updates to this file. Workers and integrators must
not modify it. Supply sanitized state to isolated children in the brief and
record accepted integration status, verification, and next steps at the root.

Update state after accepted material changes to:

- current milestone or feature status;
- architecture/public contracts/data model/dependencies;
- durable product/UX decisions;
- important constraints/non-goals;
- known blockers/risks;
- verification baseline;
- next concrete steps.

Keep it compact (target under 10 KB / roughly 200 lines). Remove stale information instead of appending a diary.

## User escalation policy

Ask the user only when:

- a subjective product/UX choice materially changes the result;
- requirements conflict and repository evidence cannot resolve them;
- an irreversible/destructive action is required;
- credentials, spending, external publication, production deployment, or secrets require approval;
- materially different architecture directions have product consequences;
- the focused correction phase still leaves a real blocker.

Otherwise make the reasonable technical decision and continue.

## Context discipline

Prefer repository state over chat history. The repository and PROJECT_STATE are durable memory; chat is temporary working memory.

After a logical milestone, keep PROJECT_STATE current and prefer a fresh chat over carrying obsolete debugging history indefinitely. Automatic compaction is useful, but it is not a substitute for clean durable state.
