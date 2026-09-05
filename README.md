# Bordro AI

Backend V2.1A payroll-document ingestion architecture is documented in
[`docs/PAYROLL_IMPORT_V21A.md`](docs/PAYROLL_IMPORT_V21A.md). Extraction is
generic staging only; it does not create authoritative payroll revisions.

Backend V2.1B canonical review mapping is documented in
[`docs/PAYROLL_ADAPTER_V21B.md`](docs/PAYROLL_ADAPTER_V21B.md). Canonical
review rows remain staging data and are not approved payroll.
