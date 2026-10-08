# Troubleshooting

## The installer requests a Codex home

Pass `--codex-home PATH` explicitly or set `CODEX_HOME`. The installer does not infer a target. Check the dry-run plan before writing.

## The installer reports a conflict

A managed file differs from the bundled copy. The installer does not clobber an existing unowned file. Nothing is written over a differing managed file unless `--force` is supplied. Inspect the named file first. With `--force`, backups use `.bak`, then `.bak.1`, `.bak.2`, and so on without replacing older backups. Existing `PROJECT_STATE.md`, root `AGENTS.md`, and conflicting project `.codex/hooks.json` are preserved; the hook conflict blocks the install even with `--force`, so merge or remove it manually before retrying.

## An old managed file remains after upgrade

Use `--prune` only after reading the dry-run plan. It removes unchanged files whose exact paths and hashes are in the shared `.orchestrator-install-registry.json` and whose paths remain on the installer allowlist. Unknown files and unregistered paths stay in place; registry hashes alone do not grant ownership. If an existing `.codex/hooks.json` conflicts, `--force` cannot replace it; merge or remove that file manually, then retry.

## The installer verifier reports that TOML parsing is unavailable

`verify_install.py` requires Python 3.11+ for the standard-library `tomllib` parser. An older Python reports that the TOML parser is unavailable and does not validate configuration. Use an already available Python 3.11+ interpreter; Python 3.12.14 was available in this environment. This is a verifier requirement, not a requirement for the skill text, role files, installer, or runtime ledger.

## Role files are missing

Check that exactly the six child-role TOML files were copied under `<CODEX_HOME>/agents/` and the separate director profile is at `<CODEX_HOME>/orchestrator-director.config.toml`. The runtime is `<CODEX_HOME>/skills/sol-deepseek-project-orchestrator/scripts/orchestrate.py`. If child roles were intentionally omitted with installer `--no-agent`, run `verify_install.py --no-agent` too; otherwise missing roles are reported as errors. This verifier flag allows absent child files but still verifies every role file that exists, including files without installer ownership. If roles are needed, reinstall without installer `--no-agent` after reviewing the dry run. Restart Codex to reload custom agents. The `name` inside each child TOML is the dispatched role name. The director runs as the primary session. `--no-agent` skips the six child definitions, not the director.

## Native desktop pilot is blocked before child calls

The inspected delegated-task route exposes `spawn_agent` with a priority field only; it has no service-tier or role selector. In that route, the skill was read from disk rather than discovered through `skills.list`, and the six TOML roles have not been shown to load into dispatch. Treat the live Standard child-call pilot as blocked until a supported route can load and invoke those roles with Standard. This finding applies to the inspected route, not all Codex desktop chats. A parser accepting `standard`, `default`, or another string is only a syntax/config-load check, not semantic validation of service tier.

## Model unavailable or dispatch fails

Check model ID and effort against account/client availability. The templates currently contain `service_tier = "standard"`, but the official Codex TOML reference does not confirm that literal or `default` as the Standard selector. Verify template loading and Standard selection in an isolated desktop pilot; if Standard cannot be confirmed, report the blocker and do not silently choose Fast. The model catalog can change. Do not silently substitute another role. Record the failure and decide whether to wait, correct configuration, or stop. A local verifier cannot prove a live inference will succeed.

If an old configuration has `astra_flash_builder`, inspect its TOML: historical installs used that name for a DeepSeek route. It is not the new `astra_consultant` role.

## A task cannot be assigned

Run `list` or `snapshot --json` and inspect its state, dependencies, and current owner. Assignment requires an unowned ready item and completed dependencies. Resolve the predecessor through integrated review before assigning dependents. Keep a single writer per shared file or serialize conflicting work.

## Work was interrupted

Keep the current diff. Confirm that the prior agent has stopped, then use `interrupt` and `recover` with a concise handoff that includes existing changes, reproduction, failed attempts, and remaining criteria. Do not clean or overwrite the working directory during recovery.

## A review is inconclusive or finds a defect

`fail` with a reproducible defect returns it to the owner with the exact observation. Requirement ambiguity, inadequate test scope, or unclear risk goes to the director. Record unrun checks as unrun. The review-round limit should allow the initial review and one correction review. Once exhausted, use the finite `escalate` allowance with `--owner-role sol_senior`, a new owner identity, and the preserved diff, reproduction, and prior attempts, or create a follow-up task. Use `replan` only after the director resolves a blocked requirement; it can record explicit goal, scope, and acceptance updates with the reason, then checks scope conflicts on assignment. Do not repeat the same task indefinitely.

## A dependent task remains blocked

A worker's report or green isolated branch is not enough. Integrate the prerequisite and verify the combined snapshot, then mark it accepted. Only then will dependent work become ready.

## State appears stale

Compare the `state_fingerprint` marker in `.codex/PROJECT_STATE.md` with `snapshot --json`. It covers HEAD tree, semantic index entries, and dirty content while excluding state/backlog bookkeeping; a state-only commit does not stale the marker, but source HEAD drift does even with a clean worktree. Index stat-cache-only changes do not stale it. Recheck affected paths instead of blindly rereading the whole project. The separate task fingerprint includes the exact HEAD commit ID for review/integration.

## Hooks do not run

1. Confirm `--hooks` was used and `.codex/hooks.json` points to existing scripts.
2. Review and trust the project hook layer with `/hooks`.
3. Confirm hooks are enabled in the active Codex configuration.
4. Run the verifier's `--self-test` in the isolated setup and inspect its result.

The supported state injection uses `SessionStart` sources `startup`, `resume`, `clear`, and `compact`. The Stop hook is a one-shot prompt. A missing marker stays quiet on a clean legacy tree, but a missing or stale marker triggers one nudge when source or HEAD drift exists. SessionStart still includes a stale note for a missing marker. The bundled helper compares content; older hook installs without it retain a timestamp fallback. Hooks do not start or assign agents.

## Verification is green but acceptance is unclear

Read the command, exit status, and evidence. An unrun check is not green. Confirm that the reviewer checked the integrated code, not just a worker report or a separate branch. The director owns final acceptance.

For a complete local diagnostic, run:

```bash
python scripts/verify_install.py --project /path/to/project --codex-home /path/to/test-codex-home --self-test
python scripts/orchestrate.py --project /path/to/project snapshot --json
```
