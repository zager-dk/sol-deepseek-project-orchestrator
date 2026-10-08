---
name: sol-deepseek-project-orchestrator
description: Coordinate substantial project work in native Codex subagents with a Sol 6.1 director, Luna implementation and independent review, and rare Astra consultation. Keeps compact per-project state and a manually managed dependency-aware backlog.
---

# Project Orchestrator

Use this skill for substantial implementation, multi-component debugging, migrations, or architecture work that benefits from explicit contracts and independent acceptance. The historical package name `sol-deepseek-project-orchestrator` remains for upgrade compatibility; the current native mode does not require DeepSeek or an external router.

Read only the supporting guide needed for the current step:

- [Routing](references/ROUTING.md) for model roles, TOML definitions, and availability limits.
- [Delegation contract](references/DELEGATION_CONTRACT.md) for implementation and review briefs.
- [State policy](references/STATE_POLICY.md) when initializing, refreshing, or updating `.codex/PROJECT_STATE.md`.


## Director rules

The director is `orchestrator_director` (`gpt-6.1-sol`, high). It owns scope, interfaces, task boundaries, dependencies, acceptance, integration, and decisions. It never implements code, including small changes. If native delegation is unavailable, state that blocker and stop implementation rather than breaking the role boundary.

Before planning, check the state marker against the separate `state_fingerprint` from the project snapshot. The task fingerprint binds exact HEAD commit, semantic index entries, and dirty content; state freshness excludes state/backlog bookkeeping, so a state-only commit does not stale itself while a source commit does. Inspect affected paths when stale. After a semantic state update, write the current `state_fingerprint` marker into the state file. It writes a backlog contract before dispatch: ID, goal, dependencies, priority, risk, change area, acceptance criteria, owner, and status. Do not assign blocked items or give one item to multiple agents.

Choose concurrent assignments based on independent ready tasks, shared resources, and review capacity. The ledger reservation cap and Codex spawned-agent thread cap are separate ceilings, neither a target. Integrated tasks awaiting completion retain a ledger reservation. Serialize ownership where tasks share files, API shapes, schemas, migrations, or a test environment. The first version uses director-managed assignment and local ledger transitions; it is not a daemon or model launcher.

## Implementation and acceptance

Use `luna_worker` (`gpt-6-luna`, medium) for bounded work; request high for nontrivial logic or low only for exact mechanical edits when supported, and record why. Use `sol_senior` (`gpt-6.1-sol`, high) only after justified escalation; request xhigh for a complex reproducible bug only through supported launch controls and record why. The primary Sol director defaults to high; it may request xhigh for a complex initial plan, architecture, or contradictions only when supported. The Luna reviewer defaults to high; Sol reviewer defaults to high and may request xhigh for concurrency, data-loss risk, or complex interactions. State editor defaults to low and may request medium to reconcile reports. Astra defaults to high and may request xhigh only for an especially complex architecture choice. Effort changes are instructions for launch controls, not a runtime capability guarantee. This policy preserves Luna-first routing.

Escalate justified complex implementation to `sol_senior` (`gpt-6.1-sol`, high), supplying the current diff, reproduction, acceptance contract, and prior attempts. Do not silently substitute a different model if a role is unavailable.

For significant tasks, ask a separate `luna_reviewer` (`gpt-6-luna`, high) to derive scenarios from the original contract before implementation, then inspect the diff, surrounding code, and observed behavior. It returns `pass`, `fail`, or `inconclusive` with evidence and does not edit the reviewed code. It identifies failed and unrun checks. The director settles unclear requirements and review disputes. For security, access, migrations, concurrency, or similarly high risk, add independent Sol review or use `astra_consultant` (`gpt-6-astra`, high) for a decision-changing question; Luna approval alone does not close those risks.

Set a finite review-round limit that allows the initial review and at most one Luna correction review by default. After those rounds are exhausted, diagnose the cause and change approach. The ledger permits a bounded Sol senior escalation (one by default), carrying the diff, reproduction, and prior attempts, with one added review round. Further work requires a separate director-created task. A reviewer `inconclusive` result blocks the task. The director may replan with a resolution and explicit goal, scope, or acceptance updates; the ledger records contract changes and rechecks scope conflicts on assignment. Prefer a follow-up task for substantially different work. Bound consultations and review cycles. Do not let agents spawn nested work without explicit director assignment.

Only the integrated, independently checked snapshot can complete a task or unlock its dependents. Keep one active writer per shared file. On interruption, preserve edits, inspect the current diff, confirm the earlier worker stopped, then safely resume or reassign.

For a persistent bug or design uncertainty, the director may ask two agents to investigate different hypotheses independently. State the question, budget, constraints, and stop condition. Favor evidence and discriminating checks over duplicate full implementations. Consult Astra only if advice can change the decision.

## State updates

`.codex/PROJECT_STATE.md` is compact project memory, not conversation history. Distinguish confirmed facts, hypotheses, and plans; record accepted changes and verification outcomes, including failed and unrun checks. Never store secrets or full logs. Ask `luna_state_editor` (`gpt-6-luna`, low) to make a narrow update from director instructions, then review the diff yourself.

The state hooks run at supported session events and may issue one Stop nudge. They do not schedule agents. The project-local `.codex/ORCHESTRATOR.json` ledger records backlog transitions. See [state policy](references/STATE_POLICY.md) for freshness and scope.

## Cost and completion

The role templates currently contain `service_tier = "standard"`; treat this as an unverified candidate config value. Do not infer that API response `default` is the equivalent TOML selector. Confirm the config and Standard dispatch in an isolated desktop pilot. If Standard is unavailable or unconfirmed, report the blocker; do not auto-select Fast or Ultrafast. Do not auto-select maximum reasoning. Pass only relevant context, combine small related work where it reduces handoffs, and avoid routine progress polling. The final report separates actual live model calls, tests run, and behavior that remains unverified. Do not claim percentage savings without measurements.
