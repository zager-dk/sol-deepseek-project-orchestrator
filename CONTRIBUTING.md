# Contributing

Keep the workflow understandable and its claims tied to behavior. The current design uses native Codex custom subagents with a director-managed local backlog; it does not include an external router or a background scheduler.

## Before proposing a change

- Read [ARCHITECTURE.md](ARCHITECTURE.md) and the relevant reference under `skill/references/`.
- Preserve the primary director's no-implementation boundary, the six child roles, their model/effort settings, and the current candidate `service_tier` string. Its accepted Standard value is unverified; do not treat `standard` and `default` as interchangeable. Do not describe config or actor labels as proof of dispatch or identity.
- Keep the install path isolated and explicit. Do not add global Codex configuration writes, network access, or secret handling.
- Update user-facing docs, examples, and tests when command behavior changes.

## Validation

Run the checks appropriate to the change. For code changes, the current suite is:

```bash
python -m unittest discover -s tests -v
```

For documentation-only changes, check commands and file paths against the current implementation and search for stale role names or unsupported promises. Do not add or claim a test that was not run. Installation changes must be checked in throwaway Codex-home and project directories.

The installer and verifier can validate config values and local ledger behavior. They do not prove a live model call or service tier. The Python ledger is separate from the `codex` runtime CLI. Report module tests, actual delegated calls, and unverified behavior separately.

## Review principles

- Backlog records need ID, goal, dependencies, priority, risk, scope, acceptance, owner, and status.
- Assignment must prevent duplicates and respect dependencies and exclusive shared-resource ownership.
- Interruption recovery preserves changes and records a declaration that the old agent stopped; the CLI cannot verify or terminate its process.
- Review is independent and returns pass, fail, or inconclusive with evidence. It never edits the reviewed implementation.
- Integration checks the exact combined state before dependents are unlocked.
- Keep correction and consultation cycles bounded.

## Reporting issues

Include a minimal reproduction, exact commands and outcomes, and relevant platform/Python versions. Remove secrets, private paths, and project-state contents.

## License

Contributions are licensed under the MIT License in [LICENSE](LICENSE).
