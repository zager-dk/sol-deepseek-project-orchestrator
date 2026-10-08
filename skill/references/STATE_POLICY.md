# Project state policy

Project memory is stored in `.codex/PROJECT_STATE.md`, separate for each repository. The orchestration ledger is `.codex/ORCHESTRATOR.json`. The ledger tracks task metadata and transitions; the Markdown state carries compact project knowledge. Neither file is a chat transcript.

## State contents

Keep only information that helps the next task start accurately:

- project intent and current milestone;
- durable architecture, contracts, and constraints;
- confirmed facts, clearly marked hypotheses, and plans as distinct items;
- backlog summary, active work, accepted integrated changes, and blockers;
- verification baseline and actual outcomes, including failed and unrun checks;
- concise state metadata such as date and snapshot reference.

Do not store credentials, secrets, full history, raw logs, or large diffs. Replace stale bullets instead of appending a diary. Remove resolved blockers and transient debugging notes. Keep the state compact (aim below 10 KB).

## Ownership

The director owns the meaning and acceptance of project state. It can ask `luna_state_editor` to make a small change using explicit instructions. The editor updates only the named sections and returns a short diff. The director checks that diff and confirms evidence before accepting claims.

## Freshness

At task start, compare the HTML marker in `.codex/PROJECT_STATE.md` with `state_fingerprint` from `python scripts/orchestrate.py snapshot --json`. State freshness uses the HEAD tree, semantic index entries (modes, object IDs, conflict stages), and dirty content, excluding project-state and orchestration bookkeeping. A state-only commit does not stale this marker; a source commit does even when the worktree is clean. Changes to Git index stat-cache metadata do not affect it. The separate task `fingerprint` uses the exact HEAD commit ID, semantic index, and dirty content for review/integration. Recheck affected paths on drift rather than rereading the entire repository. After semantic state edits, copy the current `state_fingerprint` into `<!-- orchestrator-snapshot:<state_fingerprint> -->`.

## Backlog records

Each task record in `.codex/ORCHESTRATOR.json` has an ID, goal, dependencies, priority, risk, scope, acceptance criteria, owner, and state. Assignment requires completed dependencies and no existing owner. Keep one writer on a shared file or serialize those tasks. Interrupted tasks retain their changes and history. Reassignment requires a director declaration that the prior agent stopped, plus a safe handoff of the current diff and remaining work. Actor IDs, freshness flags, and stop-owner declarations are not authenticated; they neither prove a separate context nor terminate a process.

The local CLI validates bookkeeping transitions; it does not spawn Codex agents or provide a background scheduler. The director remains responsible for model dispatch, inspection, and integration.

## Hooks

The SessionStart hook injects state at startup, resume, clear, and compaction. It includes a stale note whenever the marker is missing or differs from the current snapshot. The Stop hook nudges at most once when state is missing/stale and dirty or HEAD drift exists; it stays quiet for a clean legacy state with no marker. The bundled helper compares content snapshots rather than mtimes. Older manual hook installs without the helper retain a timestamp fallback. Hooks are prompts with local process permissions; they do not enforce task ownership or schedule agents. Review the local hook source and generated hook configuration before enabling. Hooks run with local process permissions and may expose their output to the model; keep secrets out of state and hook output.
