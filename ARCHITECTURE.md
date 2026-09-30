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

The thin-root workflow addresses all three by splitting one job into bounded execution and root judgement
and making the boundary between them explicit.

## The shape of it

```text
User: product intent and permissions
         ↓
GPT-6.1 Sol: scope + contracts + adaptive choice
         ↓
  SINGLE                 PARALLEL-2 / PARALLEL-3
  one Flash worker       2–3 Flash workers in separate worktrees
         ↓                        ↓ (all complete and stopped)
  completion report      one Flash integrator in a separate worktree
         ↓                        ↓
         └──────── combined result / verification ────────┘
                                  ↓
                  one Sol acceptance review
                  at most one correction phase
                  root-owned PROJECT_STATE update
```

One writer remains the default. The integrator runs after the writers finish,
so there are at most three active DeepSeek children at once. Release finished
child slots before starting the integrator. Wait APIs may return on one child
or time out; continue waiting for outstanding children, without progress polls.

## Responsibilities

### The user

The user owns product direction and authorizes spending, publication, and
destructive actions. Already supplied authorization persists; do not ask again
for the same action. The root handles agent logistics and routine technical
choices. An explicit request for no delegation wins over this workflow.

### The root model

Preferred root: **GPT-6.1 Sol, high reasoning, Standard speed**. GPT-5.6 Sol
and user-selected capable roots remain supported. The installer never switches
the root model or escalates reasoning/speed. Confirm available settings in your
installed client; these are starting preferences, not measured performance claims.

The root owns scope, interfaces, architecture, security decisions, final
acceptance, and semantic updates to `.codex/PROJECT_STATE.md`. It reads compact
state and enough repository context to establish a contract, then lets workers
own in-scope discovery, implementation, testing, and debugging. It does not
repeat that loop or separately review every worker by default.

### Implementation workers

Each DeepSeek V4.1 Flash worker gets a coherent outcome and explicit ownership.
It investigates, implements, verifies, fixes ordinary failures, and returns
`ready_for_review`, `blocked`, or `failed`, with paths and real command results.
It is not alone in the codebase: it must respect the other streams and must not
revert their changes. No nested agents, orchestration skill, unapproved commits,
remote writes, credentials changes, or persistent-state edits.

### The DeepSeek integrator

For multiple code-producing workers, one `deepseek_integrator` combines exact
local SHAs or complete patches in the designated integration worktree. Its brief
authorizes application and names allowed integration edits. It checks baseline,
ownership, missing inputs, and forbidden state changes before applying them.
Then it resolves routine conflicts under the frozen contracts, runs combined
verification, and returns one report. It escalates architecture, product, and
security ambiguity. It cannot approve the result or change persistent state.

Single-worker tasks skip this pass. Legacy installs may use `deepseek_worker`
with `ROLE=integrator` under the same contract; the optional separate role makes
the integration responsibility easier to discover and bound.

## Adaptive parallelism

| Choice | Worker count | Decision |
| --- | ---: | --- |
| DIRECT | 0 | The edit is cheaper than delegation overhead |
| SINGLE | 1 | Default substantial task; shared mutable surfaces or uncertain interfaces |
| PARALLEL-2 | 2 | Two streams can start now and have disjoint write ownership |
| PARALLEL-3 | 3 | Three independent streams, isolation, and enough expected time benefit |

The root records its choice and a short reason in the dispatch. Available slots
are not a reason to parallelize. Independence requires stable interfaces, no
start dependency between streams, separate acceptance criteria, and one bounded
integration pass. Shared migrations, lockfiles, schemas, generated files, and
central configuration must have one owner. Finish a shared prerequisite first
or keep a single writer. Worktree separation prevents file races; it does not
make dependent changes logically independent.

Use distinct branches/worktrees for concurrent writers. If the client cannot
dispatch a worker into the named writable workspace, keep one writer; do not
loosen permissions. Read-only helpers must also have bounded ownership and stay
within the same three-child cap. See `references/PARALLELISM_POLICY.md` in the
installed skill and `skill/references/PARALLELISM_POLICY.md` in this repository.

## The dispatch sequence

1. **Scope once.** Read durable state. Freeze shared contracts, acceptance,
   risk constraints, and non-goals. Choose DIRECT, SINGLE, PARALLEL-2, or PARALLEL-3.
2. **Prepare and dispatch.** For parallel writers, establish a clean committed
   baseline, isolated paths/branches, ownership and no-touch paths, verification,
   and transfer protocol. Dispatch 1–3 coherent briefs in one phase.
3. **Wait for all.** Collect completion reports; stop/close finished children
   with the client-supported lifecycle API. Preserve outputs of failed streams.
   Do not interrupt healthy work or silently accept an incomplete subset.
4. **Integrate once when needed.** Dispatch one DeepSeek integrator after all
   writers stop. Supply exact inputs, global acceptance criteria, and combined
   checks. A missing or blocked stream makes the global bundle incomplete.
5. **Review once.** Sol reviews the consolidated diff and evidence for both
   specification compliance and quality/security proportional to the risk.
6. **Correct at most once.** Batch every concrete finding. Prefer one correction
   writer in the integration workspace. If corrections need isolated streams,
   integrate their deltas within the same correction phase before re-reviewing.
7. **Accept and persist.** Review the correction delta if any, then update
   root-owned state and report outcome/limitations. Commits, push, PR, and deploy
   remain governed by the user's authorization; acceptance alone is not permission.

One integration pass refers to the initial bundle. Necessary reintegration of
the single correction is part of that correction, not a fresh orchestration loop.
If a material blocker survives correction, diagnose it and return the concrete
decision or fix at the root. Do not restart an unbounded worker loop.

## Worktree and transfer protocol

Every writer and the integrator start at the same full commit SHA. Local Git
worktrees share object storage but have separate files and indexes. They provide
write isolation, not a security sandbox. Credentials, network permissions, and
provider data sharing still need their usual controls.

Prefer managed Codex worktrees when your client exposes a supported way to
dispatch into them. The installed `scripts/prepare_worktrees.py` is an offline
fallback: preflight, 1–3 worker branches, an integrator branch for parallel tasks,
and a local manifest. It refuses dirty/unborn roots, nested paths, branch/task
collisions, and submodule projects. It never commits, merges, publishes, stashes,
copies uncommitted files, or deletes worktrees. Partial failures are retained.

The root verifies the output paths are writable in the current session and puts
them in each brief. Ignored local files and uncommitted project state are not
copied into worktrees. Supply a sanitized state/contract snapshot to each child.
Never copy secret files into task workspaces to make setup easier.

For transfer, explicitly grant `LOCAL_COMMIT: yes` only inside an isolated task
branch, if compatible with user/repository policy. A worker stages only named
owned files and returns its exact SHA. Without that permission, use a complete
reviewed patch including new/deleted/binary files, or stay with one writer.
`git diff` alone omits untracked files and is not a complete transfer artifact.
The integrator receives these exact inputs and can use `cherry-pick --no-commit`
to produce a combined staged diff without committing. Root approval remains
required before acceptance. See the full
[worktree protocol](skill/references/WORKTREE_PROTOCOL.md) for commands and cleanup.

## The worker brief

Use `skill/references/DELEGATION_CONTRACT.md`: TASK ID, ROLE, GOAL, WHY,
WORKSPACE + branch + baseline, OWNERSHIP, NO-TOUCH PATHS, DEPENDENCIES, SCOPE,
NON-GOALS, CONTRACTS, ACCEPTANCE, LOCAL_COMMIT, VERIFICATION, RETURN FORMAT.
Every parallel worker must be told that other workers exist and what they own.
Old single-worker GOAL/SCOPE/VERIFICATION briefs remain valid; fill missing
metadata from the actual workspace and keep one writer with no commit authority.

A good brief names observable acceptance conditions and one coherent outcome.
The worker may discover relevant files inside scope, but must ask the root about
an ownership expansion. Integrator briefs additionally name exact source SHAs
or patches, ordering, allowed integration edits, and global verification.

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

The root owns the file. Workers and integrators return state-relevant facts
in their reports; only the root makes semantic state updates after acceptance.

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
