# Payroll Import V2.1A

## Architecture and authority boundary

```text
Browser
  -> authenticated Bordro API
  -> Bordro DocumentStorage (authoritative source file)
  -> durable PostgreSQL PayrollImport
  -> explicit process request
  -> Bordro GeneralReaderClient (HMAC-signed HTTP)
  -> private General Reader Integration API
  -> validated ExtractionResultV1
  -> generic PayrollImportField staging
  -> EXTRACTED or REVIEW_REQUIRED
```

General Reader extraction is not authoritative payroll truth.
`PayrollImportField` rows preserve source observations for later review and
mapping. V2.1A creates no `PayrollVersion`, performs no payroll or tax
calculation, and contains no canonical payroll mapping or approval operation.

## Durable execution model

Upload and extraction are intentionally separate synchronous requests:

1. `POST /api/v1/payroll-imports` validates and atomically stores the file,
   then commits an `UPLOADED` import and document row.
2. `POST /api/v1/payroll-imports/{id}/process` locks the import, commits
   `PROCESSING`, invokes General Reader in-process, and commits the result.
3. A safe remote/storage/contract failure commits `FAILED` while retaining the
   Bordro-owned file. Calling `process` explicitly retries `FAILED` imports.

PostgreSQL state and local files survive application restart. There is no
claim that an in-flight Python call is durable and no background queue or fake
in-memory job state. A process terminated after committing `PROCESSING` can
leave that import for future operational recovery; automatic stale-processing
recovery is not part of V2.1A.

## State machine

```text
UPLOADED -> PROCESSING -> EXTRACTED
                      -> REVIEW_REQUIRED
                      -> FAILED -> PROCESSING

UPLOADED ---------> REJECTED
EXTRACTED --------> REJECTED
REVIEW_REQUIRED --> REJECTED
```

No approval state or transition is implemented.

## Storage and ingress validation

`DocumentStorage` defines `put`, `open`, `stat`, and `delete`.
`LocalDocumentStorage` stores development files below the ignored
`backend/runtime/payroll-documents` directory, outside frontend/static assets.
Production should configure a dedicated protected filesystem path with OS
access controls and backups.

The original filename is display metadata only. Storage keys are random UUID
paths, root-confined, and absent from public schemas. Writes stream through a
temporary file, calculate exact size and SHA-256, flush and `fsync`, then use an
atomic rename. Failed temporary writes are cleaned.

Bordro independently accepts only coherent PDF, JPEG/JPG, PNG, BMP, TIFF/TIF,
and WebP extension/MIME/magic combinations. Empty input and uploads above
`PAYROLL_DOCUMENT_MAX_UPLOAD_BYTES` (25 MiB by default) are rejected. General
Reader performs deeper parser/resource validation afterward.

## General Reader client

The client calls `POST /internal/v1/extractions` at
`GENERAL_READER_BASE_URL` and sends multipart part `file`. It implements the
General Reader `ad0433f` contract without importing General Reader code.

Required signed headers are `X-GR-Client-ID`, `X-GR-Timestamp`, `X-GR-Nonce`,
`X-GR-Tenant-Namespace`, `X-GR-Tenant-ID`, `X-GR-Content-SHA256`,
`X-GR-Allow-LLM`, `X-GR-API-Version`, and `X-GR-Signature`.

Canonical bytes are ASCII-escaped UTF-8 JSON with sorted keys, compact `,`/`:`
separators, integer timestamp, and exact fields `allow_llm`, `api_version`,
`client_id`, `content_sha256`, `method`, `nonce`, `path`, `tenant_id`,
`tenant_namespace`, and `timestamp`. The signature is `sha256=` plus lowercase
`HMAC-SHA256(secret, canonical_bytes)` hex.

Tenant namespace is fixed to `bordro-ai`; tenant ID is the authenticated
organization UUID. Neither is accepted from the browser. Nonces use
`secrets.token_urlsafe`. `GENERAL_READER_ALLOW_LLM` defaults false and has no
request override. Response JSON is validated through an explicit Bordro-owned
Pydantic `ExtractionResultV1` mirror, including schema, tenant, content hash,
request ID, and correlation ID.

## Generic staging and tables

Scalar `fields` and `missing_fields` become generic `PayrollImportField` rows.
Source IDs/labels/text, raw and normalized values, type, confidence, page,
bbox, coordinate space, extraction source, rule index, and missing reason are
preserved. No canonical key or mapping state exists.

Review status is honest:

- `MISSING`: missing contract observation
- `REVIEW_REQUIRED`: low confidence, source warning, or LLM-sourced observation
- `UNREVIEWED`: otherwise; never represented as verified

Generic table-row persistence is deliberately deferred. Table count is stored
and `TABLE_STAGING_DEFERRED` is added to the safe warning summary, so table
presence is never silently discarded.

## API and RBAC

| Method | Path | Roles | Result |
| --- | --- | --- | --- |
| POST | `/api/v1/payroll-imports` | PAYROLL_ADMIN, HR_ADMIN | Multipart upload; `201` durable `UPLOADED` import |
| GET | `/api/v1/payroll-imports` | PAYROLL_ADMIN, HR_ADMIN, AUDITOR | Organization-scoped list |
| GET | `/api/v1/payroll-imports/{id}` | PAYROLL_ADMIN, HR_ADMIN, AUDITOR | Organization-scoped detail |
| GET | `/api/v1/payroll-imports/{id}/fields` | PAYROLL_ADMIN, HR_ADMIN, AUDITOR | Generic staging fields |
| POST | `/api/v1/payroll-imports/{id}/process` | PAYROLL_ADMIN, HR_ADMIN | Process or retry failed import |

EMPLOYEE and SYSTEM_ADMIN receive no import access. Cross-organization IDs use
404-style non-disclosure. Organization ID always comes from the access token.

## Duplicate, idempotency, errors, and audit follow-up

Exact duplicates are unique by `(organization_id, full SHA-256)` and return
`409 DUPLICATE_DOCUMENT`, even under another filename. Identical bytes in
different organizations are isolated and allowed.

Persistent `Idempotency-Key` support is deferred because exact-file duplicate
protection covers this phase's single-document operation; no in-memory or
partially durable idempotency mechanism was introduced.

Domain errors expose stable codes without raw database, filesystem, HTTP,
contract, HMAC, or secret details. Logs contain safe IDs/state, not file
contents, signatures, shared secrets, or remote response bodies.

There is no durable audit-event domain yet. The next review/approval phase must
persist: import uploaded, processing/retry started, extraction completed,
extraction failed, review decision recorded, import rejected, approval
requested, and authoritative materialization performed.

## Configuration

```dotenv
PAYROLL_DOCUMENT_STORAGE_ROOT=runtime/payroll-documents
PAYROLL_DOCUMENT_MAX_UPLOAD_BYTES=26214400
GENERAL_READER_BASE_URL=http://127.0.0.1:8010
GENERAL_READER_CLIENT_ID=
GENERAL_READER_SHARED_SECRET=
GENERAL_READER_TIMEOUT_SECONDS=180
GENERAL_READER_ALLOW_LLM=false
```

General Reader calls fail closed without a valid client ID, root URL, and
shared secret of at least 32 UTF-8 bytes. Real secrets must not be committed.
`PayrollVersion.source_import_id` remains an unbound nullable UUID; its foreign
key/lifecycle relationship is deferred until approval/materialization exists.
