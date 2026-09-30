<!-- Example AGENTS.md for GPT-6.1 Sol + DeepSeek adaptive thin-root orchestration. -->

## Working agreement

For substantial coding work, use the `sol-deepseek-project-orchestrator` skill.

### Root

- Preferred root: GPT-6.1 Sol High, Standard speed.
- Keep the root thin: scope/contracts, adaptive delegation, integration judgement, one batched review, at most one correction phase.
- Default to one DeepSeek worker.
- Use two or three only for genuinely independent streams with clear ownership and meaningful wall-clock benefit.
- Do not poll workers. Wait for all; stop/close finished children before the
  integrator starts. Workers and integrators do not delegate further.
- A current user request for single-agent work takes precedence.
- Existing GPT-5.6 Sol roots and the one-worker path remain supported.
- Own `.codex/PROJECT_STATE.md`.

### Parallel workers

- Multiple concurrent writers require isolated worktrees/branches at one clean
  baseline. If isolated dispatch is unavailable, use one writer.
- Every worker gets explicit OWNERSHIP and NO-TOUCH paths.
- Workers never edit `.codex/PROJECT_STATE.md`.
- If safe write isolation is unavailable, keep one writer and use extra workers only for read-only investigation/review.

### Integration

- With one writer, Sol reviews the result directly.
- With multiple writers, run one `deepseek_integrator` pass first
  (legacy `deepseek_worker` with ROLE=integrator is supported).
- The integrator may combine local worker commits/patches and resolve routine conflicts only when explicitly authorized.
- Sol reviews the integrated result once rather than re-reviewing every worker independently.

### Safety

- No push, publish, deploy, destructive remote action, or credentials change without explicit user approval.
- Do not weaken tests/types/validation/security checks to obtain a green result.
- Stop and escalate product/architecture ambiguity rather than inventing a cross-stream decision.
