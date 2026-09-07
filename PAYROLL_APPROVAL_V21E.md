# Payroll Approval V2.1E

## Boundary and flow

V2.1E adds an explicit human decision over immutable validation evidence:

```text
current immutable review snapshot
  -> exact completed validation run and ruleset
  -> acknowledge every WARNING, if any
  -> APPROVED or REJECTED human decision
  -> immutable historical evidence
```

Approval is evidence and a terminal human decision only. Approval is not a
`PayrollVersion`, payroll materialization, or publication. It does not create
or modify payrolls, earnings, deductions, absences, tax calculation runs, or
tax cumulative records.

## Warning acknowledgement

Only a `WARNING` result belonging to the exact validation run may be
acknowledged. The authenticated server-side user is recorded as the actor.
Acknowledgements are append-only and cannot be updated or deleted.

A warning acknowledgement is not an `ERROR` or `BLOCKING` waiver. `INFO`,
`ERROR`, and `BLOCKING` results cannot be acknowledged. Every warning must be
acknowledged before an approval can be recorded.

## Approval and rejection

Approval requires a `COMPLETED` validation run whose persisted results contain
no `ERROR` or `BLOCKING` findings. The service recomputes the validation result
checksum and counts from stored results and binds the decision to the exact:

- organization and payroll import;
- review snapshot ID and checksum;
- validation run ID and result checksum;
- validation ruleset version;
- sorted acknowledged-warning result IDs;
- decision and optional note/rejection reason.

Rejection is permitted for any exact, completed validation run, including a
`NOT_READY` run, and requires a non-blank reason. One validation run can have
only one terminal decision. An `APPROVED` decision cannot later become
`REJECTED`, and a `REJECTED` decision cannot later become `APPROVED`.

The approval checksum is SHA-256 over canonical JSON. Evidence fields are
sorted deterministically and timestamps are excluded.

## Historical and current state

Decisions and acknowledgements remain available as immutable history. A
historical approval counts as current only when it belongs to the current
review snapshot and the latest relevant validation run/ruleset for that exact
snapshot.

Old approvals do not apply automatically to newer snapshots. Old approvals do
not apply automatically to newer rulesets. Either change returns the effective
state to `NOT_DECIDED` until a new explicit human decision is recorded.

## Access and API

`PAYROLL_ADMIN` may acknowledge warnings, approve, reject, and read.
`HR_ADMIN` and `AUDITOR` are read-only. `EMPLOYEE` is denied, and
`SYSTEM_ADMIN` receives no implicit access. All lookups are organization-scoped
and actors are derived from authentication rather than request data.

- `GET /api/v1/payroll-imports/{id}/approval`
- `GET /api/v1/payroll-imports/{id}/approvals`
- `POST /api/v1/payroll-imports/{id}/validations/{run_id}/warnings/{result_id}/acknowledge`
- `POST /api/v1/payroll-imports/{id}/validations/{run_id}/approve`
- `POST /api/v1/payroll-imports/{id}/validations/{run_id}/reject`

Database foreign keys bind organization, import, snapshot, run, and result
scope. Unique constraints and row locking prevent competing terminal decisions.
Database triggers reject update or deletion of acknowledgements and decisions
and enforce exact warning and approval evidence on insert.
