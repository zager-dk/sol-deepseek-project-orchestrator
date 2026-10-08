# Sol + Luna Project Orchestrator

## Optional ledger storage directory

By default the runtime keeps its ledger and lock in the project's `.codex` directory. To move only that bookkeeping data, explicitly bind a contained ordinary directory once:

```powershell
python scripts/orchestrate.py --project . bind-storage --data-dir .orchestrator-data
python scripts/orchestrate.py --project . init
```

The binding writes `.codex/ORCHESTRATOR_STORAGE.json` with create-only semantics. It never migrates or adopts an existing ledger. Binding refuses a legacy ledger, a ledger already in the requested directory, paths outside the project, Git metadata, protected `.codex` configuration subdirectories, and links or reparse points. After binding, omit `--data-dir` or pass the same path; a conflicting path or missing/invalid selector fails closed. The selector remains visible to project snapshots. Initialization and binding coordinate through `.codex/ORCHESTRATOR_STORAGE.lock` followed by the legacy lock; normal ledger updates lock only the selected data directory. Keep both generated hook commands consistent with the binding. Installer `--data-dir` embeds the path into both hooks and does not bind storage or create the selected directory.

A Codex skill and local workflow for substantial project work. A primary Sol 6.1 director writes the contract, manages a dependency-aware backlog, assigns bounded work to Luna or an escalated Sol senior, and accepts the integrated result with independent review. Astra is reserved for consequential unresolved architecture questions.

The existing skill package name `sol-deepseek-project-orchestrator` stays in place for upgrade compatibility. The current mode uses native Codex custom subagents and does not require DeepSeek, an external API router, or a background service.

Start with [QUICKSTART.md](QUICKSTART.md). For the complete workflow and its limits, see [ARCHITECTURE.md](ARCHITECTURE.md). Russian overview: [README_RU.md](README_RU.md).

## Roles

| Role | Model / effort | Responsibility |
| --- | --- | --- |
| Primary director session (`orchestrator-director` profile) | `gpt-6.1-sol`, high | Plan, assign, integrate, and accept; never implement. |
| `sol_senior` | `gpt-6.1-sol`, high | Implement after justified escalation. |
| `luna_worker` | `gpt-6-luna`, medium | Bounded implementation. |
| `luna_reviewer` | `gpt-6-luna`, high | Independent plan and acceptance review, no fixes. |
| `sol_reviewer` | `gpt-6.1-sol`, high | Separate read-only review for high-risk work. |
| `luna_state_editor` | `gpt-6-luna`, low | Narrow state edits under director instruction. |
| `astra_consultant` | `gpt-6-astra`, high | Rare, decision-changing architecture advice. |

The primary profile and six child files currently contain `service_tier = "standard"`, but the installed TOML contract does not explicitly confirm that literal. Do not substitute `default` based on API response terminology. Confirm loading and Standard dispatch in an isolated desktop pilot. The model and effort values are template requests, not runtime proof. Per-task effort adaptations are suggestions for supported launch controls, not a runtime guarantee; task reasons should be recorded. Preserve Luna-first routing. These configuration values do not prove runtime dispatch. Delegated inference availability is account-specific; unavailable roles must be reported without silent substitution.

## Included

- `skill/`: entrypoint and focused routing, delegation, and state references.
- `scripts/orchestrate.py`: standard-library CLI for the project-local backlog ledger and state transitions; it does not launch models.
- `templates/agents/`: native Codex role definitions.
- `templates/PROJECT_STATE.md` and `templates/AGENTS.md`: project memory and optional working-agreement templates.
- `hooks/`: project state injection and freshness nudge hooks.
- `scripts/install.py`, `scripts/verify_install.py`, `scripts/uninstall.py`: explicit-target installation, verification, and cleanup.
- `tests/`: isolated non-destructive checks.

## Install and verify in isolation

Use a disposable project and Codex home first. Inspect the plan with `--dry-run`; the installer does not guess a Codex home:

```bash
python scripts/install.py --project /tmp/demo-project --codex-home /tmp/demo-codex --dry-run
python scripts/install.py --project /tmp/demo-project --codex-home /tmp/demo-codex --hooks
python scripts/verify_install.py --project /tmp/demo-project --codex-home /tmp/demo-codex --self-test
```

On Windows, use separate temporary directories and the same commands with their paths. The installer uses a shared `.orchestrator-install-registry.json`, OS-level locks, and no-clobber behavior for unowned files; failed unlink operations preserve ownership claims. `--force` backs up differing managed files, and `--no-agent` skips only the six child role files; the root director profile remains. Windows hook commands use encoded PowerShell, while POSIX hooks use shell quoting. See [INSTALL.md](INSTALL.md) before installing into a real project.

## First task

Initialize and configure the project-local ledger, then create a task before assigning it:

```bash
python scripts/orchestrate.py --project /path/to/repo init --max-workers 3 --review-round-limit 2 --consultation-limit 1 --escalation-limit 1
python scripts/orchestrate.py --project /path/to/repo add T-101 --goal "Add CSV export" --depends-on "" --priority 50 --risk medium --scope "src/reports/routes.ts,src/reports/Page.tsx" --acceptance "CSV download has headers and rows; unauthenticated request remains 401" --actor director
python scripts/orchestrate.py --project /path/to/repo list
```

Use `python scripts/orchestrate.py --project /path/to/repo --help` and the [Quickstart](QUICKSTART.md) for dispatch, review, integration, recovery, and completion. The director launches agents through Codex; CLI commands record and validate transitions only.

## Project memory and hooks

`.codex/PROJECT_STATE.md` stores compact project facts, hypotheses, plans, accepted changes, blockers, and verification outcomes. It is not a transcript. Optional hooks inject it on supported session events and can issue a one-time freshness nudge. They do not schedule or launch agents. Read [SECURITY.md](SECURITY.md) before enabling hooks.

## Validation and limits

Run the suite from the repository root:

```bash
python -m unittest discover -s tests -v
```

Tests of the CLI validate local state transitions; they do not demonstrate a model call. Report separately the actual live model invocations, test outcomes, and unverified behavior. No cost-saving percentage is claimed without measurement. The package does not install into a live configuration unless the user explicitly runs the installer, and it does not publish, commit, or push.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Keep the skill and its focused references consistent with [ARCHITECTURE.md](ARCHITECTURE.md).

## License

MIT. See [LICENSE](LICENSE).
