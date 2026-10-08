# Project State Hooks

Two small Python hooks make `.codex/PROJECT_STATE.md` durable in practice rather than a file people forget to update. Both are stdlib-only, cross-platform, and designed to fail silently instead of breaking a session.

## What each script does

| Script | Hook event | Behavior |
| --- | --- | --- |
| `inject_project_state.py` | `SessionStart` (`startup|resume|clear|compact`) | Finds the nearest `.codex/PROJECT_STATE.md` within the current Git project and returns it as `hookSpecificOutput.additionalContext`. Silent when no state file exists. |
| `stop_project_state_check.py` | `Stop` | Compares the `state_fingerprint` marker with current source state, then requests one state update with affected paths when stale. Fires at most once per turn. |

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

### Optional ledger directory

Projects without a binding continue using `.codex` for the ledger. To use another project-contained ordinary directory, first create its protected selector explicitly, then pass the same path to the installer so both generated hook commands use it:

```bash
python scripts/orchestrate.py --project /path/to/repo bind-storage --data-dir .orchestrator-data
python scripts/install.py --project /path/to/repo --codex-home /path/to/.codex --hooks --data-dir .orchestrator-data
```

Binding is a one-time protected `.codex/ORCHESTRATOR_STORAGE.json` configuration write. It refuses legacy or unbound ledgers instead of migrating/adopting them. The installer only embeds the supplied path; it never binds or creates the selected directory. Once bound, hooks can omit the runtime flag or use the same path; a different path or missing/invalid selector fails closed. The selected folder holds only ledger bookkeeping; `.codex/PROJECT_STATE.md` and protected role/config files remain under `.codex`. Keep both generated hooks on the same binding. Normal ledger operations write in the selected ordinary folder.

## Relocation caveat

The generated `hooks.json` embeds absolute paths, because Codex runs hook commands with the session `cwd`, which may be a subdirectory. If you move or rename the repository, inspect `.codex/hooks.json` first. If it still contains the old paths, merge or remove that project-local file manually, then rerun:

```bash
python scripts/install.py --project /path/to/repo --codex-home /path/to/.codex --hooks
```

The installer will not replace a differing `.codex/hooks.json`, even with
`--force`; resolve that conflict yourself before retrying. `--force` replaces
other differing managed files with uniquely named backups and never overwrites
an existing backup.

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
- It invokes the co-located `orchestrate.py` helper installed beside the hook, or `scripts/orchestrate.py` in a source checkout. A task snapshot fingerprints the exact HEAD commit, semantic index entries (modes, blob IDs, and conflict stages), and dirty content. State freshness uses a separate `state_fingerprint`: it fingerprints source state while excluding project state/backlog bookkeeping. Thus a state-only commit does not stale its own marker, but a source commit does, even with a clean worktree; index stat-cache-only changes do not stale it.
- Record `state_fingerprint` returned by `python scripts/orchestrate.py snapshot --json` as `<!-- orchestrator-snapshot:<state_fingerprint> -->` after a semantic state update. A missing marker prompts an update only when HEAD or source content has drifted; a clean tree with an unmarked legacy state stays quiet. State discovery stops at the Git project root, so nested repositories do not inherit an outer project's state.
- Actor IDs, reviewer labels, freshness flags, and stopped-owner declarations are manual attestations, not authenticated identity, model, context isolation, or process-control proofs. A Sol senior or Astra consultant used for elevated verification must be a separate instance from the Luna reviewer and every current or former task author. The director records the evidence and resolves any consultant recommendation.
- The hook reads the state file and sends it to the model. Keep secrets out of `PROJECT_STATE.md`.
- Oversized hook output is spilled to disk by Codex, so secrets in hook output can land in temporary files.
- Hooks are guardrails, not an enforcement boundary. Tool coverage can change between releases.
