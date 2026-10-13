# Architecture: Native Codex project orchestration

This repository packages a Codex skill, custom subagent definitions, a small local backlog/state CLI, optional project hooks, and an installer. The workflow coordinates work; it does not run a daemon, launch models itself, or guarantee provider billing. Codex performs agent routing through its native subagent support.

## Roles and model settings

The native mode supplies model and reasoning defaults for each role; explicit user choices take precedence:

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

Role model and effort values are defaults for an explicitly chosen orchestration setup. The user's selected model, speed/service tier, and reasoning effort take precedence. Preserve them in the primary session and dispatch; do not change them automatically or apply role defaults over an explicit choice. Recommend a different effort only when useful, and apply it only through supported controls with user authorization. Omit service-tier overrides from new templates so the client can inherit the selected speed. Standard, other supported modes, and absent or unknown mode metadata do not block work. Unknown metadata remains unverified; do not invent a selector or map UI labels to TOML values. If the platform rejects an actual model or setting, describe the concrete availability/configuration error separately and preserve the selection; do not call it a Standard-mode failure or silently substitute a model. Sandbox, approvals, and platform limits still apply. Child roles disable nested delegation; the Sol reviewer remains read-only. The primary profile enables delegation and sets a separate child-thread cap. These role and safety constraints remain in force.

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

## Release readiness and communication

For deployed work, inspect the target early: paths/configuration, container identity and runtime file access, script line endings, and backup consistency with all background writers. Reuse one versioned project release/rollback procedure and check switch prerequisites before stopping services. Local tasks that need no deployment omit this stage. See [Release workflow](skill/references/RELEASE_WORKFLOW.md).

Send concise briefs and updates in the user's language with normal word spacing, a concrete goal, scope, and done criterion. Link existing contracts; batch corrections; reuse passed checks for an unchanged snapshot and environment. Recheck only relevant drift or missing evidence, and preserve independent acceptance of significant changes and visual approvals.

## Review and recovery

The reviewer plans tests from the original task before seeing the implementation when the change is significant. Its findings must distinguish observed behavior from inferred risks and list both failed and unrun checks. The director resolves disagreements and judges the evidence. A correction request contains all concrete findings in one bounded package.

On interruption, preserve the working tree and recorded owner/status. Resume by inspecting the current diff and revalidating scope. Reassign only after the director confirms the previous worker stopped and its changes are safe to continue; the ledger stop-owner field is a declaration, not process control. Do not discard or overwrite an interrupted worker's changes. Keep one writer per shared file at a time.

## Visual profile extension

`add --profile` defaults to `code`; `visual-design`, `ux-ui`, `storyboard`, and `motion-fx` add visual evidence to the same task record. They do not add role files, change Luna-first routing, replace code acceptance, or integrate Unreal Engine. Sol directs and resolves scope; workers make the assets; a separate reviewer inspects the result. The director never uses approval bookkeeping to approve a design for the user.

The preproduction contract is a brief, real inspected reference links with take/avoid notes, and 2–3 coherent directions with boards and exact palettes. Motion includes linked motion examples. An existing approved style is allowed with its source, version, scope, and user approval. Record explicit user approval of the current direction/palette, then of a rendered prototype, before the production transition. Delivery includes all agreed editable, preview, and report formats. The four profiles have one [focused visual reference](skill/references/VISUAL_WORKFLOW.md) with their schemas and acceptance checklists.

The spec starts a visual revision and fingerprints existing board files. Preflight declares all capability categories with observed evidence; required categories must be available. Generation is optional unless required by the spec. Missing required capability is a blocker, not permission to substitute an unreviewable output. A reduced scope needs the user's sourced agreement and a new spec; profile-level requirements cannot be waived. The runtime binds preflight/approvals to spec and contract revisions, prototype approval to the exact prototype, and QA to final artifact bytes, approvals, owner history, and attempt. New specs reset dependent evidence. Changing an approved direction or palette requires a new spec and approvals.

The visual stage (`directions` → `prototype` → `production` → `qa` → `delivery`) supplements the existing task states. `visual-qa` requires an independent reviewer, current previews with exact content fingerprints, observation/tool/source records, and profile checks. Reviewers must actually open renders/screenshots and editable sources; UI adds interactions, responsive layouts, and accessibility; motion requires full-duration playback with timing, transitions, and continuity checks. A text `PASS` or motion stills are insufficient. Passing visual evidence supplements normal `review`, `integrate`, and `complete`; both the visual bindings and exact combined repository snapshot must remain current. Completion records delivery but does not transfer files.

The CLI checks manual record consistency and file bytes, not visual quality, actual tool execution, user identity, or authenticity of approval. `stats --format json` adds a `visual` sidecar with profile counts and categorized stage/revision/reason/result records; source links, paths, user quotes, and findings are omitted. Its model/token/cost observations stay `null`. CSV retains its fixed event columns. This is workflow bookkeeping, not generation telemetry or a savings measurement.

## Competing hypotheses

Effort changes are recommendations for an explicitly authorized, supported launch control. Preserve selected effort and speed otherwise; role defaults and complexity never authorize an automatic settings switch. Record an approved adjustment and its reason.

For a persistent bug or architectural uncertainty, the director can set up two independent research tasks with different hypotheses or candidate designs. It states the question, constraints, budget, and stop condition first. Researchers return evidence and a proposed discriminating check; they do not duplicate full implementations. Astra is consulted only if its answer could change the choice. If prototypes are warranted, compare each against the same acceptance criteria and integrate only a selected, verified result.

## Project state and freshness

The durable memory is `.codex/PROJECT_STATE.md`, kept separate per project and limited to useful facts, hypotheses, plans, accepted changes, blockers, and verification outcomes. Do not put secrets, credentials, full chat history, logs, or unfiltered command output in it. One state editor writes on director instruction; the director reviews the diff. Keep confirmed facts distinct from hypotheses and plans. Record failed and not-run checks explicitly.

The existing hooks inject state on session startup, resume, clear, and compaction, and the Stop hook can issue one freshness nudge. They are convenience hooks, not a scheduler or security boundary. The local ledger is `.codex/ORCHESTRATOR.json`. Task review/integration uses an exact fingerprint of the HEAD commit, semantic index entries (modes, blob IDs, conflict stages), and dirty content. State uses a separate `state_fingerprint` from the HEAD tree, semantic index, and dirty content while excluding project-state and orchestration bookkeeping. Index stat-cache changes do not stale either fingerprint, and a state-only commit does not stale the state marker; a source commit still does even with a clean worktree. On drift, inspect affected paths before rereading larger areas. Record the `state_fingerprint` HTML marker after semantic state updates. SessionStart warns when the marker is missing; Stop is quiet for a clean unmarked legacy state and nudges once when missing or stale state coincides with dirty or HEAD drift. The bundled helper uses content fingerprints; only older hook installations without that helper retain the timestamp fallback.

## Context and spend discipline

Role model and effort values are defaults for an explicitly chosen orchestration setup. The user's selected model, speed/service tier, and reasoning effort take precedence. Preserve them in the primary session and dispatch; do not change them automatically or apply role defaults over an explicit choice. Recommend a different effort only when useful, and apply it only through supported controls with user authorization. Omit service-tier overrides from new templates so the client can inherit the selected speed. Standard, other supported modes, and absent or unknown mode metadata do not block work. Unknown metadata remains unverified; do not invent a selector or map UI labels to TOML values. If the platform rejects an actual model or setting, describe the concrete availability/configuration error separately and preserve the selection; do not call it a Standard-mode failure or silently substitute a model. Sandbox, approvals, and platform limits still apply. Give each agent only its contract and needed context; reuse current evidence and batch related findings. Bound independent review and consultations. No percentage savings are claimed without measurements.

## Evidence and validation limits

TOML parsing and local validation check syntax, optional selection field types, and role/safety contracts; they do not prove live dispatch or availability. Absent or unknown speed metadata remains unverified and never blocks the workflow by itself. The Python ledger records manual test, identity, freshness, and stopped-owner declarations; it does not execute tests, authenticate identities, stop processes, or verify routing/billing. Distinguish local module tests, actual delegated calls, and unexercised behavior.

## Pilot

Use a disposable or low-risk project first. Inspect the installer's dry run and verify output in an isolated test Codex home and project. Start with one bounded, non-production task and one Luna worker, then run the independent review and inspect the integrated diff and project state. Exercise dependency blocking, interruption/reassignment, and stale-context refresh with the CLI's local checks before relying on them. Do not install into a production Codex configuration or publish the package as part of a pilot.

## Further reading

- [Quickstart](QUICKSTART.md): a first task and sample brief.
- [Installation](INSTALL.md): dry run, isolated verification, and install scope.
- [Skill instructions](skill/SKILL.md): what the director does in a task.
- [Routing](skill/references/ROUTING.md): role IDs, configuration, and verification limits.
- [Delegation contract](skill/references/DELEGATION_CONTRACT.md): task and review brief fields.
- [State policy](skill/references/STATE_POLICY.md): state schema and freshness.
- [Visual workflow](skill/references/VISUAL_WORKFLOW.md): preproduction gates, exact evidence shapes, visual CLI, and four acceptance profiles.
