# Historical acceptance record: 2026-10-08

Preserved from the pre-upgrade uncommitted delivery report. Machine-specific paths are redacted; local project state and installer ownership data remain in a local recovery backup. This records historical validation and limitations. Its model-mode restrictions are superseded by v0.2.0 and later; they are not current instructions.

# Final independent acceptance — 2026-10-08

## Outcome

**Code acceptance: PASS.** **Autonomous native Standard dispatch: BLOCKED in the inspected desktop delegated-task route.** This is a code prototype with verified ledger, installer, verifier, and hook behavior; it is not fully operational as an autonomous native Standard-dispatch system. The block applies to the inspected route, not every Codex desktop chat.

The inspected delegated `spawn_agent` interface exposed only a priority field, without a service-tier or role selector. The skill was read from disk rather than discovered in `skills.list`, and loading the six role TOMLs into child dispatch was not demonstrated. The desktop inspection surface exposed no apps or browsers, so UI inspection was unavailable. No dispatch or billing claim is inferred from TOML parsing or local tests.

## Verification and evidence

- Full suite: **exit 0; 134 tests, 130 passed, 4 platform skips**. Existing Python 3.12.14 was used; no dependencies were installed. Evidence: <local evidence path redacted> and `verifier_final_suite.py` in the same evidence directory.
- Independent verifier/runtime closure: **PASS**, `python -B verifier_independent_closure.py`, exit 0; evidence: <local evidence path redacted>.
- Accepted source HEAD for that review: `a67b2fc511baa7b290b7b94eb2eb831036492f46`.
- Runtime SHA256: `58b8d1873bb7f3e4698142258fc370d627e973a4c8731f78d1bb31b042aa99d3`.
- Verifier SHA256: `3f293e61856a1156bb1e7bc1b2219abd387d6a1e0ee2a996f4b47cf7b18fc658`.
- Stop hook SHA256: `e312fcf3bf2f9625a734dd303610173074724abfd51f51266facab5a8a323ac4`.
- Hook regression test SHA256: `922547adce31c226849cd66f9ca33273fccce98a1d31864ed46f9b07b6f12fda`.
- Source manifest: `accepted_source_manifest.json`, 40-file manifest SHA256 `09465c25b405e7c21c0fc2195959dc685e5f55caf873a329e6371d33d9de4e22`.
- Source snapshot evidence: `accepted_source_snapshot.json`; task fingerprint `61ecdbcbfd4cc91fb30c22da2235078d2dccec0c19b8bdba187249e2985a34b6`; state fingerprint `1c1cfe4d465f9ac806f86de42ab449bc23f185d9b706185a027b574b1cc89ecd`.

The closed verifier findings included strict `tomllib` parsing (malformed and dangerous TOML is rejected), ownership-independent validation of every present child role, explicit `verify_install.py --no-agent` for intentionally absent roles, and fail-closed handling of malformed encoding/read errors. Tier/profile tampering and disabled director delegation are rejected by verifier checks. These checks validate configuration and local code behavior, not live service-tier dispatch.

## Roles and effort policy

Defaults: primary Sol 6.1 director high; Luna worker medium; Luna reviewer high; Luna state editor low; Sol senior high; read-only Sol reviewer high; Astra consultant high. Approved task-specific effort guidance: director xhigh for complex initial planning, architecture, or contradictions; worker high for nontrivial logic and low only for exact mechanical edits; Sol senior xhigh for a complex reproducible bug; Sol reviewer xhigh for concurrency, data-loss risk, or complex interactions; state editor medium to reconcile reports; Astra xhigh only for an especially complex architecture decision. Record the reason in the task and apply a change only through supported launch controls. These are configuration/instruction defaults, not proof that runtime effort can be changed or was used. Preserve Luna-first routing.

## Enforced and procedural boundaries

The local ledger and tests enforce bounded task transitions, dependency readiness, owner/scope conflicts, review and escalation gates, current-snapshot checks, recovery ownership rules, and verifier configuration contracts. The verifier requires Python 3.11+ for stdlib `tomllib`; that is a verifier-only requirement. Python 3.12.14 was already present and used for verification.

Actor IDs, role labels, fresh-context attestations, and stopped-owner declarations remain procedural bookkeeping; they do not authenticate identity, prove context isolation, or stop a process. The ledger does not launch agents, run recorded task checks, or prove billing/dispatch. Two-hypothesis investigations remain manually managed, not a daemon. `service_tier` strings accepted by the TOML parser are not semantically validated; Standard dispatch remains unverified and blocks this live pilot route.

No live/global installation, Codex CLI/model call, dependency installation, commit, push, or PR was performed. The global Codex configuration was left unchanged.

## Post-suite documentation follow-up

After the accepted code snapshot, documentation-only clarifications were made to INSTALL, QUICKSTART, and TROUBLESHOOTING. They explain verifier Python support and `--no-agent` verification semantics. No code or runtime files changed in this follow-up; the shared full suite was not rerun. `git --no-optional-locks diff --check` passed. Current follow-up document SHA256: INSTALL `C9A67745CAB74A2B9AADF5EFCF14DE8A43D0036D08FDC0C0FCCAA9096AAD0FCF`; QUICKSTART `509F30DCBA416D82192B75F8A0478542929E6973410C384AB0A7930A8E6184E1`; TROUBLESHOOTING `F38D2D8B129DC7E484900CB53509CD1875B0C7830F249DD5F91D2767AF44D605`.
