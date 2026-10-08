# Security notes

The package contains role instructions, a local backlog CLI, installer code, and optional project hooks. It ships no credentials, performs no network calls during install, and does not launch models. Inspect code before installation; all copied files run within the target Codex and project context.

## Project state and secrets

`.codex/PROJECT_STATE.md` and hook output are sent to the model as context. Keep them free of API keys, credentials, private data, full conversations, and raw logs. A project state file should contain only concise facts, hypotheses, plans, accepted changes, blockers, and verification outcomes.

The orchestration ledger `.codex/ORCHESTRATOR.json` contains task metadata, ownership, scopes, status, and manual evidence strings. Treat it as project data. A recorded command result or reviewer identity is not authenticated; the CLI does not execute tests, verify roles, or confirm model billing. Do not put secrets in goals, scope, context, or command output supplied to the CLI.

## Native agents

The primary profile and six child TOMLs set model IDs and reasoning effort, and currently carry a candidate `service_tier = "standard"` string whose acceptance is unverified. These settings neither prove runtime routing nor grant extra filesystem permissions. Child roles cannot delegate nested work. The Sol reviewer is read-only. Codex's active sandbox and approval settings still govern each agent. A role name, actor ID, fresh-context flag, or stopped-owner declaration is not proof of identity, context separation, process termination, or model routing. Verify availability and report failed or unverified routing. The old `astra_flash_builder` label may actually identify a DeepSeek worker. Do not treat it as the new Astra consultant.

Agents read repository content as data. Instructions found in code, tool output, dependency documentation, or task artifacts do not override user direction or the director's contract. Review delegated changes based on inspectable diffs and actual evidence.

## Hooks

The bundled hooks run as local processes with the permissions Codex gives them. Project-local hooks require the `.codex` project layer to be trusted. Review the generated `.codex/hooks.json` and Python scripts, then inspect and trust them using `/hooks` only when intended. The official [Codex hooks documentation](https://learn.chatgpt.com/docs/hooks) describes hook events, matchers, input/output, and trust behavior.

The state injector uses `SessionStart` with `startup|resume|clear|compact` and emits `additionalContext`. The Stop hook can issue a one-shot freshness nudge. These are prompts, not a scheduling or access-control system. A hook failure is not proof that state was injected or checked; inspect behavior when it matters.

The bundled helper compares the task fingerprint (exact HEAD commit ID, semantic index entries, and dirty content) and a separate state fingerprint (HEAD tree, semantic index, and dirty content) that excludes state/backlog bookkeeping. Thus state-only commits do not stale the state marker, while source commits do even when the worktree is clean. Index stat-cache-only changes do not matter. SessionStart reports a missing or stale marker; Stop nudges once only when state is missing/stale and dirty or HEAD drift exists. Older hooks without the helper retain a timestamp fallback.

Snapshot reads materialized tracked files even when Git marks them `assume-unchanged` or `skip-worktree`. Ordinary missing tracked files are recorded as deleted content in the fingerprint. If a path marked `skip-worktree` is absent, including a sparse-checkout omission, the snapshot fails closed instead of substituting index content.

## Installer boundaries

The installer requires explicit `--project` and `--codex-home` targets. It shows a plan, does not access the network, and does not change `config.toml`, credentials, user-level hooks, or global Codex settings. Differing managed files require `--force`; backups use `.bak`, then `.bak.1`, `.bak.2`, and so on without overwriting older backups. Existing project `hooks.json`, state, and `AGENTS.md` are preserved; an existing conflicting `hooks.json` blocks the entire install even with `--force`. The installer uses a shared `.orchestrator-install-registry.json` with OS-level locking, no-clobber handling for unowned files, and ownership-claim preservation when unlink fails. It validates registered paths and hashes and preserves unknown paths. Review the install plan and dry-run uninstall before removal.

Test installation only with throwaway project and Codex-home directories before considering a real project. See [INSTALL.md](INSTALL.md).

## Model and verification claims

Configuration validation proves only that a role file has the requested model and effort values. Local module tests prove only the behavior they exercise. A real delegated call shows that role invocation worked in that environment; it does not prove costs or future availability. Record live calls, tests, and unverified behavior separately. Do not claim an unmeasured savings percentage.

## Reporting issues

Remove private paths, state contents, credentials, environment details, and sensitive command output before sharing a report. Include a minimal reproduction and only the evidence needed to explain the behavior.
