# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-13

### Added

- Four visual task profiles (`visual-design`, `ux-ui`, `storyboard`, `motion-fx`) on the existing code ledger, without changing the primary director or six child roles.
- Version-bound brief/reference/direction specs, observed capability preflight records, explicit user direction and prototype approval records, production gates, and editable/preview/report manifests.
- Independent visual QA evidence for opened renders, UI interactions/responsive/accessibility, story continuity, and full-duration motion playback; existing review/integration/completion gates remain required.
- One focused visual workflow reference, starter JSON/assets, compact project-state guidance, and a privacy-filtered visual category sidecar in JSON statistics. Records remain manual declarations, not tool execution, authenticated approvals, or model/token/cost measurements. No Unreal Engine integration.

### Changed

- Reworked the workflow around native Codex subagents: Sol 6.1 director and escalated senior, Luna worker/reviewer/state editor, and rare Astra consultant.
- Added a local, director-managed backlog and explicit task transitions; the CLI records state but does not launch models or run as a daemon.
- Updated acceptance, interruption recovery, integrated verification, project freshness, and competing-hypothesis guidance.
- Kept the historical skill package directory name for upgrade compatibility; new installs no longer require DeepSeek or an external router.
- Split the primary director profile from exactly six child agents and added an independent read-only Sol reviewer.
- Preserve user model/speed/effort selections; remove Standard-only instruction and verifier gates and template speed overrides. Unknown/missing speed metadata is nonblocking; live availability remains separately verified.
- Check deployment prerequisites early only for deployed work, reuse one project release/rollback procedure, and send concise briefs while retaining independent and visual acceptance.
- Clarified the separate Codex CLI and installed Python ledger runtime, as well as the limits of manual identity and freshness attestations.

### Removed

- Removed the old workflow claims that the director may implement small tasks and that every substantial task must use one DeepSeek worker.
- Removed the assumption that `astra_flash_builder` is an Astra role; old installations may route that historical name to DeepSeek.

## [0.1.0] - 2026-09-29

First public release of the thin-root workflow, DeepSeek worker template, project state hooks, installer, verifier, uninstaller, and non-destructive tests.
