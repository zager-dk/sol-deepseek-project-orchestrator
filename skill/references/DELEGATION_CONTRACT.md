# Delegation and acceptance contract

Use this contract for each backlog item. The director writes the acceptance terms before implementation. Each ready task has an ID, goal, dependencies, priority, risk, change scope, acceptance criteria, owner, and status. The local ledger records transitions; it does not launch the agent.

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

## Integration contract

A task is complete only when the director has integrated the result and checked the exact combined state against the contract. Record the verification command and whether it ran. Unlock dependents only after the prerequisite's integrated snapshot passes independent acceptance. Separate green worktrees do not prove their combined behavior.

## Recovery contract

When work is interrupted, keep all files and inspect the diff. Confirm the previous worker has stopped before reassigning. Record the prior owner and attempts, give the next owner the current diff, reproduction, remaining acceptance criteria, and failed checks, and ensure no two owners write the same shared file. Recovery preserves changes; it does not automatically mark the task complete or retry the same approach.

## Correction and escalation

Bundle concrete review findings into one bounded correction request. Set the ledger review limit to cover the initial review and one correction review. After those rounds are exhausted, the director diagnoses whether the cause is implementation complexity, a requirement problem, or the environment. A configured finite escalation allowance (one by default) may assign `sol_senior` with the diff, reproduction, and prior attempts; it adds one review round. Further work needs a separate follow-up task. Do not repeat an unchanged brief indefinitely.

## Competing hypotheses

For a persistent bug or architecture question, two agents may investigate distinct hypotheses independently. The director defines the question, budget, constraints, and stop condition. Ask for evidence and a discriminating check rather than two complete implementations. Astra is used only where its advice could change the decision. Any prototype is evaluated against shared acceptance criteria and integrated only after a reasoned selection.
