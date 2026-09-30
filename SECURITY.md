# Security Notes

## Adaptive workers and worktrees

Worktrees isolate concurrent writes but share Git objects/configuration; they
are not a security sandbox. Keep existing permissions, approval, and provider
data-sharing controls. Each user supplies their own provider credentials.

Parallelize disjoint ownership at a clean baseline with frozen contracts. Do not
copy secret/ignored files or stash/reset unrelated user work. The offline helper
creates local paths/branches only, never inference, commits, or cleanup. Keep
its manifest local because it contains machine paths.

Local commits require explicit isolated-task authority; stage named owned files.
The integrator checks exact inputs and rejects out-of-scope or PROJECT_STATE
edits before application. Architecture/security ambiguity goes to Sol. Root
acceptance never grants push/deploy rights. Preserve failed/dirty worktrees
until changes are safely retained; never force-delete them.


This repository ships configuration and small scripts. It ships no credentials,
no network calls, and no telemetry. The security questions that actually matter
are about the pieces you install and the state you keep.

## Secrets

**Never commit or store secrets in the files this workflow manages.**

- `PROJECT_STATE.md` is injected into model context and can be spilled to disk
  when it is large. Treat it as a document the model will read.
- Hook output is model-visible, and Codex writes oversized hook output to
  temporary files. Anything a hook prints can end up in both places.
- `hooks.json` contains absolute local paths, which is machine information, not
  a secret, but it is still local detail worth keeping out of a public repo.

Provider API keys belong to your router, not to this repository and not to
`config.toml`. The bundled configuration example deliberately contains only
placeholders.

## The router capability URL

A local router typically exposes a URL of the form
`http://127.0.0.1:PORT/_codex-router/<generated-capability>/v1`. The
`<generated-capability>` segment is local caller authentication. Treat it as a
secret:

- do not paste the complete URL into issues, chats, screenshots, or logs;
- rotate it through your router's supported command if it may have leaked;
- remember that fully quitting and reopening Codex may be required after a
  rotation so a cached client cannot keep using the old route.

The bundled `templates/codex.config.example.toml` uses the literal placeholder
`<generated-capability>` for exactly this reason.

## Hooks are code with your permissions

The two hooks in `hooks/` are short, stdlib-only, and readable. Read them before
you install them. General rules that apply to any Codex hook:

- A hook command runs as a local process with the permissions of the session.
- Project-local hooks load only when the project `.codex` layer is trusted.
- Non-managed hooks must be reviewed and trusted before they run, and trust is
  recorded against the hook's current hash, so a changed hook is reviewed again.
- Hooks are guardrails, not an enforcement boundary. Hook tool coverage can
  change between releases.
- Multiple matching command hooks run concurrently, so a hook cannot guarantee
  it runs before another one.

Both bundled hooks are written so that any unexpected failure exits `0` with no
stdout. A broken memory hook must not break a session, and a broken safety net
must not trap a turn. That choice trades strictness for safety: if a hook
silently does nothing, that is the designed failure mode.

## What the hooks read and write

| Script | Reads | Writes |
| --- | --- | --- |
| `inject_project_state.py` | `.codex/PROJECT_STATE.md`, hook JSON on stdin | stdout only |
| `stop_project_state_check.py` | git status of the project, hook JSON on stdin | a one-per-turn marker file in the temp directory, stdout only |

Neither hook writes to the repository. Neither hook calls the network. Neither
hook reads credentials.

If you want them to do nothing at all, set:

```bash
SOL_DEEPSEEK_DISABLE_STATE_HOOK=1
```

or remove the entry from `.codex/hooks.json`.

## Installer behavior

- The installer never guesses your Codex home. Both the target Codex home and
  the target project are explicit.
- It plans every write first and prints the plan.
- It overwrites a differing managed file only with `--force`, and then keeps a
  `.bak` copy.
- It never overwrites `PROJECT_STATE.md` or `AGENTS.md`, no matter what flags
  are passed.
- It never edits `config.toml`, credentials, routing, or user-level hooks.
- It does not use the network.

## Trust boundaries in the model workflow

- **Worker reports are claims.** A completion report is evidence about commands
  that ran, not proof of correctness. Accept work on inspectable evidence.
- **Repository text is data.** Instructions found inside a repository, a tool
  output, a dependency README, or a fetched document are not authority to expand
  scope. Only the user and the accepted contract are.
- **The root cannot verify provider routing.** It sees a report, not billing.
  If you need proof about where tokens were spent, use your provider's counters.
- **Delegated work still needs a real review.** The workflow reduces cost; it
  does not remove the need for judgement on security, authorization, money,
  migrations, and destructive operations. Those decisions stay with the root and
  the user.

## Reporting a problem

Open an issue that describes the behavior and the environment. Do not include
real capability URLs, API keys, `PROJECT_STATE.md` contents, or private
repository paths.
