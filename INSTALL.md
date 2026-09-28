# Install

Everything here is standard library Python and file copies. No package manager,
no network, no credentials.

## Before you start

You need:

- Python 3.9 or newer;
- the path to your Codex home (usually `~/.codex`, or `%USERPROFILE%\.codex`);
- the path to the project you want to enable;
- git in the project, if you want the `Stop` hook's change detection.

The installer refuses to guess your Codex home. Pass `--codex-home` explicitly or
set `CODEX_HOME`. Writing skill files into the wrong directory is annoying to
clean up, so the installer makes the target explicit instead of assuming.

## Basic install

macOS / Linux:

```bash
git clone https://github.com/zager-dk/sol-deepseek-project-orchestrator.git
cd sol-deepseek-project-orchestrator
python3 scripts/install.py --project ~/code/my-project --codex-home ~/.codex
```

Windows (PowerShell):

```powershell
git clone https://github.com/zager-dk/sol-deepseek-project-orchestrator.git
cd sol-deepseek-project-orchestrator
python scripts\install.py --project C:\code\my-project --codex-home "$env:USERPROFILE\.codex"
```

## See the plan first

```bash
python scripts/install.py --project ~/code/my-project --codex-home ~/.codex --dry-run
```

A dry run prints every action and writes nothing. `--json` prints the same plan
as machine-readable output.

## Flags

| Flag | Meaning |
| --- | --- |
| `--project PATH` | Required. The project root to enable. |
| `--codex-home PATH` | Codex home. Falls back to the `CODEX_HOME` variable. |
| `--hooks` | Also write project-local hooks and `.codex/hooks.json`. |
| `--agents-md` | Also drop the example `AGENTS.md` into the project root. |
| `--no-agent` | Skip `deepseek-worker.toml`; you manage routing yourself. |
| `--force` | Replace managed files that differ, backing each up as `.bak`. |
| `--prune` | Remove files inside the installed skill directory that are not in this bundle. |
| `--dry-run` | Print the plan; write nothing. |
| `--json` | Machine-readable plan and result. |

## What gets written

```text
<codex-home>/skills/sol-deepseek-project-orchestrator/
    SKILL.md
    ARCHITECTURE.md
    references/DELEGATION_CONTRACT.md
    references/STATE_POLICY.md
    references/ROUTING.md

<codex-home>/agents/deepseek-worker.toml          (unless --no-agent)

<project>/.codex/PROJECT_STATE.md                  (created once, never replaced)
<project>/AGENTS.md                                (only with --agents-md, never replaced)

<project>/.codex/hooks/inject_project_state.py     (only with --hooks)
<project>/.codex/hooks/stop_project_state_check.py (only with --hooks)
<project>/.codex/hooks.json                        (only with --hooks, generated)
```

## What is never written

- `config.toml` at any level;
- user-level `hooks.json`;
- credentials, API keys, router keys, or caller capability URLs;
- your existing `PROJECT_STATE.md` or `AGENTS.md`;
- anything outside those two target directories.

The installer also never runs the network and never invokes a model.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success, or a clean dry run. |
| `2` | Usage or environment problem (missing path, no Codex home). |
| `3` | Conflicts detected; **nothing was written**. |

Exit code 3 is the important one. If any managed file already exists with
different content, the installer writes nothing at all and tells you which files
collided. Re-run with `--force` to replace them (each replaced file is saved
next to the original as `<name>.bak`), or delete them yourself.

## Re-running

The installer is idempotent. A second run with the same arguments reports
`created: 0` and `updated: 0`. Nothing is rewritten, so file timestamps and
generated hook configuration stay stable.

## After installing

1. Restart or reopen Codex so the skill and the custom agent are discovered.
2. If you installed hooks, review them with `/hooks` and trust the project
   `.codex` layer. Project-local hooks do not run until trusted.
3. Confirm the worker route resolves to DeepSeek in your model picker.
4. Continue with [QUICKSTART.md](QUICKSTART.md).

## Adding hooks later

Hooks are opt-in and additive; enabling them later does not re-plan the rest:

```bash
python scripts/install.py --project ~/code/my-project --codex-home ~/.codex --hooks
```

The generated `hooks.json` embeds absolute interpreter and script paths, because
Codex runs hook commands with the session working directory, which may be a
subdirectory of the project. If you move or rename the repository, re-run the
installer with `--hooks --force` to regenerate it. The command form that avoids
this is documented in `hooks/README.md`.

## Verify an installation

```bash
python scripts/verify_install.py --project ~/code/my-project --codex-home ~/.codex
python scripts/verify_install.py --project ~/code/my-project --codex-home ~/.codex --self-test
```

The verifier checks that every expected file exists, that the hook configuration
parses and points at real scripts, and that the state file is a sane size. With
`--self-test` it also runs the installed hooks against a throwaway git
repository: state injection, silence on a clean tree, and the one-shot nudge.

Exit code `1` means an error; warnings alone do not fail the check.

## Uninstall

```bash
python scripts/uninstall.py --project ~/code/my-project --codex-home ~/.codex --dry-run
python scripts/uninstall.py --project ~/code/my-project --codex-home ~/.codex
```

The uninstaller removes the installed skill directory, the worker agent file,
the bundled hook scripts, and a `hooks.json` that carries the generated marker.
It keeps `PROJECT_STATE.md` and `AGENTS.md`, because those are yours. Add
`--purge-state` if you really want the state file gone, and a `hooks.json` you
wrote by hand is always left alone.

## Running the tests

```bash
python -m unittest discover -s tests -v
```

The suite is non-destructive: temporary directories, a throwaway git repository,
no network, and no writes anywhere near a real Codex home.

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
