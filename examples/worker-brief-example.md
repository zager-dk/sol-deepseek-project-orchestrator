# Worker Brief Example

A filled brief for a small but realistic bundle, with notes explaining why each
section is written the way it is. Copy the structure, not the content.

```text
GOAL
Add CSV export to the report page, with tests for the new route.

WHY
Support copies numbers out of the table by hand today. The user-visible outcome
is a working download that respects the current filter.

SCOPE
- server route that streams the current report as CSV
- download control on the report page
- tests for the route: happy path, empty result, unauthenticated request

NON-GOALS
- no new export formats
- no changes to the report query or its caching
- no styling work beyond the single control
- no changes to the public report JSON shape

CONSTRAINTS / CONTRACTS
- reuse the existing auth middleware; do not add a second auth path
- the CSV column order must follow the visible table order
- keep the existing streaming helper pattern used by other downloads in the repo

ACCEPTANCE CRITERIA
- GET /reports/:id/export.csv returns 200 with content-type text/csv
- the body has a header row and one row per record
- an empty result still returns the header row
- an unauthenticated request returns 401
- the download control applies the currently selected filter

KNOWN RELEVANT PATHS
- apps/web/src/reports/routes.ts
- apps/web/src/reports/ReportPage.tsx
Both are starting points, not the full surface: check for a shared download
helper before adding a new one.

VERIFICATION
- run the test and lint commands for apps/web
- run the new tests specifically and report their counts
- diagnose and fix ordinary in-scope failures before reporting

RETURN FORMAT
- STATUS: ready_for_review | blocked | failed
- SUMMARY: concise
- CHANGED: paths + behavior
- VERIFICATION: command + outcome for each command
- RISKS/BLOCKERS: only unresolved items
- ROOT/USER DECISIONS: only if genuinely required
```

## Why this brief works

**One outcome, not a checklist of edits.** The goal is a working download, so
the worker is free to discover the right place to put the route.

**Non-goals are explicit.** Changing the report JSON shape is the most tempting
adjacent refactor here, and the brief closes that door before it opens.

**Acceptance criteria are observable.** Every line can be checked by looking at
a response or a test result. None of them say "works well".

**Known paths come with a warning.** The brief points at two files to save time
and explicitly says they are starting points, which stops the worker from
treating them as the whole surface.

**Verification names commands, not outcomes.** The worker reports what ran and
what happened; it does not get to assert that things are fine.

## Anti-patterns

```text
# Too vague: no worker can satisfy this
GOAL
Improve the reporting page.

# Too small: this is a one-line edit the root should do directly
GOAL
Rename the variable `reportsData` to `reportRows`.

# Scope creep built in: three unrelated bundles in one dispatch
GOAL
Add CSV export, upgrade the router, and fix the login bug.

# Unfalsifiable acceptance
ACCEPTANCE CRITERIA
- export is fast
- the code is clean

# Verification without teeth
VERIFICATION
- make sure everything works
```

Each of these costs at least one extra round trip, and the vague ones often cost
two: one to discover the ambiguity, one to correct it.
