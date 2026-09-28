# Architecture: The Thin-Root Orchestration Workflow

This document describes the whole working model in one place: who does what, in
what order, and where the model is allowed to spend effort. It is written to be
read by two audiences at once:

- a person deciding whether this workflow fits their project;
- a language model that has just been handed the repository and needs the rules
  without reconstructing them from chat history.

If you only read one section, read [Responsibilities](#responsibilities) and
[The dispatch sequence](#the-dispatch-sequence).

---

## The problem this solves

A single strong model doing everything in one context has three costs:

1. **Context pressure.** Exploration notes, test logs, stack traces, and file
   dumps accumulate. Long sessions degrade, and compaction throws away detail
   that later turns needed.
2. **Cost per unit of work.** A frontier model writing boilerplate and re-running
   a test suite burns expensive tokens on mechanical work.
3. **Verification weakness.** A model that wrote the code and then reviewed its
   own work tends to confirm its own assumptions.

The thin-root workflow addresses all three by splitting one job into two roles
and making the boundary between them explicit.

## The shape of it

```text
user (direction, product judgement, approvals)
        |
        v
ROOT MODEL  (preferred: GPT-5.6 Sol at high reasoning)
            technical lead, orchestrator, integrator
        |            one scope pass -> one dispatch -> one wait
        |            -> one batched review -> at most one correction
        v
WORKER MODEL (DeepSeek V4.1 Flash: implementation, tests, debugging)
        |
        v
repository:  code  +  .codex/PROJECT_STATE.md  (durable memory)
```

Two roles, one repository, one durable state file. The chat is temporary; the
repository is not.

## Responsibilities

### The user

- Owns the product vision, priorities, and taste.
- Approves anything irreversible, external, or expensive.
- Does **not** manage agent logistics. Which agent runs which step, how many
  correction cycles happened, and what the verification command was are the
  root's job to handle.

### The root model

**Preferred root: GPT-5.6 Sol at high reasoning.** That pairing is the intended
shape of this workflow, and it is what the bundled skill assumes when it talks
about a thin root: a strong, expensive model doing scope, contracts, judgement,
and acceptance, and nothing mechanical.

The preference is a default, not a lock. If you select a different root model,
the workflow still applies, because the boundary is defined by responsibilities
rather than by a model name. What does not change is the worker side: the
implementation worker is DeepSeek V4.1 Flash, dispatched through an explicit
route. If routing to that worker is unavailable, report it instead of silently
substituting another paid model.

The root is a technical lead who delegates the build and keeps the review. In
one substantial task the root normally does exactly this:

1. **Scope and contract pass.** Read the existing durable state, inspect only
   enough of the repository to fix the goal, scope, non-goals, stable
   interfaces, acceptance criteria, and high-risk constraints. Deliberately do
   not read the whole tree.
2. **One coherent dispatch.** Write a single worker brief covering the whole
   bundle, including the verification the worker must run.
3. **One wait.** Wait for the completion report. No polling, no progress
   requests, no interrupting a healthy run.
4. **One batched acceptance review.** Judge the finished diff and the evidence,
   under two lenses at once: specification compliance, and quality (security,
   regressions, architecture, maintainability) proportional to the change.
5. **At most one batched correction.** If the review found problems, send every
   concrete finding in a single request. Do not drip-feed.
6. **One final response**, plus the durable state update.

The root keeps architecture decisions, security judgement, public contracts,
and integration. It does not rewrite the worker's code line by line unless the
review demands it.

### The worker model

- Owns repository discovery inside the assigned scope.
- Implements the bundle end to end, writes or updates tests, runs the named
  checks, diagnoses failures, and iterates inside scope before reporting.
- Reports once: status, summary, changed paths, verification commands with real
  exit status, unresolved risks, and decisions that genuinely need the root.
- Does not spawn nested agents, commit, push, deploy, or widen scope.
- Reports a missing contract as a blocker instead of inventing one.

The worker is not a smaller version of the root. It is a different job: bounded
execution against a contract that someone else already established.

## The dispatch sequence

```text
scope pass
   |
   +--> dispatch (one brief, one bundle, one wait)
           |
           +--> worker: discover -> implement -> test -> fix -> report
                   |
                   +--> review (one batch, two lenses)
                           |
                           +--> accept  -> update PROJECT_STATE -> final answer
                           |
                           +--> correct (one batch of findings)
                                   |
                                   +--> re-review the delta only
                                           |
                                           +--> accept, or escalate the
                                                genuine blocker to the user
```

The counters matter. Six steps, not one per file. One correction cycle, not an
unbounded repair loop. If the same problem survives one focused correction, the
faithful move is to diagnose at the root and escalate, not to keep re-dispatching
the same failing approach.

## The worker brief

The brief is the contract. It is the single most important artifact in the
workflow, because it is the only thing the worker is accountable to. A brief
that is vague produces work the root then has to redo.

```text
GOAL
    one outcome, stated as something observable

WHY
    user or product intent, when it changes what "good" means

SCOPE
    the work that is inside this bundle

NON-GOALS
    adjacent work that must not be touched

CONSTRAINTS / CONTRACTS
    interfaces, shapes, invariants, and safety rules that must survive

ACCEPTANCE CRITERIA
    how the root will decide the bundle is done

KNOWN RELEVANT PATHS
    only when it saves the worker real time

VERIFICATION
    the commands to run, and the instruction to fix ordinary failures first

RETURN FORMAT
    STATUS / SUMMARY / CHANGED / VERIFICATION / RISKS / DECISIONS
```

Three rules for writing it:

- **One bundle.** A bundle is a coherent unit of work: a feature, a migration, a
  cross-component bug fix, a refactor. Not "add the type", "then add the test",
  "then run it".
- **Acceptance criteria are checkable.** "Works well" is not a criterion.
  "Unauthenticated requests still return 401" is.
- **Non-goals are explicit.** Most scope creep is not malice; it is a worker
  solving an adjacent problem nobody asked about.

See `skill/references/DELEGATION_CONTRACT.md` for the copy-paste template and a
filled example.

## Review and correction rules

**One batch, two lenses.** Review the diff once and answer both questions
simultaneously:

1. *Did it meet the contract?* Every acceptance criterion, checked against
   evidence rather than against confidence.
2. *Is it good work?* Correctness, regressions, security, architecture,
   maintainability, proportional to the blast radius. A one-file change needs a
   proportional look, not an audit.

**Do not rerun the whole suite by reflex.** Rerun a focused check when the
evidence is missing, the result is suspicious, or the change is high-risk
(auth, money, migrations, shared infrastructure, secrets, destructive
operations). Otherwise accept the worker's reported commands, and spend the
root's attention on judgement.

**One correction request.** Collect every finding, then send them together with
the same return format. A second round of tiny corrections is usually a symptom
of a bad first brief or a bad first review.

**A green exit code is not acceptance.** Zero means a command finished. Look at
what it proved. "Tests pass" on a suite that never touched the changed path is
not evidence.

## Persistent project state

`.codex/PROJECT_STATE.md` is the durable working memory. It is **state, not
history**.

### Lifecycle

1. The installer writes the template once and never overwrites an existing file.
2. The `SessionStart` hook injects it on startup, resume, clear, and after
   compaction, so a new chat begins already oriented.
3. The root updates it before ending a turn, when accepted work changed
   something durable.
4. The `Stop` hook is a safety net: if git reports repository changes and the
   state file is older than the changes, it asks for one extra state pass. It
   fires at most once per turn and never writes anything itself.

### What belongs in it

- project intent, in one paragraph;
- the current milestone and its status;
- durable architecture facts and public contracts;
- decisions and non-goals, with a short reason when the reason prevents a
  future reversal;
- active work not yet integrated;
- known risks that still matter;
- the verification baseline (the commands that define "healthy");
- the next few concrete steps;
- a short metadata line.

### What does not

- command output, logs, stack traces, or diffs;
- transient debugging hypotheses;
- failed attempts that no longer matter;
- a chronological diary of what happened;
- worker play-by-play.

Update in place. Delete stale bullets. Keep it under about 10 KB; the hook warns
past 14 KB. If the file grows into a journal, it stops being memory and becomes
another context problem.

The root owns the file. A worker may touch it only when the brief says so
explicitly.

## Small-task exception

Orchestration is overhead, and overhead has a floor. For trivial, clearly local
work the root should just do it:

- formatting and lint fixes;
- a one-line obvious bug fix;
- a small text or copy change;
- a simple configuration edit;
- a question about code that needs no changes.

The test is not "how many tokens would this save" but "would repository
discovery, a brief, and a review cycle cost more than the change itself".

- If the answer is **yes, the overhead would exceed the change**: edit the file
  directly. Dispatching would cost more attention than the work is worth.
- If the answer is **no, the work merits delegation**: write the brief and
  dispatch one coherent bundle.

This exception is deliberate: a workflow that demands ceremony for a typo fix
gets abandoned before it helps with anything real.

## Routing and verification limits

Be honest about what this design can and cannot guarantee.

- **Routing is configuration, not magic.** The worker exists because a custom
  Codex subagent resolves to a DeepSeek route. If that route is missing or
  misconfigured, the correct action is to report the problem, not to substitute
  another paid model silently.
- **Model identifiers are environment-specific.** Slugs such as
  `deepseek/deepseek-v4.1-flash` come from a router catalog. Confirm the exact
  slug against your own picker before relying on it.
- **The root cannot see provider billing.** It sees a completion report, not
  which upstream provider served the tokens. Cost measurements come from the
  provider's own counters.
- **A report is a claim.** "Verification: `npm test` exit 0, 41 passed" is
  evidence of a command, not proof of correctness. Accept on inspectable
  evidence.
- **Hooks are guardrails, not enforcement.** Hook coverage can change between
  releases, project hooks load only after the project `.codex` layer is trusted,
  and a hook is running as a normal local process with your permissions.

See `skill/references/ROUTING.md` for the routing decision tree.

## Failure handling

| Failure | Response |
| --- | --- |
| Worker route unavailable | Report it. Do not silently fall back to another paid model. Ask the user whether to proceed with the root doing the work directly, or fix the route and dispatch once. |
| Worker returns `blocked` | Read the blocker. If it is a missing contract, answer it and re-dispatch once with the missing piece supplied. If it is a genuine external blocker, tell the user. |
| Worker returns `failed` | Treat as new information, not as a prompt to retry the same thing. Diagnose, then either re-dispatch with a corrected brief or take the work over. |
| Review finds problems | One batched correction request. After one focused correction, if the same problem remains, fix it at the root or escalate. |
| Acceptance criteria turn out to be wrong | Stop and re-scope with the user. Do not silently redefine done to match what was built. |
| State file is stale or bloated | Rewrite it in place. A bloated state file is a bug in the workflow, not a fact about the project. |
| Hooks misbehave | Set `SOL_DEEPSEEK_DISABLE_STATE_HOOK=1`, or remove the entry from `.codex/hooks.json`. Hooks must never be able to trap a turn. |
| Repeated failure of the same approach | Stop. Report the evidence and the blocker. Trying the same thing again with more optimism is not a strategy. |

## Worked example

A concrete pass through the whole workflow, with a small feature.

**User request:** "Add CSV export to the report page."

**1. Scope pass (root).** Read `PROJECT_STATE.md`: the project is an internal
reporting tool, the current milestone is "support team self-service", and the
verification baseline is `npm test` plus `npm run lint` in `apps/web`. Inspect
two files to find the report route and page component. Establish the contract.

**2. Dispatch (root).** One brief:

```text
GOAL
Add CSV export to the report page.

WHY
Support currently copies numbers out of the table by hand.

SCOPE
- a route that streams the current report as CSV
- a download control on the report page
- tests for the route's happy path and its 401 path

NON-GOALS
- no other export formats
- no changes to the report query
- no styling beyond the single control

CONSTRAINTS / CONTRACTS
- the existing report JSON shape must not change
- reuse the existing auth middleware

ACCEPTANCE CRITERIA
- GET /reports/:id/export.csv returns text/csv, a header row, and one row per record
- unauthenticated requests still return 401
- the control downloads with the current filter applied

KNOWN RELEVANT PATHS
- apps/web/src/reports/routes.ts
- apps/web/src/reports/ReportPage.tsx

VERIFICATION
- npm test and npm run lint in apps/web; fix ordinary in-scope failures first

RETURN FORMAT
- STATUS / SUMMARY / CHANGED / VERIFICATION / RISKS / DECISIONS
```

**3. Worker run.** The worker reads the routes, finds an existing streaming
helper it was not told about, uses it, adds three tests, hits one failure in the
filtered-export case, fixes it, and reports `ready_for_review` with the commands
it ran.

**4. Review (root, one batch).** The diff matches the contract. Two findings:
the CSV writer does not escape embedded quotes, and the new route is missing
from the route-level auth test list. Both are real; both are in scope.

**5. One correction dispatch.** Both findings, one message, same return format.
The worker fixes both, adds the escaping test, and reports again.

**6. Acceptance and state.** The root re-reviews only the delta, accepts, and
updates `PROJECT_STATE.md`: the CSV export moves into "accepted, pending
release", a note records that report exports now share the streaming helper,
and "notify support about the new download" becomes a next step.

Total: one scope pass, one dispatch, one wait, one review, one correction, one
state update. That is the whole workflow.

## Adoption notes

- Start with one project, not every project.
- Keep the first brief modest. The workflow is easier to trust after one clean
  end-to-end pass.
- If the worker's reports are consistently thin, the brief is the problem.
- If the root is consistently rewriting worker code, the bundle was too small or
  the brief too vague.
- If the state file grows past a screen or two, someone is writing history
  instead of state.

## Related documents

- `README.md` - what this repository is and how to install it.
- `INSTALL.md` - installation details, flags, and what is written where.
- `QUICKSTART.md` - first dispatch, step by step.
- `SECURITY.md` - secrets, trust, and hook safety.
- `TROUBLESHOOTING.md` - symptoms and fixes.
- `skill/SKILL.md` - the operational instructions the root model loads.
- `skill/references/` - delegation contract, state policy, routing notes.
