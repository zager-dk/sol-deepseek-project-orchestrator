# Project State

> Durable working memory for this project. State, not history.
> The root model owns this file. Keep it under 10 KB.
> Replace stale bullets instead of appending a chronological diary.

## Project intent

_One short paragraph: what this repository or product is trying to achieve._

## Current milestone

- **Milestone:** _name_
- **Status:** _not started / in progress / accepted_
- **Definition of done:** _the observable outcome that closes it_

## Architecture / contracts

- _Durable architecture facts, public interfaces, data-flow constraints, dependencies._

## Decisions / constraints

- _Decision, with a short reason when the reason prevents future reversal._
- _Non-goal that must stay a non-goal._

## Active work

- _What is in progress, or accepted but not fully integrated._

## Known issues / risks

- _Only unresolved items that matter to future work._

## Verification baseline

- _The commands or checks that currently define a healthy project._

## Visual work (omit when unused)

- **Task / profile / spec revision / stage:** _visual-design, ux-ui, storyboard, or motion-fx; current version and stage._
- **Direction / palette / approvals:** _selected direction, exact palette, and source references for user direction and prototype approval; existing style source/version if used._
- **Capabilities / blockers:** _observed availability, missing required capabilities, or sourced user agreement to revised scope._
- **Deliverables:** _paths to current editable sources, rendered preview, and report; detailed manifests stay in the ledger._
- **Visual QA:** _independent reviewer and observed results; UI interaction/responsive/accessibility evidence or motion full-playback evidence as applicable; failed and unrun checks._

_Follow the skill's Visual workflow reference. A new direction needs a new spec and approvals; the CLI records manual evidence and does not inspect or authenticate it._

## Next steps

1. _Highest priority next action._
2. _Second action._
3. _Third action (keep the list at five or fewer)._

## State metadata

- **Last semantic update:** _YYYY-MM-DD_
- **Branch / commit:** _optional_
- **Snapshot:** `<!-- orchestrator-snapshot:<state_fingerprint> -->` (copy `state_fingerprint` from `python scripts/orchestrate.py snapshot --json` after semantic edits; it excludes state/backlog paths, so a state-only commit does not stale itself. The separate `fingerprint` field is exact HEAD + semantic index + dirty content for review/integration.)

Keep confirmed facts, hypotheses, and plans in separate labeled bullets. Record verification commands with `passed`, `failed`, or `not run`; never present an unrun check as passing. Do not store credentials, secrets, or conversation transcripts.
