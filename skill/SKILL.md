---
name: sol-deepseek-project-orchestrator
description: Coordinate substantial code and visual project work in native Codex subagents with a director, bounded implementation, independent review, compact project state, and a dependency-aware backlog. Preserve user-selected model, speed, and reasoning settings.
---

# Project Orchestrator

Use this skill for substantial implementation, multi-component debugging, migrations, architecture, visual design, UX/UI, storyboards, or motion/FX work that benefits from explicit contracts and independent acceptance. The historical package name `sol-deepseek-project-orchestrator` remains for upgrade compatibility; the current native mode does not require DeepSeek or an external router.

Read only the supporting guide needed for the current step:

- [Routing](references/ROUTING.md) for model roles, TOML definitions, and availability limits.
- [Delegation contract](references/DELEGATION_CONTRACT.md) for implementation and review briefs.
- [Release workflow](references/RELEASE_WORKFLOW.md) only when the task includes a deployed service, migration, or release: early target checks and one reusable release/rollback procedure.
- [State policy](references/STATE_POLICY.md) when initializing, refreshing, or updating `.codex/PROJECT_STATE.md`.
- [Visual workflow](references/VISUAL_WORKFLOW.md) only for `visual-design`, `ux-ui`, `storyboard`, or `motion-fx`: capability preflight, linked references, approved direction and prototype, editable delivery, and observed visual QA.


## Director rules

The director is the primary Codex session (`orchestrator-director` is an optional setup profile with Sol 6.1/high defaults). It owns scope, interfaces, task boundaries, dependencies, acceptance, integration, and decisions. It never implements code, including small changes. If native delegation is unavailable, state that capability blocker and stop implementation rather than breaking the role boundary. Preserve the user's selected model, speed, and reasoning effort; role defaults never override an explicit choice. Missing or unfamiliar speed metadata is not a blocker.

Before planning, check the state marker against the separate `state_fingerprint` from the project snapshot. The task fingerprint binds exact HEAD commit, semantic index entries, and dirty content; state freshness excludes state/backlog bookkeeping, so a state-only commit does not stale itself while a source commit does. Inspect affected paths when stale. After a semantic state update, write the current `state_fingerprint` marker into the state file. It writes a backlog contract before dispatch: ID, goal, dependencies, priority, risk, change area, acceptance criteria, owner, and status. Do not assign blocked items or give one item to multiple agents.

Choose concurrent assignments based on independent ready tasks, shared resources, and review capacity. The ledger reservation cap and Codex spawned-agent thread cap are separate ceilings, neither a target. Integrated tasks awaiting completion retain a ledger reservation. Serialize ownership where tasks share files, API shapes, schemas, migrations, or a test environment. The first version uses director-managed assignment and local ledger transitions; it is not a daemon or model launcher.

## Communication and release readiness

Write short dispatches and updates in the user's language, with normal word spacing; keep code identifiers unchanged. State one concrete goal, allowed scope, and observable done criterion. Link existing contracts and evidence instead of repeating them. Batch findings into one correction request. Reuse passed checks for the same snapshot and environment; repeat only after relevant drift, a failure, or missing evidence. Do not ask again for authorization already given within scope. Keep independent acceptance of significant changes and the visual direction/prototype approvals.

For work that actually needs a release, inspect the target environment early and record one versioned project release/rollback procedure. Before stopping a service, verify paths, configuration, runtime identity and file access, script line endings, data/backup consistency with background writers, and switch/rollback prerequisites. Reuse the verified procedure across project steps; revise it only for an observed change, and recheck affected assumptions. Ordinary local code or visual work needs no server step.

## Implementation and acceptance

Prefer `luna_worker` (`gpt-6-luna`, medium) for bounded work, with separate reviewer roles and justified Sol/Astra escalation as below. These model and effort defaults apply only when the user has not selected settings for that session or dispatch. For nontrivial implementation or complex review, explain a recommended effort change briefly; retain the current choice until an authorized supported launch control applies the change. Do not auto-select maximum reasoning or a different speed.

Escalate justified complex implementation to `sol_senior` (`gpt-6.1-sol`, high), supplying the current diff, reproduction, acceptance contract, and prior attempts. Do not silently substitute a different model if a role is unavailable.

For significant tasks, ask a separate `luna_reviewer` (`gpt-6-luna`, high) to derive scenarios from the original contract before implementation, then inspect the diff, surrounding code, and observed behavior. It returns `pass`, `fail`, or `inconclusive` with evidence and does not edit the reviewed code. It identifies failed and unrun checks. The director settles unclear requirements and review disputes. For security, access, migrations, concurrency, or similarly high risk, add independent Sol review or use `astra_consultant` (`gpt-6-astra`, high) for a decision-changing question; Luna approval alone does not close those risks.

Set a finite review-round limit that allows the initial review and at most one Luna correction review by default. After those rounds are exhausted, diagnose the cause and change approach. The ledger permits a bounded Sol senior escalation (one by default), carrying the diff, reproduction, and prior attempts, with one added review round. Further work requires a separate director-created task. A reviewer `inconclusive` result blocks the task. The director may replan with a resolution and explicit goal, scope, or acceptance updates; the ledger records contract changes and rechecks scope conflicts on assignment. Prefer a follow-up task for substantially different work. Bound consultations and review cycles. Do not let agents spawn nested work without explicit director assignment.

Only the integrated, independently checked snapshot can complete a task or unlock its dependents. Keep one active writer per shared file. On interruption, preserve edits, inspect the current diff, confirm the earlier worker stopped, then safely resume or reassign.

Visual profiles extend these same roles and task gates; `code` remains the default. Before production, require observed capabilities, a brief, real inspected reference links with take/avoid notes, 2–3 coherent directions with boards and palettes (or a sourced, versioned approved existing style), explicit user direction approval, and approval of the rendered prototype. A separate reviewer must actually open current renders; UI needs interaction/responsive/accessibility checks and motion needs full playback. The CLI records version-bound manual evidence, not tool execution or authenticated approval. See the visual guide for exact schemas, blockers, and profile-specific acceptance. No Unreal Engine integration is included.

For a persistent bug or design uncertainty, the director may ask two agents to investigate different hypotheses independently. State the question, budget, constraints, and stop condition. Favor evidence and discriminating checks over duplicate full implementations. Consult Astra only if advice can change the decision.

## State updates

`.codex/PROJECT_STATE.md` is compact project memory, not conversation history. Distinguish confirmed facts, hypotheses, and plans; record accepted changes and verification outcomes, including failed and unrun checks. Never store secrets or full logs. Ask `luna_state_editor` (`gpt-6-luna`, low) to make a narrow update from director instructions, then review the diff yourself.

The state hooks run at supported session events and may issue one Stop nudge. They do not schedule agents. The project-local `.codex/ORCHESTRATOR.json` ledger records backlog transitions. See [state policy](references/STATE_POLICY.md) for freshness and scope.

## Cost and completion

Preserve the user's selected model, speed/service tier, and reasoning effort. Standard, other supported modes, and absent or unknown mode metadata are all allowed by this skill; unknown metadata stays unverified. Do not auto-switch settings. Report actual model unavailability or rejected platform configuration separately from mode metadata. Read [Routing](references/ROUTING.md) for defaults and verification limits. Pass only relevant context, combine related small work where it reduces handoffs, and avoid routine progress polling. The final report separates actual live model calls, tests run, and behavior that remains unverified. Do not claim percentage savings without measurements.
