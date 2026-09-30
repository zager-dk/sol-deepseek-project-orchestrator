# Routing And Verification Limits

This document states what the orchestrator can and cannot promise about the DeepSeek worker.

## What must be true

- The root is a capable lead model. **GPT-6.1 Sol at high reasoning is the
  preferred choice**; if the user selects another root model, the
  workflow still applies, but the Sol pairing is the default this repository
  documents.
- A custom Codex subagent exists whose `model` resolves to a DeepSeek V4.1 Flash route.
- The route is reachable at dispatch time.
- The route is passed explicitly at dispatch, so the worker does not silently inherit the root model.

The repository ships `templates/agents/deepseek-worker.toml` with:

```toml
name = "deepseek_worker"
model = "deepseek/deepseek-v4.1-flash"
model_reasoning_effort = "high"
```

Install it to `~/.codex/agents/deepseek-worker.toml` (personal) or `<repo>/.codex/agents/deepseek-worker.toml` (project-scoped). Codex loads standalone agent files from those directories and identifies the agent by the `name` field.

The optional `deepseek_integrator` role uses the same explicit model/effort.
Install it with `--adaptive`, or use a legacy worker with ROLE=integrator.
Neither route changes the selected root or shares credentials. Existing GPT-5.6
Sol roots remain supported.

## Legacy name

Older setups, including the one this repository grew out of, used the historical role name `astra_flash_builder` for the same job. If your installation still exposes that name, it is the same worker: use it, and note the alias in your dispatch. New installs should use `deepseek_worker`.

## What to do when routing is unavailable

Report the routing problem. Do not silently fall back to another paid model, and do not pretend the work was delegated.

Acceptable responses, in order of preference:

1. Fix the route (enable the provider, re-check the model id in the picker) and dispatch once.
2. Ask the user whether to proceed with the root model only, and say explicitly that orchestration was not used.
3. Stop and report blocked with the routing evidence.

## Unverified details

Model identifiers such as `deepseek/deepseek-v4.1-flash` are router-supplied. The exact slug depends on the router build and the providers you enabled, so confirm it against your own model picker or router CLI before relying on it. If your catalog uses a different slug, change the `model` field and nothing else.

The example router configuration in `templates/codex.config.example.toml` is illustrative. It shows the shape of a routed provider block with placeholders instead of a real caller capability URL. Read your router's own README for the authoritative, version-specific steps.

## Verification limits

- The orchestrator does not verify that a worker actually used DeepSeek. The root sees a completion report, not provider billing.
- Provider-side token counters are the authoritative cost measurement if you need one; the router forwards requests, and the upstream provider bills them.
- A worker's report is a claim. Accept work on inspectable evidence, and rerun a focused check when the evidence is missing, suspicious, or high-risk.
- A green exit status is not acceptance. Look at what the command actually proved.
- Hooks are guardrails, not an enforcement boundary. Tool coverage can change between releases, and project hooks run only after the project `.codex` layer is trusted.
