# Architecture: Native Codex project orchestration

This repository packages a Codex skill, custom subagent definitions, a small local backlog/state CLI, optional project hooks, and an installer. The workflow coordinates work; it does not run a daemon, launch models itself, or guarantee provider billing. Codex performs agent routing through its native subagent support.

## Roles and model settings

The native mode pins a model and reasoning effort for each role:

| Role | Model | Effort | Responsibility |
| --- | --- | --- | --- |
| Primary director session (`orchestrator-director` profile) | `gpt-6.1-sol` | `high` | Scope, contracts, backlog, assignment, integration, decisions and final acceptance. Never implements code, even for a small task. |
| `sol_senior` | `gpt-6.1-sol` | `high` | Escalated implementation after a Luna attempt or a justified high-complexity assignment. |
| `sol_reviewer` | `gpt-6.1-sol` | `high` | Independent read-only review for high-risk work. |
| `luna_worker` | `gpt-6-luna` | `medium` | Bounded implementation tasks that meet their acceptance contract. |
| `luna_reviewer` | `gpt-6-luna` | `high` | Independent pass/fail/inconclusive review; does not edit the code under review. |
| `luna_state_editor` | `gpt-6-luna` | `low` | Makes a narrow state-file update from director instructions; director checks the short diff. |
| `astra_consultant` | `gpt-6-astra` | `high` | Rare advice on a consequential unresolved architecture question. It does not take over implementation or decisions. |

The director is the primary session selected with the `orchestrator-director` config profile; it is not a custom child agent and must not spawn another director. Exactly six standalone custom-agent files define the Luna worker, Luna reviewer, state editor, Sol senior implementer, read-only Sol reviewer, and Astra consultant. These are configured values, not a promise that every account can run every role. The configured IDs are `gpt-6.1-sol`, `gpt-6-luna`, and `gpt-6-astra`; availability depends on the active account and client. Codex must report unavailable roles or failed routing; it must never silently substitute another model. The historical name `astra_flash_builder` referred to the old DeepSeek route in some installs. It is not an alias for `astra_consultant`; inspect its configuration and migrate deliberately.

Custom subagents use Codex TOML definitions with `name`, `description`, `developer_instructions`, `model`, and `model_reasoning_effort`. The role and director templates currently contain `service_tier = "standard"`, but the official Codex schema documents this field only as a preferred string tier and does not explicitly validate either `standard` or `default` as the Standard selector. The API response label `default` is not proof that the TOML accepts that value. Treat the template value as unverified until an isolated desktop pilot confirms config loading and Standard dispatch; do not edit the active Codex home. The six child role files set `[agents] enabled = false`; the Sol reviewer also sets `sandbox_mode = "read-only"`. The primary profile selects Sol high and enables delegation. The concurrent thread cap belongs in `[agents] max_concurrent_threads_per_session` and excludes the primary agent. See the [official subagent configuration reference](https://learn.chatgpt.com/docs/agent-configuration/subagents). Do not alter global Codex configuration automatically.

## Work lifecycle

1. The director reads the project's compact state and inspects the relevant code. It writes an observable goal and acceptance criteria before implementation.
2. The director records backlog items with an ID, goal, dependencies, priority, risk, change area, acceptance criteria, owner, and status. Only ready items with completed dependencies can be assigned. One task cannot have two owners at once.
3. The director selects concurrency from independent ready work, shared resources, and review capacity, subject to two separate ceilings: the ledger reservation cap for in-flight tasks and Codex spawned-agent thread cap. Integrated tasks awaiting final completion retain a ledger reservation. Neither cap is a target; the director does not fill it automatically. Tasks that touch the same file, API contract, schema, migration, or test environment need explicit exclusive ownership or serialization. Separate worktrees are useful when Codex supports them and the tasks justify the setup; worktrees do not require commits.
4. A worker receives only its contract, relevant context, and an explicit file/resource boundary. It reports changed paths, exact commands and outcomes, and unresolved issues. It does not broaden its scope or make commits.
5. For significant work, an independent Luna reviewer prepares acceptance scenarios before coding and checks the contract, diff, surrounding code, and behavior. It returns `pass`, `fail`, or `inconclusive` with evidence and does not fix the implementation. Concrete reproducible defects go back to the owner; unclear requirements return to the director. Unrun checks remain unverified. High-risk security, permission, migration, concurrency, and similar changes need stronger independent Sol review or Astra advice; Luna approval alone does not close those risks.
6. The director integrates changes and reviews the exact combined state. A dependency becomes ready only after its prerequisite is integrated and independently verified on that snapshot. A task is complete only after integration and acceptance of that combined state.
7. The configured review-round limit includes the initial independent review and the bounded Luna correction review. Once those rounds are exhausted, the director diagnoses whether the issue is implementation difficulty, a wrong or unclear requirement, or the environment. The CLI allows a configured, finite number of escalations (default one) to `sol_senior`; it carries the current diff, reproduction, and prior attempts and adds one review round. Further work becomes a separate director-created task. An inconclusive review blocks the task. The director can replan it with a recorded resolution and, when needed, explicit new goal, scope, or acceptance fields. The ledger records old and new contract values and checks scope conflicts again at assignment. Prefer a separate follow-up task for substantially different work. No blind retry loop is allowed.
8. The director asks `luna_state_editor` for a compact state update when needed, then checks its diff.

The first version is a director-controlled workflow, not a background scheduler. The local CLI records and validates state transitions; Codex itself launches the assigned agents. See [QUICKSTART.md](QUICKSTART.md) and [INSTALL.md](INSTALL.md) for the implemented command surface.

## Review and recovery

The reviewer plans tests from the original task before seeing the implementation when the change is significant. Its findings must distinguish observed behavior from inferred risks and list both failed and unrun checks. The director resolves disagreements and judges the evidence. A correction request contains all concrete findings in one bounded package.

On interruption, preserve the working tree and recorded owner/status. Resume by inspecting the current diff and revalidating scope. Reassign only after the director confirms the previous worker stopped and its changes are safe to continue; the ledger stop-owner field is a declaration, not process control. Do not discard or overwrite an interrupted worker's changes. Keep one writer per shared file at a time.

## Competing hypotheses

Effort adaptation is a task-specific launch recommendation, not a runtime guarantee: use director xhigh for a complex initial plan, architecture, or contradictions; Luna worker high for nontrivial logic and low only for exact mechanical edits; Sol senior xhigh for a complex reproducible bug; Sol reviewer xhigh for concurrency, data-loss risk, or complex interactions; state editor medium to reconcile reports; Astra xhigh only for an especially complex architecture choice. Record the reason in the task. Apply a change only through supported launch controls; otherwise keep the configured role default and report that effort could not be adjusted. The director high default remains primary; effort changes do not change Luna-first routing.

For a persistent bug or architectural uncertainty, the director can set up two independent research tasks with different hypotheses or candidate designs. It states the question, constraints, budget, and stop condition first. Researchers return evidence and a proposed discriminating check; they do not duplicate full implementations. Astra is consulted only if its answer could change the choice. If prototypes are warranted, compare each against the same acceptance criteria and integrate only a selected, verified result.

## Project state and freshness

The durable memory is `.codex/PROJECT_STATE.md`, kept separate per project and limited to useful facts, hypotheses, plans, accepted changes, blockers, and verification outcomes. Do not put secrets, credentials, full chat history, logs, or unfiltered command output in it. One state editor writes on director instruction; the director reviews the diff. Keep confirmed facts distinct from hypotheses and plans. Record failed and not-run checks explicitly.

The existing hooks inject state on session startup, resume, clear, and compaction, and the Stop hook can issue one freshness nudge. They are convenience hooks, not a scheduler or security boundary. The local ledger is `.codex/ORCHESTRATOR.json`. Task review/integration uses an exact fingerprint of the HEAD commit, semantic index entries (modes, blob IDs, conflict stages), and dirty content. State uses a separate `state_fingerprint` from the HEAD tree, semantic index, and dirty content while excluding project-state and orchestration bookkeeping. Index stat-cache changes do not stale either fingerprint, and a state-only commit does not stale the state marker; a source commit still does even with a clean worktree. On drift, inspect affected paths before rereading larger areas. Record the `state_fingerprint` HTML marker after semantic state updates. SessionStart warns when the marker is missing; Stop is quiet for a clean unmarked legacy state and nudges once when missing or stale state coincides with dirty or HEAD drift. The bundled helper uses content fingerprints; only older hook installations without that helper retain the timestamp fallback.

## Context and spend discipline

The role templates currently contain `service_tier = "standard"`, but its acceptance by the installed Codex TOML schema is unverified. Do not replace it with `default` based on API response terminology. In an isolated desktop pilot, load the templates through a temporary Codex home and project, confirm no config error, then verify the active app exposes and uses Standard. If Standard cannot be confirmed, report the blocker and do not switch to Fast. The native collaboration interface may not expose per-call service-tier metadata, so distinguish the requested tier from observed dispatch. Do not claim a live delegation used Standard without evidence. Model and reasoning configuration are also not proof of actual routing. Give each agent only its task contract and needed context; ordinary child roles cannot delegate. Bound review and consultation rounds, and use concurrency only when work is independent and review capacity is available. No percentage savings are claimed without measurements.

## Evidence and validation limits

A configured TOML file proves only that model, effort, and a candidate `service_tier` string are present; it does not prove that the string is accepted or used for a live inference. If dispatch metadata does not expose service tier, report it as unverified. The Python ledger records manual attestations for test commands, actor/reviewer IDs, roles, fresh context, and prior-owner stop status; it does not run those commands, authenticate identities, prove context isolation, stop processes, or verify actual routing/billing. A CLI transition test proves local bookkeeping behavior; it does not prove Codex agent execution. Clearly label live delegated calls, module tests, and described-but-unexercised behavior separately. Never say a test passed if it did not run. Inspect the exact integrated diff and evidence before acceptance.

## Pilot

Use a disposable or low-risk project first. Inspect the installer's dry run and verify output in an isolated test Codex home and project. Start with one bounded, non-production task and one Luna worker, then run the independent review and inspect the integrated diff and project state. Exercise dependency blocking, interruption/reassignment, and stale-context refresh with the CLI's local checks before relying on them. Do not install into a production Codex configuration or publish the package as part of a pilot.

## Further reading

- [Quickstart](QUICKSTART.md): a first task and sample brief.
- [Installation](INSTALL.md): dry run, isolated verification, and install scope.
- [Skill instructions](skill/SKILL.md): what the director does in a task.
- [Routing](skill/references/ROUTING.md): role IDs, configuration, and verification limits.
- [Delegation contract](skill/references/DELEGATION_CONTRACT.md): task and review brief fields.
- [State policy](skill/references/STATE_POLICY.md): state schema and freshness.
