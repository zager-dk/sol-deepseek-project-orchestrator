# Project State Hooks

Two small Python hooks make `.codex/PROJECT_STATE.md` durable in practice rather than a file people forget to update. Both are stdlib-only, cross-platform, and designed to fail silently instead of breaking a session.

## What each script does

| Script | Hook event | Behavior |
| --- | --- | --- |
| `inject_project_state.py` | `SessionStart` (`startup|resume|clear|compact`) | Finds the nearest `.codex/PROJECT_STATE.md`, walks up from the session `cwd`, and returns it as `hookSpecificOutput.additionalContext`. Silent when no state file exists. |
| `stop_project_state_check.py` | `Stop` | If git reports repository changes and the state file is older than every changed path, asks for one state-update pass. Fires at most once per turn. |

The injector is registered on `SessionStart` only. The `compact` source in its
matcher is what handles the window after compaction: Codex runs matching
`SessionStart` hooks before the next model request, including when automatic
compaction happens in the middle of a turn. `PostCompact` is deliberately not
used, because that event supports only the common output fields and cannot carry
`additionalContext`.

## Contract used

Codex command hooks receive one JSON object on stdin with fields such as `session_id`, `hook_event_name`, `cwd`, `model`, and turn-scoped extras like `turn_id` and `stop_hook_active`. Output rules differ per event:

- `SessionStart`: plain text on stdout becomes developer context, or return `hookSpecificOutput.additionalContext`.
- `Stop`: JSON is required. `{"decision": "block", "reason": "..."}` continues the turn with `reason` as the new prompt. `stop_hook_active` tells the hook that Codex already continued once.

Both scripts keep stdout clean. Anything unexpected goes to stderr and the hook exits 0.

Field naming differs by file format: `hooks.json` uses camelCase
(`commandWindows`, `statusMessage`, `additionalContextLimit`), while the inline
`[hooks]` tables in `config.toml` accept snake_case (`command_windows`).

## Installing

```bash
python scripts/install.py --project /path/to/repo --codex-home /path/to/.codex --hooks
```

That writes `<repo>/.codex/hooks/*.py` plus a generated `<repo>/.codex/hooks.json` containing absolute interpreter and script paths. Project-local hooks load only after Codex trusts the project `.codex` layer; review them with `/hooks`.

## Relocation caveat

The generated `hooks.json` embeds absolute paths, because Codex runs hook commands with the session `cwd`, which may be a subdirectory. If you move or rename the repository, re-run:

```bash
python scripts/install.py --project /path/to/repo --codex-home /path/to/.codex --hooks --force
```

For a portable team setup, prefer adding the hook commands through your shared repository configuration with a git-root-resolved path instead, for example:

```json
"command": "python3 \"$(git rev-parse --show-toplevel)/.codex/hooks/inject_project_state.py\""
```

That form depends on a POSIX shell; Windows sessions need `commandWindows` (in
`hooks.json`) or an absolute path.

## Disabling without uninstalling

```bash
SOL_DEEPSEEK_DISABLE_STATE_HOOK=1
```

Set that in the environment Codex is launched from, or remove the entry from `.codex/hooks.json`.

## Safety notes

- The Stop hook never writes state; it only asks the root to do so.
- The hook reads the state file and sends it to the model. Keep secrets out of `PROJECT_STATE.md`.
- Oversized hook output is spilled to disk by Codex, so secrets in hook output can land in temporary files.
- Hooks are guardrails, not an enforcement boundary. Tool coverage can change between releases.
