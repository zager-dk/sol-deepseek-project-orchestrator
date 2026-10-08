# Quickstart

The workflow is manually directed. Codex launches agents; the installed Python ledger records transitions and checks declarations. It is not a daemon, scheduler, or automatic dispatcher.

**Readiness:** the ordinary local pilot confirmed discovery and invocation through the native custom-role route. The root requested `gpt-6.1-sol` at high effort with `service_tier = "default"`; the human selected Standard with Fast off. Child roles had no tier override, so inheritance was expected. Actual model, effort, and tier telemetry was unavailable, so runtime selections are not independently confirmed. Actor IDs and fresh-context/stop declarations remain manual attestations, not authentication.

## 1. Open the project in the Codex app

For a temporary project-scoped pilot, make the skill and child roles available in the project layout:

```text
<project>/.agents/skills/sol-deepseek-project-orchestrator/SKILL.md
<project>/.codex/agents/
    luna-worker.toml
    luna-reviewer.toml
    luna-state-editor.toml
    sol-senior.toml
    sol-reviewer.toml
    astra-consultant.toml
```

The project-local layout above is manual preparation for a temporary desktop pilot; the installer does not provision it. The installer targets `<CODEX_HOME>/agents/` and places the skill under `<CODEX_HOME>/skills/sol-deepseek-project-orchestrator/`. For the app pilot, copy the skill from `skill/` and six role files from `templates/agents/` into the project paths above, then open that project in the Codex app. The Codex app supports project-scoped custom agents; this does not imply installer support or automatic selection of a named profile.

Open the project folder in the Codex app, choose **Codex**, and start a new chat. Use the project orchestrator skill in the primary session. The primary session is the Sol 6.1 technical director; it plans, delegates, resolves interfaces, integrates, and accepts work, but does not implement. The director default is Sol 6.1 high; request xhigh for a complex initial plan, architecture, or contradictions only if supported by the app controls, recording why in the task. For other roles, use the task-specific effort guidance in the skill. A TOML default or instruction does not prove that runtime effort changed. Select or verify the director model using the app's supported controls. The templates carry `service_tier = "standard"`, but the installed Codex TOML contract has not confirmed that literal; API response `default` is not established as an interchangeable config value. In the isolated desktop pilot, verify config loading and Standard selection/dispatch. If Standard cannot be confirmed, report the blocker and do not silently switch to Fast.

The app's subagent activity is the place to inspect the live delegated roles. A successful TOML parse or ledger entry alone does not prove that an agent was discovered or dispatched with the requested model and tier. Child roles do not delegate nested work.

### Optional: Codex CLI profile

The installer places the root profile at `<CODEX_HOME>/orchestrator-director.config.toml`; this is an optional CLI route. Set `CODEX_HOME` and run `codex --profile orchestrator-director` from the project directory. This starts a CLI session; it does not select the same profile in the Codex app. For that separate installer route, `verify_install.py` needs Python 3.11+ for strict TOML parsing (`tomllib`); the installer/runtime do not. Python 3.12.14 was available in this environment. When installation intentionally used `--no-agent`, run `verify_install.py` with `--no-agent` too; that permits absent roles but does not skip verification of any role files that are present.

## 2. Initialize the state and backlog

The bundled Python ledger is separate from the Codex CLI and does not launch agents. From this source checkout, run `python scripts/orchestrate.py`; it accepts `--project` to select the repository. The installed runtime is `<CODEX_HOME>/skills/sol-deepseek-project-orchestrator/scripts/orchestrate.py`; from a source checkout, use `python scripts/orchestrate.py`:

```bash
python scripts/orchestrate.py --project /tmp/demo-project init --max-workers 3 --review-round-limit 2 --consultation-limit 1 --escalation-limit 1
python scripts/orchestrate.py --project /tmp/demo-project snapshot --json
```

`max-workers` counts ledger reservations; Codex's child-thread cap is separate. Neither is a concurrency target. Edit `.codex/PROJECT_STATE.md` with current project facts, hypotheses, plans, blockers, and verification baseline, without secrets or chat history.

### Optional ledger directory

Unconfigured projects keep the ledger under `.codex`. To select another ordinary directory within the Git project, bind it explicitly once before initializing:

```bash
python scripts/orchestrate.py --project /tmp/demo-project bind-storage --data-dir .orchestrator-data
python scripts/orchestrate.py --project /tmp/demo-project --data-dir .orchestrator-data init
```

Binding creates the protected `.codex/ORCHESTRATOR_STORAGE.json` selector. It does not migrate or adopt a ledger; it refuses an existing legacy ledger, an existing ledger in the selected directory, and paths outside the project, inside Git metadata, or inside protected `.codex` configuration. Existing path components and files must not be symlinks, junctions, or reparse points. After binding, omit `--data-dir` or pass the same path; a conflicting path or missing/invalid selector fails closed. Only the ledger, lock, and exact `ORCHESTRATOR.tmp` bookkeeping move. `PROJECT_STATE.md` and role/config files stay under `.codex`. Treat selector creation as one-time protected project configuration setup; normal ledger mutations write in the selected ordinary directory. The installer can embed the same selection in both hooks with `--data-dir`, but does not create the selector or selected directory.

## 3. Add a task and independently review its plan

Write the task contract before dispatch. For significant or higher-risk work, have an independent Luna reviewer derive scenarios from the proposed contract in a fresh review context before assignment:

```bash
python scripts/orchestrate.py --project /tmp/demo-project add T-101 --goal "Add CSV export" --depends-on "" --priority 50 --risk medium --scope "src/reports/routes.ts,src/reports/Page.tsx" --acceptance "CSV has a header and one row per record; unauthenticated requests return 401" --actor director
python scripts/orchestrate.py --project /tmp/demo-project plan-review T-101 --actor director --director director --reviewer luna-reviewer-1 --contract-version v1 --scenario "Check header/row order, empty output, filters, CSV escaping, and unchanged JSON behavior" --fresh-context-attested --context-item contract --context-item diff --context-item relevant-code --context-item verification-results
```

For this preimplementation review, provide the current baseline diff (including “no task changes yet” if applicable), relevant code, and baseline verification results along with the contract; the CLI requires all four context labels. The plan review is a manual declaration. Actor IDs and `--fresh-context-attested` do not authenticate identity, prove context isolation, or establish that a process stopped. The director records the plan review; the separate reviewer identity is recorded with `--reviewer`. A current acceptance planner cannot become the worker or recovery owner. Resolve an inconclusive result or contract issue with the director before assignment. For a deliberately low-risk task, the CLI supports `--review-mode manual-control`; document why independent plan review was omitted.

## 4. Assign and start the worker

Confirm dependencies are complete and scopes do not conflict, then assign and start one owner. The primary Sol director sends the worker the agreed goal, scope, acceptance checks, relevant state, and any reproduction. Dispatch is a separate native Codex action; these ledger commands do not launch agents.

```bash
python scripts/orchestrate.py --project /tmp/demo-project assign T-101 --owner luna-worker-1 --actor director
python scripts/orchestrate.py --project /tmp/demo-project start T-101 --actor luna-worker-1
```

Use `luna_worker` for bounded implementation. Escalate justified complex work to `sol_senior` only with the existing diff, reproduction, prior attempts, and explicit bounded contract. The director plans, delegates, settles interfaces, and integrates; it does not implement. Child roles do not create more directors or delegate nested work.

## 5. Submit, review the integrated snapshot, integrate, and complete

When the worker reports, submit the task. A fresh independent Luna reviewer checks the original contract, plan scenarios, exact diff, relevant code, and actual verification evidence. Supply the evidence for checks actually run; record other checks as unrun. For high or critical risk, add a separate `sol_reviewer` high-risk review (or a bounded Astra consultation plus director resolution as appropriate). Record Sol evidence with `--senior-verified --senior-reviewer sol-reviewer-1 --senior-role sol_reviewer` on both the `review` and `integrate` commands; the flags record a manual attestation only.

```bash
python scripts/orchestrate.py --project /tmp/demo-project submit T-101 --actor luna-worker-1
python scripts/orchestrate.py --project /tmp/demo-project review T-101 --reviewer luna-reviewer-2 --result pass --check "PASS; command=python -m unittest tests.test_reports; result=exit 0; evidence=CSV and auth cases passed" --unrun "full browser suite" --findings "Plan scenarios checked on the integrated diff" --fresh-context-attested --context-item contract --context-item diff --context-item relevant-code --context-item verification-results
python scripts/orchestrate.py --project /tmp/demo-project integrate T-101 --actor director --check "PASS; command=python -m unittest tests.test_reports; result=exit 0; evidence=integrated snapshot verified"
python scripts/orchestrate.py --project /tmp/demo-project complete T-101 --actor director --check "PASS; command=python scripts/orchestrate.py --project /tmp/demo-project snapshot --json; result=exit 0; evidence=completed task and current fingerprint recorded"
```

Use new reviewer context for acceptance; a new actor ID alone does not create fresh context or prove reviewer independence. The CLI stores attestations; it does not authenticate people or roles, verify context freshness, run checks, or guarantee a process has stopped. A reviewer `fail` returns the work for correction; `inconclusive` blocks until the director resolves the uncertainty. Earlier `pass` evidence is retained as history, but it is current only for its contract revision, attempt, owner history, and reviewed snapshot. Contract changes, recovery/reassignment, or tree changes require a new independent passing review before integration/completion; the CLI checks that evidence and reviewer independence at both gates. A task is complete only after integrated evidence is recorded. Dependents unlock only then.

## 6. Replan or recover safely

For an inconclusive result, the director records the resolution and any changed goal, scope, or acceptance criteria. Then repeat the plan review against the new contract. Do not erase the old diff or imply it passed:

```bash
python scripts/orchestrate.py --project /tmp/demo-project replan T-101 --actor director --director director --reason "Resolved the scope question and narrowed acceptance" --goal "Updated observable outcome" --scope "src/reports/routes.ts" --acceptance "Updated testable result and error cases"
```

On interruption, preserve and inspect the diff, confirm the prior owner has stopped, then record interruption and recover with the current state. The stop declaration is not process control or proof of termination. Assign a new, unoccupied owner ID:

```bash
python scripts/orchestrate.py --project /tmp/demo-project interrupt T-101 --actor luna-worker-1
python scripts/orchestrate.py --project /tmp/demo-project recover T-101 --owner sol-senior-1 --actor director --context "Preserved diff; reproduction and prior attempts attached; old owner confirmed stopped" --old-agent-interrupted
```

A recovered task keeps its changes and history. The planner for the current contract cannot be selected as the recovery owner; choose another unused identity. Continue with that owner using the normal `start` and `submit` steps. Recovery changes owner history, so any previous passing review is historical: obtain a fresh independent acceptance review on the integrated current diff before retrying integration/completion.

Escalate to `sol_senior` only after the configured Luna review/correction allowance is exhausted. The prior active owner must have stopped; `--old-agent-interrupted` is a required declaration, not proof of process termination. The new owner ID must differ from the prior owner, every prior task author, and the current acceptance planner. A rejected escalation leaves the ledger unchanged. Example syntax from the current runtime contract:

```bash
python scripts/orchestrate.py --project /tmp/demo-project escalate T-101 --actor director --director director --owner sol-senior-2 --owner-role sol_senior --reason "Luna correction rounds exhausted" --context "reproduction=...; prior attempts=...; current diff preserved" --old-agent-interrupted
```

Use a separate read-only Sol reviewer for elevated acceptance of high-risk work. Astra remains a rare bounded consultation when its advice could change the decision. Do not assign complex work to Sol senior preemptively.

## 7. Keep state current

Ask `luna_state_editor` to update only the named state sections from explicit director instructions. Review its diff, verify each claim, and refresh the `state_fingerprint` marker from `snapshot --json`. State is durable project context, not a transcript.

For two competing hypotheses, define a shared question, bounded budget, separate approaches, and a stop condition. Run them as manually managed independent investigations. This is not a daemon or auto-dispatch loop. See [ARCHITECTURE.md](ARCHITECTURE.md) and `skill/references/` for detailed contracts and limits.
