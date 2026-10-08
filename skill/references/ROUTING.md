# Routing and model verification

The native mode uses Codex custom subagents. It does not require DeepSeek or an external router. The historical skill package name remains for in-place upgrade compatibility.

## Roles

The technical director is the primary Codex session, configured by the `orchestrator-director` profile. It is not a custom child agent. The six child roles are:

| Child role | Model | Reasoning | Responsibility |
| --- | --- | --- | --- |
| `luna_worker` | `gpt-6-luna` | `medium` | Bounded implementation. |
| `luna_reviewer` | `gpt-6-luna` | `high` | Independent plan and acceptance review; no edits. |
| `luna_state_editor` | `gpt-6-luna` | `low` | Narrow state-file updates directed by the primary session. |
| `sol_senior` | `gpt-6.1-sol` | `high` | Escalated implementation. |
| `sol_reviewer` | `gpt-6.1-sol` | `high` | Independent read-only review of high-risk work. |
| `astra_consultant` | `gpt-6-astra` | `high` | Bounded architecture advice when it can change a decision. |

The primary profile requests `gpt-6.1-sol` and high reasoning. Role and director templates currently include `service_tier = "standard"`, but the official schema documents only a preferred string and does not explicitly validate `standard` or `default` as the Standard selector. The API response label `default` is not evidence of an accepted TOML value. Validate loading and Standard dispatch in an isolated desktop pilot. Until then treat this field as unverified, not as a confirmed request. The collaboration layer may not expose service-tier metadata. If Standard cannot be selected or confirmed in the target client, report the blocker and stop that route; do not switch to Fast. Report observed runtime model, effort, and service tier separately from configuration. No usage savings are claimed without measurements.

Effort adaptation is a task-specific launch recommendation, not a runtime guarantee: use director xhigh for a complex initial plan, architecture, or contradictions; Luna worker high for nontrivial logic and low only for exact mechanical edits; Sol senior xhigh for a complex reproducible bug; Sol reviewer xhigh for concurrency, data-loss risk, or complex interactions; state editor medium to reconcile reports; Astra xhigh only for an especially complex architecture choice. Record the reason in the task. Apply changes only through supported launch controls; otherwise retain the configured default and report that effort could not be adjusted. This policy does not change Luna-first routing.

## Configuration and activation

The installer places custom-agent TOML under `<CODEX_HOME>/agents/`; its skill files and Python ledger runtime live under `<CODEX_HOME>/skills/sol-deepseek-project-orchestrator/`. For the desktop app project-scoped pilot, manually prepare `<project>/.codex/agents/` and the project skill path as documented in QUICKSTART; the installer does not currently support that layout. Codex reads custom-agent TOML from `<CODEX_HOME>/agents/`. The six child files define `name`, `description`, `developer_instructions`, `model`, `model_reasoning_effort`, and supported settings. The director is a normal profile file at `<CODEX_HOME>/orchestrator-director.config.toml`; it sets model, reasoning effort, the unverified candidate tier string, and `[agents] enabled = true`. See the official [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) and [Codex speed guide](https://learn.chatgpt.com/docs/agent-configuration/speed); neither explicitly documents `standard` or `default` as the TOML value selecting Standard. Child agent definitions set `[agents] enabled = false`; the Sol reviewer also sets `sandbox_mode = "read-only"`.

Set `CODEX_HOME` to the selected home and launch Codex from the target project directory with `codex --profile orchestrator-director`. The official config reference documents profile files as `$CODEX_HOME/profile-name.config.toml` and selection with `--profile profile-name`. This is the Codex CLI launch. Separately, the installed Python ledger runtime is `<CODEX_HOME>/skills/sol-deepseek-project-orchestrator/scripts/orchestrate.py`; it records task transitions and does not launch models.

The installer uses a shared `.orchestrator-install-registry.json`, operating-system locks, and no-clobber behavior for unowned files. A failed unlink preserves its registry claim. It does not change a live global config or copy credentials. Verify the installer dry run and target layout. A live authenticated startup and a harmless native delegation can establish whether the profile and exact child role load in that client; TOML parsing alone cannot. If isolated startup asks for sign-in, stop and let the user decide whether to authenticate. Never copy tokens or authentication files.

## What each validation proves

- TOML parsing proves syntax and configured values, not that Codex loads the profile.
- A strict/live Codex startup, when available, can check runtime configuration. Do not claim this check ran if the CLI was unavailable.
- Installer verification checks copied files and values; it does not invoke models.
- A Python ledger test proves local bookkeeping behavior; it does not prove Codex delegation.
- A live delegation proves that invocation completed in that client. It does not by itself verify hidden routing or billing metadata.
- Actor IDs, reviewer role labels, fresh-context flags, and stopped-owner flags are manual declarations. They do not authenticate identity, guarantee context isolation, or terminate a process.

Record actual agent invocations, tests, config values, and unverified claims separately. Recheck model availability in the target account and client.

## Legacy installations

Some older Codex homes may still contain a custom role configured for an external provider. The installer does not repoint or overwrite unrelated existing role files. Inspect old role configuration explicitly and do not treat it as one of the six native roles.
