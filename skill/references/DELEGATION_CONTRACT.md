# DeepSeek Delegation Contract Template

Copy this template into the worker dispatch and fill every section. Keep it one coherent bundle.

```text
GOAL
<one outcome>

WHY
<user/product intent if relevant>

SCOPE
- ...

NON-GOALS
- ...

CONSTRAINTS / CONTRACTS
- ...

ACCEPTANCE CRITERIA
- ...

KNOWN RELEVANT PATHS
- ...

VERIFICATION
- run the relevant tests/build/lint/typecheck
- diagnose and fix ordinary in-scope failures before reporting

RETURN FORMAT
- STATUS: ready_for_review | blocked | failed
- SUMMARY: concise
- CHANGED: paths + behavior
- VERIFICATION: command + outcome
- RISKS/BLOCKERS: only unresolved items
- ROOT/USER DECISIONS: only if genuinely required
```

Rules for the dispatch:

- Do not send progress updates. The root waits once.
- The worker owns repository discovery, implementation, testing, debugging, and routine verification inside the stated scope.
- The worker does not spawn nested agents, commit, push, deploy, or expand scope without authorization.
- The worker must not claim a command ran when it did not. Report the real exit status.
- If the bundle is under-specified, the worker reports a blocker instead of redesigning the system.

## A concrete example

```text
GOAL
Add CSV export to the report page and cover it with a test.

WHY
Users currently copy numbers out of the table by hand; support asks for a file download.

SCOPE
- server route that streams the current report as CSV
- download control on the report page
- one test for the route

NON-GOALS
- no new export formats
- no changes to the report query
- no styling work beyond the single control

CONSTRAINTS / CONTRACTS
- the existing report JSON shape must not change
- reuse the existing auth middleware

ACCEPTANCE CRITERIA
- GET /reports/:id/export.csv returns text/csv with a header row and one row per record
- unauthenticated requests keep returning 401
- the page control triggers a download with the current filter applied

KNOWN RELEVANT PATHS
- src/reports/routes.ts
- src/reports/ReportPage.tsx

VERIFICATION
- run the repository's test and lint commands for the touched packages
- fix ordinary in-scope failures before reporting

RETURN FORMAT
- STATUS / SUMMARY / CHANGED / VERIFICATION / RISKS / DECISIONS
```
