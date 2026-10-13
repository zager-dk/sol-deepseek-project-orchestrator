# Routing and model verification

The native mode uses Codex custom subagents. It does not require DeepSeek or an external router. The historical skill package name remains for in-place upgrade compatibility.

## Roles

The technical director is the primary Codex session; `orchestrator-director` is an optional setup profile. It is not a custom child agent. The six child roles have these defaults:

| Child role | Model | Reasoning | Responsibility |
| --- | --- | --- | --- |
| `luna_worker` | `gpt-6-luna` | `medium` | Bounded implementation. |
| `luna_reviewer` | `gpt-6-luna` | `high` | Independent plan and acceptance review; no edits. |
| `luna_state_editor` | `gpt-6-luna` | `low` | Narrow state-file updates directed by the primary session. |
| `sol_senior` | `gpt-6.1-sol` | `high` | Escalated implementation. |
| `sol_reviewer` | `gpt-6.1-sol` | `high` | Independent read-only review of high-risk work. |
| `astra_consultant` | `gpt-6-astra` | `high` | Bounded architecture advice when it can change a decision. |

Role model and effort values are defaults for an explicitly chosen orchestration setup. The user's selected model, speed/service tier, and reasoning effort take precedence. Preserve them in the primary session and dispatch; do not change them automatically or apply role defaults over an explicit choice. Recommend a different effort only when useful, and apply it only through supported controls with user authorization. Omit service-tier overrides from new templates so the client can inherit the selected speed. Standard, other supported modes, and absent or unknown mode metadata do not block work. Unknown metadata remains unverified; do not invent a selector or map UI labels to TOML values. If the platform rejects an actual model or setting, describe the concrete availability/configuration error separately and preserve the selection; do not call it a Standard-mode failure or silently substitute a model. Sandbox, approvals, and platform limits still apply.

Report configured requests and observed runtime model, effort, and tier separately. The collaboration layer may expose no tier metadata; this limits verification, not execution. No usage savings are claimed without measurements.

Suggested effort adaptations, when the user wants them, are worker high for nontrivial logic, senior/reviewer xhigh for a complex reproducible issue, state editor medium for conflicting reports, and Astra xhigh for a consequential architecture choice. Record the reason and apply only an authorized change through supported controls. Otherwise preserve the selected effort. Luna-first routing is a default, not permission to override the user's model choice.

## Configuration and activation

The installer places custom-agent TOML under `<CODEX_HOME>/agents/`; skill files and the Python ledger runtime live under `<CODEX_HOME>/skills/sol-deepseek-project-orchestrator/`. The six child templates contain role instructions and model/effort defaults; they omit `service_tier` to inherit speed. The optional director profile at `<CODEX_HOME>/orchestrator-director.config.toml` supplies Sol/high defaults and enables agents. Use it only when the user chooses that setup, after inspecting its effective settings; an already configured session needs no profile switch. Child definitions disable nested delegation; the Sol reviewer remains read-only. Do not edit active config or existing user selections automatically.

For an explicitly selected CLI setup, use `CODEX_HOME` for the chosen home and `codex --profile orchestrator-director` from the project directory. Do not add a Standard-only launch flag or replace active model/speed/effort settings. The installed ledger runtime `<CODEX_HOME>/skills/sol-deepseek-project-orchestrator/scripts/orchestrate.py` records transitions and does not launch models.

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
