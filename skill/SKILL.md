---
name: sol-deepseek-project-orchestrator
description: Use for substantial coding work when a strong root model should stay a thin technical lead and orchestrator while one DeepSeek V4.1 Flash native subagent owns repository discovery, implementation, testing, debugging, and routine verification. Preferred root is GPT-5.6 Sol at high reasoning; another root model works if the user selects one. Keeps a compact durable project state across chats and compaction.
---

# Sol + DeepSeek Project Orchestrator

Long-form explanation of this workflow, for humans and for other models:

- `ARCHITECTURE.md` - installed next to this file, and published in the repository.
- `references/ROUTING.md` - how the worker role is wired to DeepSeek, and what to do when routing is unavailable.
- `references/DELEGATION_CONTRACT.md` - the worker brief template.
- `references/STATE_POLICY.md` - the durable state schema.

Use this workflow for substantial implementation, multi-file features, debugging across components, migrations, or refactors.

The user is the product and vision supervisor. The root model is the technical lead and orchestrator. DeepSeek is the implementation worker.

## Core topology

Root -> one DeepSeek V4.1 Flash worker -> root acceptance review.

**Preferred root: GPT-5.6 Sol at high reasoning.** This is the intended shape of
the workflow: the expensive model spends its effort on scope, contracts,
judgement, and acceptance, while mechanical execution goes to the worker. If the
user selects a different root model, apply the same rules under that model; the
user's choice wins and no re-planning is needed.

The worker side is not a preference. The implementation worker is DeepSeek V4.1
Flash, reached through an explicitly configured route.

Use a native custom subagent whose `model` is an explicitly configured DeepSeek route, for example the `deepseek_worker` agent shipped in this repository (`templates/agents/deepseek-worker.toml`). Pass the route explicitly when you dispatch. Historical installations may still carry the legacy role name `astra_flash_builder`; treat that name as an alias for the same worker job, not as a different role.

Never silently substitute another paid model when the DeepSeek route is unavailable. Report the routing problem instead of falling back.

## Thin-root rule

For a substantial task, the root should normally perform exactly:

1. One scope and contract pass.
2. One coherent worker dispatch.
3. One wait for completion; do not poll or request progress updates.
4. One batched acceptance review.
5. At most one batched correction dispatch when needed.
6. One final response to the user.

Do not duplicate the worker's repository discovery, implementation loop, or full validation unless there is concrete evidence that the worker missed something important.

## Before delegation

Read `.codex/PROJECT_STATE.md` if it was not already injected by the session hook.

Inspect only enough repository context to establish:

- goal and user-visible outcome;
- scope and non-goals;
- interfaces and contracts that must remain stable;
- acceptance criteria;
- high-risk constraints;
- relevant paths if already known.

Do not read the whole repository merely to prepare the brief. Let the worker own in-scope discovery.

## Worker brief

Delegate one coherent implementation bundle, not a sequence of tiny steps. See `references/DELEGATION_CONTRACT.md` for the template. Include:

- GOAL
- WHY / user intent when relevant
- SCOPE and NON-GOALS
- CONSTRAINTS and contracts
- ACCEPTANCE CRITERIA
- KNOWN RELEVANT PATHS only when useful
- VERIFICATION expectations
- RETURN FORMAT

Tell the worker to investigate the relevant repository area itself, implement, test, diagnose failures, iterate within scope, and return one concise completion report rather than play-by-play updates.

The worker should return:

- STATUS: ready_for_review | blocked | failed
- concise summary
- changed paths
- verification commands and outcomes
- unresolved risks and blockers
- decisions that genuinely require the root or the user

## Acceptance review

Review the finished diff and evidence in one batch.

Check two lenses together:

1. specification and acceptance compliance;
2. quality, regressions, security, architecture, and maintainability proportional to the task.

Do not automatically rerun the worker's entire validation suite. Rerun a focused check only when evidence is missing, suspicious, or high-risk.

If fixes are needed, send all concrete findings in one correction request. Default to one correction cycle. If the same problem remains after a focused correction, diagnose at the root and escalate only when necessary.

## Durable project memory

`.codex/PROJECT_STATE.md` is the canonical durable working memory for the project. It is state, not history.

The root owns this file. The worker must not rewrite it unless the brief explicitly delegates a narrow state update.

Before finishing a turn, update PROJECT_STATE when the accepted work or discussion materially changes any of:

- current milestone or feature status;
- architecture, public contracts, data model, or major dependencies;
- durable product and UX decisions;
- important constraints or non-goals;
- known blockers, significant bugs, or technical risks;
- verification baseline;
- next concrete steps.

Do not record:

- routine command output;
- transient debugging hypotheses;
- failed attempts that no longer matter;
- verbose change logs;
- conversation history;
- worker play-by-play.

Edit existing bullets and delete stale state instead of appending a chronological diary. Keep the file compact; target under 10 KB and no more than roughly 200 lines.

The optional project hooks in `hooks/` inject PROJECT_STATE on session start, resume, clear, and after compaction. That is one `SessionStart` hook whose matcher includes the `compact` source, which is the supported way to reach the model after compaction. A Stop hook acts as a safety net: if repository changes occurred during the turn and PROJECT_STATE was not updated, it requests one final state-update pass before the turn ends.

See `references/STATE_POLICY.md` for the exact memory schema.

## User escalation policy

The user should supervise direction, not agent logistics.

Ask the user only when:

- a subjective product or UX choice materially changes the result;
- requirements conflict in a way that cannot be resolved from repository evidence;
- an irreversible or destructive operation is required;
- credentials, spending, external publication, production deployment, or secrets require approval;
- there are materially different architecture options with product consequences;
- one focused worker correction still leaves a genuine blocker.

Otherwise make the reasonable technical decision and continue.

## Small tasks

For trivial, clearly local work, the root may do the change itself instead of delegating. Do not summon a worker for formatting, a tiny text change, a simple configuration edit, or a one-line obvious fix.

The orchestration overhead only pays off when a task is large enough that repository discovery, implementation, and verification are genuinely worth delegating.

## Context discipline

Prefer repository state over chat history. The repository is durable memory; the chat is temporary working memory.

After a logical milestone, keep PROJECT_STATE current and consider starting a fresh chat rather than carrying obsolete debugging history indefinitely. Automatic compaction is useful, but it is not a substitute for clean durable project state.

## Verification limits

The root should not treat orchestration as verification. A worker report is evidence, not proof: it is a claim about commands that ran and outcomes that were observed. Accept work on evidence you can inspect, and keep any claim you cannot check out of the durable state.
