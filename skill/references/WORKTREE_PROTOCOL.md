# Worktree Isolation and Local Integration

For two or three concurrent writers, use separate worktrees at one baseline.
Single-worker tasks can keep the current workspace and v0.1 no-commit behavior.
Worktrees isolate files and indexes, share Git objects/configuration, and are
not security sandboxes.

## Root preflight

1. Freeze contracts and disjoint ownership. Shared migrations, schemas,
   lockfiles, and generated artifacts have one owner. Finish prerequisites first.
2. Identify a clean committed baseline with `git rev-parse HEAD` and
   `git status --porcelain`. No automatic stash/reset or copying dirty files.
   Never commit unrelated user work to enable parallelism. Use one writer if
   a clean baseline cannot be established under existing authorization.
3. Prefer managed Codex worktrees when the client can dispatch into them.
   Otherwise use the offline helper below. Confirm every path is writable in
   the current session and that each child can execute there. Paths in a brief
   do not grant permission. If isolated dispatch is unavailable, use one writer.
4. Pass sanitized state/contract snapshots in briefs. Untracked/ignored files,
   local hooks, dependencies, and secrets are not copied into worktrees.
   Dependency setup must obey user network/spending rules.

## Offline preparation

From this repository (or use the same script in the installed skill):

```bash
python skill/scripts/prepare_worktrees.py --project /path/to/project --workspace-root /path/to/allowed-writable-workspaces --task export-adapters --workers 2 --dry-run
python skill/scripts/prepare_worktrees.py --project /path/to/project --workspace-root /path/to/allowed-writable-workspaces --task export-adapters --workers 2
```

PowerShell, with generic paths:

```powershell
python skill\scripts\prepare_worktrees.py --project C:\code\project --workspace-root C:\code\task-workspaces --task export-adapters --workers 2 --dry-run
```

`--workers` defaults to 1 and accepts 1–3. For multiple workers an additional
integrator workspace starts at the same SHA:

```text
task-workspaces/export-adapters/
    manifest.json
    worker-1/      branch sdo/export-adapters/worker-1
    worker-2/      branch sdo/export-adapters/worker-2
    integrator/    branch sdo/export-adapters/integrator
```

The helper requires the project root, valid lowercase task ID, and a clean
existing commit. It rejects existing task paths/branches, nested project or Git
metadata targets, and submodule projects. It never invokes models, changes
routing/permissions, starts paid requests, commits, merges, stashes, copies dirty
files, or deletes worktrees. Exit 0 means prepared or valid dry-run; 2 means
rejected/failed. Partial failures retain workspaces and record the error and
completed entries in the manifest. Inspect them before choosing a fresh ID.
Keep the manifest local: it contains machine paths.

## Writer transfer

Every brief names TASK ID, WORKSPACE, branch, exact BASELINE SHA, OWNERSHIP,
NO-TOUCH paths, frozen contracts, acceptance, and checks. Tell workers they are
not alone and what the other streams own; they must not revert others' work.
`.codex/PROJECT_STATE.md` is always no-touch.

- **Local commit:** grant `LOCAL_COMMIT: yes` only in an isolated task branch
  under existing user/repository authorization. Stage named owned files,
  inspect the staged diff, commit locally, and return the full SHA. No broad
  `git add .` over unrelated files. Local commit authority never grants push.
- **Complete patch:** without commit authority, return a reviewed artifact
  including additions, deletions, binary files, and mode changes. A plain
  `git diff` omits untracked additions. Inspect the complete artifact/baseline
  before application. If safe transfer is unavailable, use one writer.

Return actual checks/results, baseline/input artifact, and risks. Completion
(`ready_for_review`) is not acceptance. Wait for all children, then stop/close
finished children with the supported API before integration. Preserve failures.

## One DeepSeek integration pass

Dispatch `deepseek_integrator` after all writers finish. Legacy `deepseek_worker`
with ROLE=integrator is supported. Its worktree must be clean, at the baseline,
and have no other writer. Give exact input SHAs/patches and order, allowed
integration edits, global acceptance, and combined checks. Missing/blocked
streams remain visible; do not call a partial bundle complete.

Inspect each input against its baseline (replace placeholders with full SHAs):

```bash
git diff --name-status BASELINE_SHA WORKER_SHA
git diff BASELINE_SHA WORKER_SHA -- .codex/PROJECT_STATE.md
```

Reject out-of-scope paths and state changes. With explicit integration authority,
in the integration worktree:

```bash
git cherry-pick --no-commit WORKER_A_SHA WORKER_B_SHA
git diff --cached --stat
```

Run the combined checks from the brief. No automatic integration commit is
needed. Resolve routine conflicts under frozen contracts; architecture/product/
security ambiguity goes to Sol. Never reset unrelated work or weaken checks.
Sol reviews the consolidated diff/evidence once, then uses at most one combined
correction phase, including needed reintegration of corrected deltas. Only Sol
accepts and updates canonical state. Transfer to the target branch must follow
its rules and preserve unrelated work; the helper does not perform that transfer.

## Retention and cleanup

After acceptance and authorized target-branch transfer, inspect `git worktree
list` and `git -C <exact-worktree-path> status --porcelain`. Use managed archive
for managed worktrees. For helper worktrees, use `git worktree remove
<exact-worktree-path>` only after preserving needed changes. Do not force removal
of dirty worktrees or automatically delete branches; commits may be the only copy
of a failed stream. Installer/uninstaller never remove task workspaces/branches.
