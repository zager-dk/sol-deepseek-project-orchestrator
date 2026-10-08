# Example backlog task and review plan

The primary director creates this contract and an independent reviewer prepares scenarios before the Luna worker starts. Reviewer IDs and fresh-context declarations in the ledger are not authenticated. It is a worked example, not a claim about a particular repository's routes.

```text
TASK ID
RPT-CSV-01

GOAL
Add a CSV download for the currently selected report.

DEPENDENCIES
None.

PRIORITY / RISK
50 / medium.

SCOPE
- report export route
- report page download control
- focused route and UI tests
- exclusive ownership of the files named by the director

CONTRACTS AND CONSTRAINTS
- reuse existing report query and authentication middleware
- do not change the public report JSON shape
- CSV column order follows the visible table
- no other export format or unrelated styling

ACCEPTANCE CRITERIA
- successful request returns `text/csv` with a header and one row per record
- empty report still returns the header
- unauthenticated request remains 401
- the download uses the current report filter

CONTEXT
The current report table already exposes the filtered rows. The director will provide the relevant component/route paths and existing verification command after checking project state.

VERIFICATION
Run the focused route and UI tests. Report exact commands, exit status, and results. Identify failed and unrun checks separately.
```

## Reviewer scenarios prepared before implementation

1. A report with multiple rows produces the expected header, column order, and values.
2. An empty report returns a header-only CSV.
3. A request without authentication returns 401.
4. Changing a filter changes the downloaded rows to match the visible report.
5. Existing report JSON consumers retain their previous response shape.
6. CSV fields containing commas, quotes, and newlines are escaped correctly.

A fresh independent reviewer then inspects the exact diff, surrounding query/auth code, and observed results. Fresh-context and stopped-owner fields are declarations; they do not establish identity, context isolation, or process control. It returns `pass`, `fail`, or `inconclusive` with evidence and does not edit the implementation. An unrun scenario remains unverified. The director integrates and checks the combined snapshot before closing the task or unlocking a dependent item.
