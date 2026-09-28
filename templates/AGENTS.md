<!-- Example project AGENTS.md for the Sol + DeepSeek thin-root workflow. -->
<!-- Adapt the wording to your project, then keep the rules that matter. -->

## Working agreement for this repository

For substantial coding work, use the `sol-deepseek-project-orchestrator` skill:
keep the root model as a thin technical lead, and delegate one coherent
implementation bundle to the DeepSeek worker agent.

### Root responsibilities

- Establish scope, contracts, acceptance criteria, and non-goals.
- Dispatch one coherent bundle. Do not split work into tiny sequential handoffs.
- Wait once for the completion report. Do not poll for progress.
- Review the finished diff and evidence in one batched pass.
- Send at most one batched correction request.
- Own `.codex/PROJECT_STATE.md` and keep it current before ending a turn.

### Worker rules

- The worker owns repository discovery, implementation, tests, debugging, and
  routine verification inside the stated scope.
- The worker does not spawn nested agents, commit, push, deploy, or expand scope.
- The worker returns one completion report, not play-by-play updates.
- The worker reports a blocker instead of redesigning the system around it.

### Small tasks

Formatting, a one-line fix, a tiny text change, or a simple configuration edit
do not need a worker. The root does those directly.

### Escalate to the user only for

- subjective product or UX choices that materially change the result;
- requirements that genuinely conflict;
- destructive or irreversible operations;
- credentials, spending, publication, or production deployment;
- architecture choices with product consequences;
- a genuine blocker that survived one correction cycle.

### Safety

- Never commit secrets, tokens, or machine-specific paths.
- Do not weaken tests, types, validation, or security checks to make a command pass.
- Do not publish, push, or deploy without explicit confirmation.
