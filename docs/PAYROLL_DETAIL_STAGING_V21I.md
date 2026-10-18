# Payroll Detail Staging V2.1I

V2.1I extends Bordro AI's existing document-import transaction with generic
table evidence from General Reader's `ExtractionResultV1` response:

```text
General Reader extraction
        |
        +-- scalar fields --> PayrollImportField
        |
        +-- tables --> PayrollImportTable
                         |
                         +-- ordered PayrollImportTableRow
                                  |
                                  +-- ordered PayrollImportTableCell
```

One General Reader request supplies both branches. On successful processing,
Bordro replaces the machine-generated scalar and table staging sets in the
same database transaction. A validation or persistence failure rolls back both
sets. Existing terminal import-state restrictions still prevent processing
after review or later workflow evidence exists.

## Contract mapping

`PayrollImportTable` records the extraction response's table order, source
table ID and label, declared columns, page-number list, warning strings, row and
column counts, and a deterministic SHA-256 source checksum. A table remains
separate from every other table in the response; no same-page or cross-page
merge is attempted.

`PayrollImportTableRow` records the supplied row index, page number, optional
normalized bounding box, coordinate space, and extraction source. General
Reader V1 supplies no row identifier, row text, or row confidence, so Bordro
does not fabricate those values.

`PayrollImportTableCell` records the column position derived from the table's
ordered column declaration, source column ID and label, raw nullable string,
producer value-type label, nullable confidence, optional normalized bounding
box, coordinate space, and extraction source. Cell page ownership comes from
its parent row because V1 does not provide a separate cell page number.
Meaningful cells whose `raw_value` is null remain null; they never become zero.
General Reader's normalized cell string is not used as Bordro payroll truth.

## Provenance and isolation

Every table has organization-scoped composite foreign keys to its
`PayrollImport` and `PayrollImportDocument`. Rows and cells continue that
organization-scoped ownership through composite foreign keys to their parent.
Source table, row, and column positions preserve deterministic ordering.

The checksum uses canonical JSON containing stable source metadata, positions,
raw values, confidence strings, and bounding boxes. Database IDs and timestamps
are excluded. It is an evidence fingerprint, not a signature.

The read API is:

- `GET /api/v1/payroll-imports/{import_id}/tables`
- `GET /api/v1/payroll-imports/{import_id}/tables/{table_id}`

It follows existing payroll-import read permissions: `PAYROLL_ADMIN`,
`HR_ADMIN`, and `AUDITOR` may read; cross-organization lookup is a
non-disclosing 404. There are no table edit endpoints.

## Validation and limits

Bordro rejects duplicate row indices, duplicate or unknown cell-column
coordinates, invalid table/page relationships, and overlong bounded metadata.
The strict V1 schema already rejects negative row indices, invalid pages,
malformed confidence, and malformed bounding boxes. Configurable server limits
bound tables per import, rows and columns per table, total cells per table, and
raw cell text length. Malformed or oversized extraction fails closed without
partial staging.

## Explicit boundaries

V2.1I performs no payroll-detail business classification. It does not create
or materialize `PayrollEarning`, `PayrollDeduction`, or `PayrollAbsence` rows.
It performs no payroll calculation, total reconciliation, or tax work. It
contains no template changes and no General Reader changes.
