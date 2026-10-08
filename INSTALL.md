# Install

The installer is standard-library Python. The CLI targets Python 3.9+ and requires a Git working tree with an existing commit for snapshots; this environment verified it with Python 3.10.6. It copies the skill, its bundled local Python ledger CLI, six native child-role definitions, and the separate primary-session profile to explicit destinations. The Python ledger CLI records transitions; the Codex CLI (`codex`) starts model sessions. Optional hooks are project-local. It does not access the network, invoke models, install into a guessed Codex home, or edit `config.toml`.

## Verify in a disposable environment first

Use an existing throwaway project directory and a separate Codex-home path. The Codex home may be created by the installer. The project must be a Git worktree with an existing commit before initializing the ledger.

```bash
python scripts/install.py --project /tmp/demo-project --codex-home /tmp/demo-codex --dry-run
python scripts/install.py --project /tmp/demo-project --codex-home /tmp/demo-codex --hooks
python scripts/verify_install.py --project /tmp/demo-project --codex-home /tmp/demo-codex --self-test
```

PowerShell example:

```powershell
python scripts\install.py --project C:\temp\demo-project --codex-home C:\temp\demo-codex --dry-run
python scripts\install.py --project C:\temp\demo-project --codex-home C:\temp\demo-codex --hooks
python scripts\verify_install.py --project C:\temp\demo-project --codex-home C:\temp\demo-codex --self-test
```

Read the full plan. Use `--json` for machine-readable output. Never test installation against your live Codex home unless you have deliberately chosen that target.

## Options

| Option | Effect |
| --- | --- |
| `--project PATH` | Required project root. |
| `--codex-home PATH` | Required Codex home unless `CODEX_HOME` is set. |
| `--hooks` | Add project-local state hooks, their local CLI copy, and generated `.codex/hooks.json`. |
| `--agents-md` | Add the example root `AGENTS.md` only if none exists. |
| `--no-agent` | Skip installation of the six bundled child-agent TOML files only; the primary director remains the interactive Codex session. |
| `--force` | Replace differing managed files and save a unique `.bak`, `.bak.1`, etc. without overwriting earlier backups. User-owned state and `AGENTS.md` are preserved. Existing project `.codex/hooks.json` is protected even with `--force`; merge or remove that conflict manually, then retry. |
| `--prune` | Remove unchanged, previously recorded files at known managed paths that are no longer in the bundle. Unknown files and unregistered paths are preserved. |
| `--dry-run` | Show planned operations without writing. |
| `--json` | Print the plan/result as JSON. |

Existing configuration, credentials, routing, and user-level hooks remain untouched. The installer records managed paths and hashes in the shared `.orchestrator-install-registry.json`. It uses operating-system locks, does not clobber existing unowned files, and preserves ownership claims when an unlink fails. A checksum alone does not grant ownership. Unknown or unrecognized paths are ignored and preserved. Inspect the registry-aware plan and dry-run uninstall before applying it.

## Installed layout

```text
<codex-home>/skills/sol-deepseek-project-orchestrator/
    SKILL.md
    ARCHITECTURE.md
    references/...
    scripts/orchestrate.py

<codex-home>/agents/
    luna-worker.toml
    luna-reviewer.toml
    luna-state-editor.toml
    sol-senior.toml
    sol-reviewer.toml
    astra-consultant.toml
<codex-home>/orchestrator-director.config.toml

<project>/.codex/PROJECT_STATE.md             (created only when absent)
<project>/.codex/ORCHESTRATOR.json            (created by CLI init)
<project>/.codex/hooks/                       (only with --hooks)
<project>/AGENTS.md                           (only with --agents-md and absent)
```

With `--hooks`, a copy of the CLI is placed beside the hooks. The hooks use content-aware state fingerprints and task snapshots, not file modification times. Generated commands use platform-appropriate quoting: encoded PowerShell on Windows and shell quoting on POSIX; paths are absolute. After moving the project, inspect the new plan; if `.codex/hooks.json` differs, the installer blocks replacement even with `--force`. Merge or remove that file manually before retrying.

The director profile is a root config profile and is not installed under `agents/`. `--no-agent` skips only the six child TOMLs. The ledger runtime lives at `<codex-home>/skills/sol-deepseek-project-orchestrator/scripts/orchestrate.py`; it is separate from the `codex` command used to launch model sessions. The official [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) documents `<CODEX_HOME>/<profile>.config.toml` files and `--profile <profile>` selection.

The historical package directory name is retained for in-place upgrade compatibility. It does not mean the native workflow depends on DeepSeek. The old `astra_flash_builder` configuration may point to DeepSeek; it is not the new Astra consultant.

## Verify

```bash
python scripts/verify_install.py --project /tmp/demo-project --codex-home /tmp/demo-codex
python scripts/verify_install.py --project /tmp/demo-project --codex-home /tmp/demo-codex --self-test
```

`verify_install.py` requires Python 3.11+ because it uses the standard-library `tomllib` parser; under an older Python it reports that no configuration was validated. The installer and runtime ledger do not share this verifier-only requirement. Python 3.12.14 was available in this environment. If installation intentionally used `install.py --no-agent`, verify it with the matching explicit flag, for example `python scripts/verify_install.py --project /tmp/demo-project --codex-home /tmp/demo-codex --no-agent`. This permits absent child-role files, but any existing role files are still verified, whether or not the registry claims ownership. Verification checks installed files, configured role model/effort/tier fields, hook configuration, and local ledger behavior. The tier string's semantic acceptance remains unverified; verification does not prove observed dispatch tier. It also does not authenticate manual role/actor claims. The hook self-test uses a temporary project. These checks do not invoke every configured model or prove that future delegated calls are available. See [ROUTING.md](skill/references/ROUTING.md) for the distinction between configuration validation, module tests, and real inference.

## Initialize a project ledger

After installation, initialize the local backlog separately:

```bash
python scripts/orchestrate.py --project /tmp/demo-project init --max-workers 3 --review-round-limit 2 --consultation-limit 1 --escalation-limit 1
python scripts/orchestrate.py --project /tmp/demo-project snapshot --json
```

The installed copy is also available at `<codex-home>/skills/sol-deepseek-project-orchestrator/scripts/orchestrate.py`. It manages `.codex/ORCHESTRATOR.json`; it does not launch models. Start with [QUICKSTART.md](QUICKSTART.md) for the workflow.

## Uninstall

```bash
python scripts/uninstall.py --project /tmp/demo-project --codex-home /tmp/demo-codex --dry-run
python scripts/uninstall.py --project /tmp/demo-project --codex-home /tmp/demo-codex
```

The shared install registry lets uninstall remove only unchanged files that the installer still claims. Project state and root `AGENTS.md` are user-owned and kept. Any file modified after installation is preserved with a warning. Inspect the plan before applying it.

## Troubleshooting and safety

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) and [SECURITY.md](SECURITY.md). Review project hooks with `/hooks` and trust the project layer before expecting them to run. The hooks are convenience prompts, not a scheduler or enforcement mechanism.
