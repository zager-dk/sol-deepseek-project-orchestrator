# Release and rollback workflow

Read this only when the task includes a deployed service, data migration, or release. Ordinary local implementation, documents, and visual work need no server phase. These checks do not authorize deployment, stopping processes, or changing permissions; existing user authorization, sandbox rules, and platform limits still apply.

## Check the actual target early

Before implementation commits the project to a release approach, inspect the deployment procedure already used by that project. Resolve unknowns with read-only checks in the target environment when available. If target access is unavailable, continue independent local work and record exactly which release checks remain blocked.

- Resolve absolute paths for the current and candidate release, persistent data, mounts, configuration, secrets references, backups, and switch mechanism. Check actual target paths and effective configuration, including required variables and version compatibility; local path assumptions are insufficient. Keep secret values out of reports.
- For containers, identify the real service/container user (UID/GID or equivalent), mounted paths, ownership, and permissions. Check reading the needed config and assets from inside the runtime context using that identity, and writing only where the service requires it. A successful root/host read does not prove the service can read the file.
- Check deployed script bytes and interpreters: LF for Unix shell scripts, supported encoding/BOM behavior, executable permissions, shebang/entrypoint, and syntax. Test the staged executable in its actual runtime where feasible before switching.
- Identify every writer to persistent data: service requests, queues, scheduled jobs, background workers, and other containers. Select a database-native consistent snapshot or a documented coordinated pause/checkpoint covering all relevant writers and data stores. Copying changing files alone is not a consistent backup. Verify the backup is complete, readable, and restorable by a bounded restore check appropriate to the store; record any unrun restore check.

## Keep one project procedure

Reuse the project's existing runbook. If none exists, save one concise versioned procedure (for example `.codex/RELEASE_PROCEDURE.md`) and link it from project state and release tasks. Record:

- target/environment and revision; exact paths and effective nonsecret configuration;
- runtime identity, required reads/writes, and executable/script checks;
- candidate artifact/version, persistent-data/schema compatibility, background writers, consistent backup method and backup identifier;
- preparation, switch, readiness/smoke checks, and a bounded downtime window if needed;
- rollback trigger, prior artifact/configuration, exact restore/switch sequence, and postrollback health check;
- verification evidence, responsible owner, authorization scope, and unresolved prerequisites.

Every release task refers to that procedure and revision. Do not generate new incompatible command sequences at each handoff. Revise it only when the environment, data/schema, artifact format, or a demonstrated failure changes an assumption; recheck affected prerequisites and use independent acceptance for substantial or risky revisions. Evidence can be reused while its artifacts, target, and assumptions remain current.

## Before stopping a service or switching

Finish nondisruptive preparation first. Confirm candidate and prior-release paths exist, runtime reads succeed, data/configuration are compatible, required tools/capacity are available, and the exact switch plus rollback conditions are satisfied. Validate the backup destination and consistency mechanism before pausing writers. If the backup requires a coordinated pause, verify all other prerequisites first, pause only within authorization, take and validate the consistent backup, and then switch. Keep a runnable resume/abort path during the pause. Do not stop the service to discover missing paths, unreadable files, or absent data.

Perform the authorized release using this same procedure, record observed health checks, and execute its rollback on the documented failure condition. Record failures and unrun checks separately. A text runbook or manual ledger entry is not proof that a release or restoration ran successfully. Do not repeat a full environment audit for an unchanged target; recheck only prerequisites that could have drifted since the recorded evidence.
