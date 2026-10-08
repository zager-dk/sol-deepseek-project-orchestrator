# Project instructions for the native Codex orchestrator workflow.

For substantial work, use the orchestrator skill to define bounded backlog
items, delegate implementation to Luna, and independently review meaningful
changes. The technical director sets scope, contracts, dependencies, and
acceptance criteria, then reviews the integrated result.

The primary director uses the `orchestrator-director` Codex config profile. Six
child roles pin their model, default reasoning effort, and requested Standard service
tier in custom-agent TOML files. Verify runtime dispatch separately; these
settings are requests, not proof of actual routing. If Standard is unavailable,
report the blocker instead of silently selecting Fast. Choose concurrency from
task independence and review capacity. Child roles do not delegate nested work.

Keep project state compact and project-specific. Record confirmed results,
failed checks, and checks that were not run. Never store secrets or full chat
history. Run the installer only with an explicit project path and Codex home;
its dry run is safe for inspecting the proposed file plan.
