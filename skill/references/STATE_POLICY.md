# Durable Project State Policy

Canonical file: `.codex/PROJECT_STATE.md`

Keep it concise and current. It should let a fresh root session understand the project in a few thousand tokens without replaying old chats.

## Required sections

### Project intent
One short paragraph: what this repository/product is trying to achieve.

### Current milestone
One current milestone and its status. Remove completed transient detail.

### Architecture / contracts
Only durable architecture facts, public interfaces, data-flow constraints, and dependencies that affect future work.

### Decisions / constraints
Durable decisions and non-goals. Prefer bullets with a short reason when the reason prevents future reversal.

### Active work
What is currently in progress or just accepted but not fully integrated.

### Known issues / risks
Only unresolved items that matter to future work.

### Verification baseline
The commands/checks that currently define a healthy project or feature when known.

### Next steps
No more than 5 concrete next actions, ordered by priority.

### State metadata
Last semantic update date/time and, when useful, branch/commit reference. Metadata is informational, not a substitute for semantic state.

## Compression rules

- Replace stale bullets; do not append forever.
- Delete resolved blockers.
- Collapse old completed work into the current architecture or milestone outcome.
- Never paste logs, stack traces, full diffs, or transcripts.
- Keep under 10 KB when possible; the bundled Stop hook warns at 14 KB.

## Ownership

The root model owns this file. A worker may update it only when the dispatch explicitly says so, and even then only inside the named sections.

## Lifecycle

1. The installer writes the template once, and never overwrites an existing state file.
2. The `SessionStart` hook injects the file on startup, resume, clear, and post-compaction (the `compact` source).
3. The root updates the file when accepted work changes durable facts.
4. The `Stop` hook asks for one extra pass if the repository changed and the state file looks stale.
