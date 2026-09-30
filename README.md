# Sol + DeepSeek Project Orchestrator

Adaptive v0.2 keeps **GPT-6.1 Sol** as a thin technical lead and reviewer,
while **DeepSeek V4.1 Flash** owns discovery, implementation, tests, and debugging.
Sol chooses **1–3 workers** based on independence, ownership, and expected time
benefit. One worker remains the default. Multiple writers use isolated worktrees
and one DeepSeek integration pass before Sol reviews the combined result.

GPT-6.1 Sol with high reasoning and Standard speed is the suggested starting
profile. Existing GPT-5.6 Sol users can keep their selected root and single-worker
setup. Installation does not change the selected model, router, or credentials.

Read [ARCHITECTURE.md](ARCHITECTURE.md) for the complete English explanation
and operational rules. [Русское описание](README_RU.md).

## What is in the box

| Path | What it is |
| --- | --- |
| `ARCHITECTURE.md` | The long-form design and workflow document. |
| `skill/` | The Codex skill: `SKILL.md` plus references. Installs to `<codex-home>/skills/`. |
| `templates/agents/deepseek-integrator.toml` | Optional integration agent (`--adaptive`). |
| `skill/scripts/prepare_worktrees.py` | Offline worktree preparation with preflight and dry-run. |
| `templates/agents/deepseek-worker.toml` | Custom subagent that routes to DeepSeek V4.1 Flash. |
| `templates/PROJECT_STATE.md` | The durable state template copied into your project. |
| `templates/AGENTS.md` | Example project working agreement. |
| `templates/codex.config.example.toml` | Illustrative, secret-free router configuration. |
| `templates/hooks.example.json` | Reference shape of the generated project hook config. |
| `hooks/` | Two stdlib Python hooks: state injection, and a one-shot state nudge. |
| `scripts/install.py` | Cross-platform installer with a dry-run plan and conflict detection. |
| `scripts/verify_install.py` | Checks an installed layout and can smoke-test the hooks. |
| `scripts/uninstall.py` | Removes what the installer added, keeps your content. |
| `tests/` | Non-destructive tests for all of the above. |

## Why this shape

One strong model doing everything in one context accumulates logs and traces,
spends frontier-model tokens on mechanical edits, and then reviews its own work.
This workflow splits the job:

- the root holds scope, contracts, architecture judgement, and acceptance;
- the worker holds execution inside a bounded contract;
- `.codex/PROJECT_STATE.md` holds the durable memory, so a fresh chat starts
  oriented instead of replaying history.

The cost discipline is explicit: one scope pass, one dispatch phase, completion waits, one
batched review, at most one correction cycle, one final answer.

## Install in two minutes

```bash
python scripts/install.py --project /path/to/your/repo --codex-home ~/.codex
```

Then add hooks if you want the state file injected automatically:

```bash
python scripts/install.py --project /path/to/your/repo --codex-home ~/.codex --hooks
```

Full details, including every flag and exactly what is written where:
[INSTALL.md](INSTALL.md). First dispatch walkthrough: [QUICKSTART.md](QUICKSTART.md).

The installer:

- plans every write and prints the plan before it happens;
- never overwrites a differing file without `--force`, and backs up what it
  replaces;
- never overwrites `PROJECT_STATE.md` or `AGENTS.md`, ever;
- never edits `config.toml`, credentials, or routing;
- never touches the network.

## The short version

```text
GPT-6.1 Sol: scope, frozen contracts, choose 1–3 streams
  ├─ one worker: discover → implement → test → report
  └─ 2–3 isolated workers → DeepSeek integrator → combined verification
Sol: one batched acceptance review → at most one correction phase
Sol: update .codex/PROJECT_STATE.md → final response
```

| Choice | When it earns its overhead |
| --- | --- |
| Direct (0 workers) | A tiny local change |
| Single (1 worker, default) | One coherent stream, shared files, or unresolved interfaces |
| Parallel (2 workers) | Two independent streams with disjoint ownership |
| Parallel (3 workers) | Three independent streams and a clear time benefit after integration |

Parallelism can shorten elapsed time. It adds DeepSeek requests and integration
work, so it does not guarantee a lower total bill. The resource saving mechanism
is that discovery, coding, debugging, and routine verification move out of the
root's subscription context. Each user pays for their own routed DeepSeek usage.

The root waits for completion, reviews the integrated result once, and keeps
final architecture/security judgement. Workers and integrators do not delegate
or edit persistent state. Local commits need explicit permission in an isolated
task branch; remote writes need separate user authorization.

## Enable adaptive work (optional)

```bash
python scripts/install.py --project /path/to/your/repo --codex-home ~/.codex --adaptive --hooks
python scripts/verify_install.py --project /path/to/your/repo --codex-home ~/.codex --adaptive --self-test
```

`--adaptive` additionally installs `deepseek_integrator`. It does not launch
agents or create worktrees. Old install commands still install `deepseek_worker`
and keep the single-worker path. The existing worker can also handle an explicitly
briefed `ROLE=integrator` for legacy setups. See [INSTALL.md](INSTALL.md) for
upgrades and [the worktree protocol](skill/references/WORKTREE_PROTOCOL.md).

## Requirements

- Codex with custom subagent support (`.codex/agents/*.toml`).
- Python 3.9 or newer for the installer, verifier, and hooks. Standard library
  only; nothing to pip install.
- A router or provider setup that exposes a DeepSeek V4.1 Flash model id to
  Codex (for example the Codex Router). Verify the exact slug against your own
  model picker; the bundled value is a starting point, not a guarantee.
- Git for worktree isolation/local integration and the `Stop` hook. The installer and single-worker policy can be used without Git.

## Router configuration

`templates/codex.config.example.toml` shows the shape of a routed provider
block, with placeholders instead of a real caller capability URL. It is
illustrative. Your router's own README is the authoritative source for
version-specific steps.

Each user supplies their own DeepSeek API key, or their own credentials for a
different provider that exposes the DeepSeek route. This repository does not
provide a shared key or model access.

Two rules that matter more than the syntax:

1. Never commit a real router capability URL, router key, or provider API key.
2. Never silently substitute another paid model when the DeepSeek route is
   unavailable. Report the routing problem instead.

## Tests

```bash
python -m unittest discover -s tests -v
```

The suite creates throwaway directories and a throwaway git repository, and it
never touches a real Codex home or the network.

## Safety

Read [SECURITY.md](SECURITY.md) before installing hooks. In short: hooks run as
local processes with your permissions, project hooks load only after you trust
the project `.codex` layer, and hook output is sent to the model, so nothing
secret belongs in `PROJECT_STATE.md` or in hook output.

## Limits, stated plainly

- This repository ships no model access, no API keys, and no paid setup. It
  configures a workflow; your router and subscription provide the models.
- The bundled DeepSeek model slug is router-supplied and may differ in your
  environment.
- The installer cannot verify that a worker actually ran on DeepSeek. The root
  sees a report, not provider billing.
- Nothing here publishes, pushes, or deploys on your behalf.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Changes to the workflow itself should
update `ARCHITECTURE.md` and `skill/SKILL.md` together, so the explanation and
the operational instructions cannot drift apart.

## License

MIT. See [LICENSE](LICENSE).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
