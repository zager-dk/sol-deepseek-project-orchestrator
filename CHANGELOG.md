# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `hooks.json` now uses the camelCase `commandWindows` key for the Windows
  command override. `command_windows` is accepted only in inline `[hooks]`
  tables in `config.toml`, not in JSON.
- The state injector is registered on `SessionStart` only, with the matcher
  `startup|resume|clear|compact`. `PostCompact` supports only the common output
  fields and cannot carry `additionalContext`, so the injector is no longer
  registered there. Coverage after compaction comes from the `compact` source,
  which Codex runs before the next model request, including mid-turn.
- `ARCHITECTURE.md` stated the small-task threshold backwards: overhead that
  exceeds the change means edit directly, and work that merits delegation means
  dispatch.
- `templates/codex.config.example.toml` no longer implies that leaving
  `default_subagent_model` commented out keeps the root model in charge of
  worker dispatch. It now says the existing subagent default is left unchanged,
  and that the worker route comes from the agent file plus the explicit route at
  dispatch.

### Changed

- The GPT-5.6 Sol at high reasoning root preference is now explicit in
  `ARCHITECTURE.md`, `skill/SKILL.md`, `skill/references/ROUTING.md`, and the
  README, while still allowing another root model when the user selects one.

## [0.1.0] - 2026-09-29

First public release.

### Added

- `ARCHITECTURE.md`: the full English description of the thin-root workflow,
  covering responsibilities, dispatch sequence, worker brief, review and
  correction rules, persistent state lifecycle, the small-task exception,
  routing and verification limits, failure handling, and a worked example.
- `skill/SKILL.md` plus references for the root model: delegation contract,
  durable state policy, and routing notes.
- `templates/agents/deepseek-worker.toml`: a custom subagent that routes to
  `deepseek/deepseek-v4.1-flash`, with `astra_flash_builder` documented as the
  historical alias.
- `templates/PROJECT_STATE.md`: the durable state template.
- `templates/AGENTS.md`: an example project working agreement.
- `templates/codex.config.example.toml`: an illustrative, secret-free router
  configuration using placeholders.
- `hooks/inject_project_state.py` and `hooks/stop_project_state_check.py`:
  project state injection and a one-shot stale-state nudge.
- `scripts/install.py`: a cross-platform, stdlib-only installer with planning,
  conflict detection, dry-run, JSON output, pruning, and opt-in hooks.
- `scripts/verify_install.py`: layout checks plus an optional hook self-test in
  a throwaway repository.
- `scripts/uninstall.py`: removes installed files while preserving user content.
- `tests/`: non-destructive tests for the installer, both hooks, the verifier,
  the uninstaller, and a fresh-repository end-to-end cycle.
- `INSTALL.md`, `QUICKSTART.md`, `SECURITY.md`, `TROUBLESHOOTING.md`,
  `CONTRIBUTING.md`, `README_RU.md`.

### Security

- The installer never guesses the Codex home, never overwrites a differing
  managed file without `--force`, never overwrites `PROJECT_STATE.md` or
  `AGENTS.md`, and never edits `config.toml`, credentials, routing, or user-level
  hooks.
- Both hooks exit `0` with no stdout on any unexpected failure.

### Notes

- Router-specific syntax is illustrative. Confirm model identifiers and router
  commands against your own installation.
- No secrets, machine paths, or private configuration are included in this
  repository.

[Unreleased]: https://github.com/zager-dk/sol-deepseek-project-orchestrator/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/zager-dk/sol-deepseek-project-orchestrator/tree/v0.1.0
