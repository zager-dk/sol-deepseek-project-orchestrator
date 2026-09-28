# Troubleshooting

Symptoms first, then the fix.

## Installation

### "no Codex home given. Pass --codex-home PATH or set CODEX_HOME."

Intentional. The installer refuses to guess where your Codex home is.

```bash
python scripts/install.py --project ~/code/my-project --codex-home ~/.codex
# or
CODEX_HOME=~/.codex python scripts/install.py --project ~/code/my-project
```

On Windows, `$env:USERPROFILE\.codex` is the usual location.

### Exit code 3, "Nothing was written"

A managed file already exists with different content. The installer writes
nothing until you decide.

```bash
# Option A: replace the managed files, keeping .bak copies
python scripts/install.py --project ~/code/my-project --codex-home ~/.codex --force

# Option B: inspect first
python scripts/install.py --project ~/code/my-project --codex-home ~/.codex --dry-run
```

`PROJECT_STATE.md` and `AGENTS.md` never participate in this. They are yours.

### "no config.toml found in <codex-home>"

A warning, not an error. It usually means the path is not the Codex home you
think it is. Confirm before continuing.

### "project does not look like a git repository"

The skill and hooks still install. The `Stop` hook cannot detect changes without
git, so it will stay silent. Run `git init` in the project if you want that
behavior.

### Repeated installs keep changing the skill directory

Use `--prune` once to remove files that are not part of the current bundle, such
as references left over from an older version.

## Hooks

### Hooks do not run at all

Check, in order:

1. Is hooks support enabled? `[features] hooks = false` in `config.toml` turns
   them off globally.
2. Did you trust them? Run `/hooks` and review. Project-local hooks do not run
   in an untrusted project.
3. Did the hook definition change since you trusted it? Trust is recorded against
   the current hook hash, so editing `hooks.json` requires a fresh review.
4. Does the command in `hooks.json` point at a path that still exists?

### Hooks stopped working after moving the repository

Expected. The generated `hooks.json` embeds absolute paths.

```bash
python scripts/install.py --project /new/path --codex-home ~/.codex --hooks --force
```

### The Stop hook repeats itself

It should not. The design allows one nudge per turn, and it stands down whenever
`stop_hook_active` is set. If you see a loop:

1. disable it immediately with `SOL_DEEPSEEK_DISABLE_STATE_HOOK=1`;
2. remove the entry from `.codex/hooks.json`;
3. clear stale markers from `%TEMP%\sol-deepseek-state-nudge` (or the
   `SOL_DEEPSEEK_NUDGE_DIR` you configured);
4. file an issue with the hook's actual stdout.

### The Stop hook is silent even though I changed files

Expected in these cases:

- the working tree is clean (uncommitted changes were never made);
- `PROJECT_STATE.md` is newer than every changed path, so the state is not stale;
- the session is outside a git repository;
- git is not installed or not on `PATH`;
- the one-per-turn guard already fired for this turn.

### `PROJECT_STATE.md` is not injected

- The hook walks up from the session working directory. A state file must be at
  `<some-parent>/.codex/PROJECT_STATE.md`.
- An empty state file is treated as absent (nothing to inject).
- Very large state files are truncated with a visible marker. If you see the
  marker, compact the file.

## Routing and the worker

### The `deepseek_worker` agent is missing

1. Confirm the file exists: `<codex-home>/agents/deepseek-worker.toml`
   (`--no-agent` skips it on purpose).
2. Restart or reopen Codex; custom agent files are read at startup.
3. Remember the source of truth is the `name` field inside the file, not the
   filename.

### The worker runs, but not on DeepSeek

Check the model slug.

```toml
model = "deepseek/deepseek-v4.1-flash"
```

Router model identifiers are environment-specific. Open your model picker, or
ask your router CLI to list models, and use the exact slug you see there. The
bundled value is a starting point.

### The route is unavailable

Report it. Do not silently substitute a different paid model. Acceptable
responses are: fix the route and dispatch once, ask the user whether to proceed
with the root model alone, or stop and report the routing evidence.

### The worker returns `blocked`

Read the blocker before reacting. If it is a missing contract, supply it and
re-dispatch once. If it is genuinely external, tell the user. Do not retry the
same brief and hope for a different result.

## Workflow quality

### The root keeps rewriting the worker's code

The bundle was too small, or the brief was too vague. Send a larger bundle with
sharper acceptance criteria.

### The worker's report is thin

The brief is the problem. Add explicit acceptance criteria and an explicit
verification section, then re-dispatch once.

### The state file keeps growing

Someone is writing history instead of state. Remove command output, logs,
resolved blockers, and completed work that is now part of the architecture
section. Update bullets in place; do not append.

### Fixes keep failing after a correction

Stop the loop. After one focused correction, diagnose at the root or escalate
the real blocker to the user. Repeating the same dispatch is not a strategy.

## Still stuck

```bash
python scripts/verify_install.py --project ~/code/my-project --codex-home ~/.codex --self-test
```

The verifier reports what exists, what parses, and how the hooks behaved against
a throwaway repository. That output is the most useful thing to include in an
issue.
