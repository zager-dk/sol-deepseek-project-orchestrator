# Parallel delegation example

This is a fictional project with two publishing adapters and an existing queue.
Replace paths/checks with real equivalents. Goal: scheduled publishing for both
adapters while preserving the existing queue contract. Sol chooses PARALLEL-2
because the adapter files/tests are disjoint and both can start against a frozen
interface. If both need queue changes, finish that prerequisite or use one writer.

## Shared contract (given to both workers)

```text
BASELINE: <same full committed SHA from root preflight>
GOAL: handle the existing scheduled-job input in both adapters
CONTRACTS:
- preserve src/queue/** shapes and retry behavior
- preserve auth/config behavior; no dependency or lockfile changes
- .codex/PROJECT_STATE.md is root-owned and always no-touch
GLOBAL ACCEPTANCE:
- both adapters consume the scheduled-job shape
- existing immediate-send and queue regression tests pass
VERIFICATION: existing adapter suites/lint; fix ordinary in-scope failures
LOCAL_COMMIT: yes, explicitly authorized local-only on the named isolated branch
- stage only named owned paths; inspect staged diff before commit
- no remote writes or unrelated staging
RETURN: STATUS (ready_for_review | blocked | failed), TASK ID, workspace,
        baseline, full local SHA, SUMMARY, CHANGED, real checks/exits, RISKS
```

## Worker A: deepseek_worker

```text
TASK ID: telegram-scheduled-publish
ROLE: implementer
WORKSPACE: <allowed-workspaces>/scheduled-publish/worker-1
BRANCH: sdo/scheduled-publish/worker-1
OWNERSHIP: src/providers/telegram/**, tests/providers/telegram/**
NO-TOUCH: src/providers/vk/**, src/queue/**, lockfiles, .codex/PROJECT_STATE.md
DEPENDENCIES: none; queue contract frozen
ACCEPTANCE: Telegram handles scheduled-job input; immediate sends unchanged
OTHER WORKERS: B owns VK. You are not alone; do not revert others' work.
```

## Worker B: deepseek_worker

```text
TASK ID: vk-scheduled-publish
ROLE: implementer
WORKSPACE: <allowed-workspaces>/scheduled-publish/worker-2
BRANCH: sdo/scheduled-publish/worker-2
OWNERSHIP: src/providers/vk/**, tests/providers/vk/**
NO-TOUCH: src/providers/telegram/**, src/queue/**, lockfiles, .codex/PROJECT_STATE.md
DEPENDENCIES: none; queue contract frozen
ACCEPTANCE: VK handles scheduled-job input; immediate sends unchanged
OTHER WORKERS: A owns Telegram. You are not alone; do not revert others' work.
```

Sol dispatches both with the shared contract, waits for all reports, and stops/
closes completed children. Neither worker invokes the orchestration skill or
spawns children. If local commits are prohibited, use complete reviewed patches
or one writer. Separate worktrees do not remove a logical dependency.

## One DeepSeek integration contract

```text
TASK ID: scheduled-publish-integration
ROLE: integrator (deepseek_integrator; legacy worker role is supported)
WORKSPACE: <allowed-workspaces>/scheduled-publish/integrator
BRANCH: sdo/scheduled-publish/integrator
BASELINE: <same exact SHA>
INPUTS: <exact A SHA>, then <exact B SHA>
OWNERSHIP: the two adapter/test trees and named integration-test fixtures
NO-TOUCH: queue contracts, lockfiles, .codex/PROJECT_STATE.md, credentials
INTEGRATION AUTHORITY:
- inspect exact inputs/ownership; reject unexpected paths/state changes
- apply local commits with cherry-pick --no-commit
- resolve routine conflicts preserving frozen contracts
- run both adapter suites, queue regressions, combined scheduling checks
- fix integration-only failures inside the allowed scope
LOCAL_COMMIT: no
GLOBAL ACCEPTANCE: both adapters work together; immediate/queue behavior unchanged
RETURN: status, inputs/baseline, consolidated diff/paths, resolved conflicts,
        real checks/exits, unresolved risks/decisions
```

Sol reviews one consolidated diff for specification and quality/security. Any
findings go in one correction request. The budget covers the whole bundle,
including needed reintegration. Only Sol accepts and updates canonical state.
A blocked stream cannot be omitted from global acceptance. Publication still
requires the user's authorization. See the worktree protocol for setup/retention.
