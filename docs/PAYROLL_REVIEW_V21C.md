# Payroll Review V2.1C

## Boundary

```text
General Reader machine extraction
    -> generic PayrollImportField staging
    -> replaceable adapter mapping
    -> reviewer-owned correction revisions
    -> deterministic effective review values
    -> immutable reviewed snapshot
    -> future deterministic validation (not implemented here)
```

A review snapshot is not a `PayrollVersion`, payroll approval, publication, or
tax/financial validation. V2.1C creates no payroll, earning, deduction,
absence, tax-run, or cumulative-tax record and invokes no tax service.

Corrections are document-local evidence. They neither modify General Reader nor
create `SYSTEM`, `ORGANIZATION`, or `TEMPLATE` mapping rules.

## Review lifecycle and ownership

`PayrollImportReview` is unique per import and is separate from extraction
`PayrollImport.status`. `POST /review` explicitly starts it. Its states are
`IN_PROGRESS`, `READY_FOR_SNAPSHOT`, and `SNAPSHOTTED`; none means approved or
materialized. The row records the starting and last human reviewer, timestamps,
the current snapshot, the current adapter-output checksum, and a positive
optimistic `row_version`.

PAYROLL_ADMIN and HR_ADMIN may start, correct, revert, finalize, and read.
AUDITOR is read-only. EMPLOYEE and SYSTEM_ADMIN have no import-review access.
All persistence lookups use the authenticated organization and cross-tenant IDs
remain non-disclosing 404s. Organization and reviewer IDs are server-derived.

## Correction revisions and effective values

`PayrollImportFieldCorrection` is an append-only revision stream per
review/source observation. Every `APPLY` or `REVERT` row points to the revision
it supersedes; old rows are never deleted. It records the reviewer, timestamp,
required reason, original adapter status/key/type/value, corrected typed value,
source/mapped identities, and the adapter fingerprint it corrected.

A correction is bound by composite foreign key to a real organization/import
source observation. V2.1C has no manual assertions from nothing. Canonical
overrides must exist in Bordro's registry and use the registry's type and
section. Generic unmapped fields may instead retain a null canonical key and a
deterministically recognized source type. All values use the existing strict
parser; decimals and day counts remain exact `Decimal`/`NUMERIC(18,2)` values.

The single resolver applies this precedence:

1. Latest `APPLY` correction, only when its fingerprint still equals current
   source/adapter context: provenance `REVIEWER_CORRECTION`.
2. Current structurally valid adapter result: provenance `ADAPTER`.
3. Latest `REVERT`: explicitly selects rule 2 while retaining all history.

An incompatible correction is `STALE`, is never applied, and blocks a new
snapshot. Adapter reruns replace only adapter-owned rows. Identical reruns keep
the review version; changed output updates the review checksum, reopens the
review, and increments its version. The fingerprint is SHA-256 over the stable
source identity/content/status plus canonical key, mapping identity/version,
type, mapping/parse/review status, candidates, reason codes, and typed adapter
value. Replaceable mapped-row IDs and sensitive plaintext logs are excluded.

Every correction/revert request supplies `expected_review_version`. The service
locks the review row and compares it before writing. A mismatch returns 409
`REVIEW_VERSION_CONFLICT`; successful human changes increment exactly once.

## Structural completeness

Snapshot finalization is an explicit reviewer action. It is blocked by:

- unresolved `AMBIGUOUS` or `PARSE_FAILED` adapter output;
- a source or mapped field explicitly marked `REVIEW_REQUIRED` or `MISSING`;
- a stale correction;
- a missing/empty generic observation requiring review;
- any required canonical registry concept absent from effective resolved data;
- duplicate effective canonical concepts; or
- any correction that fails controlled-key or typed parsing checks.

An ordinary, non-required, unmapped scalar with a valid unflagged source value
does not block finalization. It is retained as a generic text field with a null
canonical key. V2.1C performs no totals, tax-base, net-pay, days, or other
payroll-law reconciliation.

## Immutable snapshots and checksums

`PayrollImportReviewSnapshot` versions are positive and unique per review.
Children copy source label/text/raw value, page/bbox/confidence/extraction
metadata, original mapping status, effective key/section/type/exact value,
provenance, correction reference, and adapter fingerprint. Future validation
can read a tenant-scoped snapshot and its fields without joining mutable source,
adapter, or correction tables. No filesystem path is stored.

PostgreSQL `BEFORE UPDATE OR DELETE` triggers reject mutation of snapshot
headers and children. There is no update/delete review API. A later correction
reopens the review and produces version N+1; prior versions remain unchanged.

Four SHA-256 values are stored:

- staging: all source observations sorted by source UUID;
- adapter: stable adapter payloads sorted by source UUID;
- corrections: all revision evidence sorted by source UUID, revision, and ID;
- snapshot: effective snapshot-field payloads sorted by source UUID.

Canonical serialization is UTF-8 JSON with sorted object keys, compact
separators, Unicode preserved, dates in ISO form, enums as values, UUIDs as
strings, and every `Decimal` serialized with `format(value, "f")`. Snapshot and
child IDs and creation timestamps are excluded from the content checksum;
replaceable mapped-row IDs and correction revision IDs are also excluded.
Source identity/content, effective key/type/value, original mapping state,
provenance, and adapter fingerprint are included. Re-finalizing identical
effective content returns the existing snapshot instead of creating a duplicate.

## API

| Method | Route | Writers | Auditor |
|---|---|---:|---:|
| POST | `/api/v1/payroll-imports/{id}/review` | start/idempotent read | denied |
| GET | `/api/v1/payroll-imports/{id}/review` | read | read |
| POST | `/api/v1/payroll-imports/{id}/review/fields/{mapped_id}` | correct | denied |
| POST | `/api/v1/payroll-imports/{id}/review/fields/{mapped_id}/revert` | revert | denied |
| POST | `/api/v1/payroll-imports/{id}/review/finalize` | snapshot | denied |
| GET | `/api/v1/payroll-imports/{id}/review/snapshots` | read | read |
| GET | `/api/v1/payroll-imports/{id}/review/snapshots/{snapshot_id}` | read | read |

Correction input contains only expected version, optional canonical key, value,
and reason. Responses expose source, adapter, correction history, effective
value/provenance, and human review state. Decimal values are strings.

Future `AuditEvent` work should additionally record review start, correction,
revert, stale detection, finalize/idempotent-finalize, and snapshot-read events
with actor, tenant, request correlation, and snapshot/checksum references. The
correction rows already provide durable who/when/what/why evidence.
