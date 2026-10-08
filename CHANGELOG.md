# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Reworked the workflow around native Codex subagents: Sol 6.1 director and escalated senior, Luna worker/reviewer/state editor, and rare Astra consultant.
- Added a local, director-managed backlog and explicit task transitions; the CLI records state but does not launch models or run as a daemon.
- Updated acceptance, interruption recovery, integrated verification, project freshness, and competing-hypothesis guidance.
- Kept the historical skill package directory name for upgrade compatibility; new installs no longer require DeepSeek or an external router.
- Split the primary director profile from exactly six child agents and added an independent read-only Sol reviewer.
- Record the candidate Standard service-tier config value as unverified until an isolated desktop pilot confirms it; distinguish configuration from runtime dispatch.
- Clarified the separate Codex CLI and installed Python ledger runtime, as well as the limits of manual identity and freshness attestations.

### Removed

- Removed the old workflow claims that the director may implement small tasks and that every substantial task must use one DeepSeek worker.
- Removed the assumption that `astra_flash_builder` is an Astra role; old installations may route that historical name to DeepSeek.

## [0.1.0] - 2026-09-29

First public release of the thin-root workflow, DeepSeek worker template, project state hooks, installer, verifier, uninstaller, and non-destructive tests.
