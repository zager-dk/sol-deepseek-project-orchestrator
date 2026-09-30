# DeepSeek Delegation Contract Template

Use one contract per worker stream.

```text
TASK ID
<stable short id>

ROLE
implementer | investigator | reviewer | integrator

GOAL
<one observable outcome>

WHY
<user/product intent if relevant>

WORKSPACE
<absolute writable repo/worktree path, branch, and exact baseline SHA>

OWNERSHIP
- files/modules this worker may change

NO-TOUCH PATHS
- files/modules owned by other workers or shared surfaces that must remain unchanged

DEPENDENCIES
- none for true parallel dispatch, or list prerequisite already satisfied

SCOPE
- ...

NON-GOALS
- ...

CONSTRAINTS / CONTRACTS
- ...

ACCEPTANCE CRITERIA
- ...

KNOWN RELEVANT PATHS
- ...

LOCAL_COMMIT
no | yes (only for explicitly isolated worktree mode)

VERIFICATION
- run the relevant tests/build/lint/typecheck
- diagnose and fix ordinary in-scope failures before reporting

RETURN FORMAT
- STATUS: ready_for_review | blocked | failed
- TASK ID + workspace
- SUMMARY
- CHANGED: paths + behavior
- LOCAL COMMIT SHA: only when requested
- VERIFICATION: command + outcome
- RISKS/BLOCKERS
- ROOT/USER DECISIONS
```

## Dispatch rules

- No progress polling.
- The worker owns repository discovery, implementation, testing, debugging, and routine verification inside the assigned scope.
- The worker is not alone in the codebase. Name the other streams and their
  ownership; do not revert others' work. Respect ownership/no-touch boundaries.
- Children do not invoke the orchestration skill or delegate further.
- Legacy single-worker briefs remain valid: use the current workspace, one
  writer, and no commit permission when the new metadata is absent.
- Workers must not modify `.codex/PROJECT_STATE.md`.
- Local commits are allowed only when `LOCAL_COMMIT: yes` is explicit and the worker is in an isolated workspace.
- A local commit never authorizes push/publish/deploy.
- Under-specification is a blocker, not permission to redesign adjacent systems.

## Integrator contract

For multiple writers, stop/close completed children, then use one
`deepseek_integrator` contract (legacy `deepseek_worker` ROLE=integrator works):

```text
ROLE
integrator

GOAL
Combine the completed worker streams into one integration workspace and verify the combined behavior.

WORKSPACE / BASELINE / LOCAL_COMMIT
- integration worktree, branch, exact baseline SHA
- LOCAL_COMMIT: no unless explicitly authorized

OWNERSHIP / NO-TOUCH PATHS
- exact integration write scope; .codex/PROJECT_STATE.md is always no-touch

INPUTS (exact SHAs or complete patches, application order)
- task A workspace/commit
- task B workspace/commit
- optional task C workspace/commit

GLOBAL ACCEPTANCE CRITERIA
- ...

INTEGRATION AUTHORITY
- may apply/cherry-pick local worker commits or patches
- may resolve routine merge conflicts that preserve the established contracts
- may run integration tests and fix ordinary integration-only failures
- must escalate product/architecture ambiguity to Sol

PROHIBITED
- no push/publish/deploy
- no credentials/secrets changes
- no PROJECT_STATE changes

RETURN FORMAT
- STATUS
- INTEGRATED SUMMARY
- CHANGED PATHS
- CONFLICTS RESOLVED
- CONFLICTS/DECISIONS REQUIRING SOL
- VERIFICATION
- RISKS
```
