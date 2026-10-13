# Delegation and acceptance contract

Use this contract for each backlog item. The director writes the acceptance terms before implementation. Each ready task has an ID, goal, dependencies, priority, risk, change scope, acceptance criteria, owner, and status. The local ledger records transitions; it does not launch the agent.

## Short messages and reused evidence

Use the user's language for briefs, corrections, and updates, with normal spaces between words and numbers. Preserve exact code identifiers. Lead with the concrete task and a testable done criterion; include only the scope, constraints, and evidence needed to act. Reference the task contract rather than resending it on every handoff. For example: “Fix <reproduction> in <scope>. Done when <observable check> passes. Return the diff, result, and any blocker.”

Batch review findings and reuse verified evidence for the same snapshot/environment. Repeat a check only when relevant files, data, configuration, or assumptions changed, a check failed, or evidence is missing. Avoid duplicate approvals for already authorized actions; retain independent acceptance for significant changes and explicit user approvals required by the visual workflow.

## Implementation brief

```text
TASK ID
<stable identifier>

GOAL
<observable result>

DEPENDENCIES
<IDs already integrated and verified, or none>

PRIORITY / RISK
<number or agreed priority label> / low | medium | high | critical

SCOPE
<files, components, or exclusive resources this owner may change>

CONTRACTS AND CONSTRAINTS
<interfaces, invariants, safety boundaries>

ACCEPTANCE CRITERIA
<observable pass/fail conditions, including expected error cases>

CONTEXT
<relevant state facts, reproduction, and prior attempts only>

VERIFICATION
<commands and expected evidence; report failures and unrun checks distinctly>

RETURN
- status and summary
- changed paths
- exact commands and outcomes
- unresolved risks/blockers
- decisions needed from the director
```

Give one task to one owner. Include only the context needed to complete it. Keep shared files, APIs, schemas, migrations, and test environments under one active writer or serialize conflicting assignments. An agent must not weaken acceptance criteria or tests to make its result pass. It must not commit, push, deploy, widen scope, or spawn nested work unless the director explicitly assigns such a step.

## Independent reviewer brief

For significant work, prepare review scenarios from the original task before implementation. Give the reviewer the contract and relevant baseline behavior. After implementation, provide the exact diff and integrated snapshot. The reviewer checks surrounding code and observable behavior independently; an author's report is a lead, not proof.

```text
TASK ID AND ORIGINAL CONTRACT
<goal, scope, constraints, and acceptance criteria>

REVIEW SCENARIOS
<prewritten happy path, failures, edge cases, regressions, and risk-specific checks>

DIFF / SNAPSHOT
<exact integrated change to inspect>

EVIDENCE TO COLLECT
<commands, outputs or behavior that demonstrate each criterion>

RETURN EXACTLY
- RESULT: pass | fail | inconclusive
- EVIDENCE: observed behavior and commands with outcomes
- FAILED CHECKS: what failed
- UNRUN CHECKS: what was not executed
- FINDINGS: concrete defect and reproduction, or requirement/coverage uncertainty
- RISK: whether senior Sol review or Astra advice is warranted
```

The reviewer does not modify the reviewed code. A passing result must include a manual evidence record in the form `PASS; command=...; result=exit 0|passed; evidence=...`. The CLI records this claim; it does not execute the command or authenticate the reviewer identity or model role. Actor IDs, role labels, freshness attestations, and stopped-owner declarations are bookkeeping only: they do not authenticate identity, prove fresh context, or terminate a process. A concrete reproducible defect returns to the implementation owner. A requirement ambiguity or inadequate test plan returns to the director. An inconclusive result blocks the task until the director records a resolution. The director can update goal, scope, or acceptance with `replan`; it records the prior and revised values with the reason, and assignment checks scope conflicts again. Prefer a separate task for substantially different work. An unrun command is not a pass. High-risk access control, security, migration, concurrency, or destructive behavior needs an independent senior Sol review or recorded Astra consultation with director resolution; Luna's pass alone is insufficient.

## Release contract (only for deployed work)

Link the project's versioned release/rollback procedure and target-environment evidence in the task. Check target paths/configuration, service identity and access, executable text/line endings, backup consistency under background writers, and switch/rollback prerequisites early. Use the same verified procedure on later steps; explain and revalidate any revision. No service stop is allowed before its preconditions pass. Read [Release workflow](RELEASE_WORKFLOW.md) for the conditional checklist. Local tasks that need no deployment omit this contract.

## Integration contract

A task is complete only when the director has integrated the result and checked the exact combined state against the contract. Record the verification command and whether it ran. Unlock dependents only after the prerequisite's integrated snapshot passes independent acceptance. Separate green worktrees do not prove their combined behavior.

## Visual contract extension

For `visual-design`, `ux-ui`, `storyboard`, or `motion-fx`, add the current spec revision, brief/audience/constraints, inspected reference links with take/avoid notes, proposed directions and exact palettes, required capabilities, promised editable/preview/report formats, and user approval sources to the brief. Bind the prototype and final artifact manifest to that revision. The Sol director still routes and accepts; Luna implements and independently reviews. These profiles add no roles and cannot use the low-risk `manual-control` review bypass.

Use [Visual workflow](VISUAL_WORKFLOW.md) for the schemas and four profile-specific acceptance checklists. Production requires explicit user approval of a direction/palette and then the rendered prototype. Review must open each current preview with an inspection tool, check the editable source, and record observed findings. UI adds interactions, responsive layouts, and accessibility; motion adds full-duration playback, timing, transitions, and continuity. A text `PASS`, filenames, or still frames for motion are insufficient. `visual-qa` supplements the existing review/integrate/complete gates; it does not replace them. Spec or direction changes require new version-bound evidence and approvals. The CLI records these claims but cannot inspect pixels, execute tools, or authenticate the user/reviewer.

## Recovery contract

When work is interrupted, keep all files and inspect the diff. Confirm the previous worker has stopped before reassigning. Record the prior owner and attempts, give the next owner the current diff, reproduction, remaining acceptance criteria, and failed checks, and ensure no two owners write the same shared file. Recovery preserves changes; it does not automatically mark the task complete or retry the same approach.

## Correction and escalation

Bundle concrete review findings into one bounded correction request. Set the ledger review limit to cover the initial review and one correction review. After those rounds are exhausted, the director diagnoses whether the cause is implementation complexity, a requirement problem, or the environment. A configured finite escalation allowance (one by default) may assign `sol_senior` with the diff, reproduction, and prior attempts; it adds one review round. Further work needs a separate follow-up task. Do not repeat an unchanged brief indefinitely.

## Competing hypotheses

For a persistent bug or architecture question, two agents may investigate distinct hypotheses independently. The director defines the question, budget, constraints, and stop condition. Ask for evidence and a discriminating check rather than two complete implementations. Astra is used only where its advice could change the decision. Any prototype is evaluated against shared acceptance criteria and integrated only after a reasoned selection.
