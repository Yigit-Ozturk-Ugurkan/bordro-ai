# Bordro AI Backend MVP — Status

**Last updated:** 2026-09-02 (handoff audit session)
**Status:** Backend MVP read path complete and integration-tested.

> **Correction to the previous revision of this file.** It reported
> "148 tests passing / COMPLETE" and listed *Phase M: API Integration Tests*
> as done. That was not accurate. The API integration test file
> (`tests/integration/test_payroll_api.py`) had been created, had failed,
> and was then deleted; the 148 figure is the suite *with the API tests
> removed*. No endpoint was covered by any automated test at that point,
> and two of the five MVP endpoints did not exist. See
> "Handoff repair" below.

---

## Test suite

```
208 collected / 208 passed / 0 failed / 0 skipped / 0 xfailed
```

| File | Tests |
| --- | --- |
| `tests/integration/test_payroll_api.py` | 46 |
| `tests/integration/test_tax_models.py` | 36 |
| `tests/integration/test_payroll_details.py` | 36 |
| `tests/integration/test_tax_engine.py` | 27 |
| `tests/unit/test_tax_schemas.py` | 24 |
| `tests/integration/test_demo_seed.py` | 14 |
| `tests/integration/test_dashboard_service.py` | 7 |
| `tests/integration/test_comparison_service.py` | 7 |
| `tests/integration/test_cumulative_tax_service.py` | 5 |
| `tests/integration/test_tax_service.py` | 4 |
| `tests/integration/test_tax_seed.py` | 2 |

Run:

```powershell
cd backend
.venv\Scripts\python.exe -m pytest tests/ -q
```

The suite requires a running PostgreSQL 16 and the seeded 2026 tax rule set.
Every test runs inside a transaction that is rolled back, so the database is
unchanged afterwards.

---

## Handoff repair

Four defects were found by writing the API tests that the previous session
had deleted. All were in the implementation, not the tests.

1. **Async/sync session mismatch.** Routes annotated `sqlalchemy.orm.Session`
   but the `get_db` dependency yielded an `AsyncSession`. Every data
   endpoint returned HTTP 500 (`coroutine 'AsyncSession.execute' was never
   awaited`).
2. **psycopg cannot use Windows' ProactorEventLoop.** The async driver
   refused to connect at all, so `/health/db` was unusable. Fixed by
   installing `WindowsSelectorEventLoopPolicy` before the engine is built
   (`app/core/event_loop.py`), which preserves the intended async stack.
3. **Demo seed referenced `PayrollVersionStatus.PUBLISHED`**, which is not a
   member of that enum. Every call raised `AttributeError`, so no test could
   obtain data to exercise the API with.
4. **January comparison returned 422 instead of 400.** `Path(ge=2)` rejected
   month 1 before the handler's own 400 branch could run, making that branch
   dead code.

---

## API

| Method | Path |
| --- | --- |
| GET | `/health` |
| GET | `/health/db` |
| GET | `/api/v1/system/info` |
| GET | `/api/v1/employees/{employee_id}/payrolls` |
| GET | `/api/v1/employees/{employee_id}/payrolls/{year}/{month}` |
| GET | `/api/v1/employees/{employee_id}/payrolls/{year}/{month}/comparison` |
| GET | `/api/v1/employees/{employee_id}/tax-status` |
| GET | `/api/v1/employees/{employee_id}/dashboard/{year}/{month}` |

All are read-only. Handlers hold no business logic: each resolves path
parameters, delegates to a service through `AsyncSession.run_sync`, and
validates the result through a Pydantic response model. ORM objects are
never returned directly.

Domain errors (`app/core/exceptions.py`) are translated by a single handler
in `app.main`, so database and driver exceptions never reach a response body.

---

## Architecture

```
FastAPI  ->  SQLAlchemy Async  ->  psycopg  ->  PostgreSQL 16   (runtime)
Alembic CLI  ->  SQLAlchemy Sync  ->  PostgreSQL                (migrations)
```

The payroll and taxation services are synchronous. They are reached from the
async runtime through `AsyncSession.run_sync`, SQLAlchemy's greenlet bridge,
which hands the callable a real synchronous `Session` on the same async
connection. This keeps one query style shared by the services, Alembic, and
the test suite, without giving up the async runtime.

Layering: `route -> service -> repository -> database`.
`app/repositories/payroll_repository.py` is the single source of truth for
which payroll revision is "current".

---

## Money policy

- Every financial value is `Decimal`; there is no `float` anywhere in `app/`.
- Money `NUMERIC(18,2)`, rates `NUMERIC(9,6)`, day counts `NUMERIC(5,2)`.
- Rounding is `ROUND_HALF_UP` (`app/core/money.py`).
- Decimals serialize to JSON **strings**, preserving scale exactly.
- Optional money fields are serialized with `is not None`, so a real
  `0.00` is never rendered as `null`.

---

## Tax engine

- Progressive calculation: `base_tax_amount + (base - lower_limit) * rate`.
- Bracket semantics `[lower, upper)`; the final bracket has `upper_limit = NULL`.
- **No threshold or rate is hard-coded in calculation logic.** They live only
  in `TaxRuleSet` / `TaxBracket` rows, seeded by `app/seeds/tax_2026_seed.py`.
  A legislative change is a data change.
- Boundary behaviour is tested at `threshold - 0.01`, `threshold`, and
  `threshold + 0.01` for each bracket.

## Cumulative tax

Append-only monthly ledger: `opening + monthly = closing`. Records are never
updated or deleted; a recalculation creates a new `TaxCalculationRun`.
January opens at `0.00`, so a new tax year starts fresh without touching the
previous year's history.

## Comparison

Factual deltas only — previous/current, absolute delta, percentage delta,
missing-days delta, and per-code earning and deduction deltas across the
union of both periods' codes. The service makes **no causal claims**; a test
asserts the payload carries no explanatory fields. Attributing a net change
to one cause needs a counterfactual engine, which does not exist.

---

## Seeds

Both seeds are idempotent, verified in-transaction by tests and on the
committed path by running each twice (row counts identical).

```powershell
.venv\Scripts\python.exe -m app.seeds.tax_2026_seed
.venv\Scripts\python.exe -m app.seeds.demo_payroll_seed
```

Demo data is entirely fictitious (`DEMO_COMPANY` / `DEMO001`): two 2026
periods with earning and deduction lines, a code present in only one month
(`BONUS`), an unpaid-absence scenario, and cumulative tax ledger records.

> `PayrollVersion.income_tax` in the demo seed is a rounded illustrative
> figure, not the engine-derived withholding implied by the ledger. See
> Technical debt.

---

## Migrations

Single head, no drift:

```
alembic current -> 4d4079f9be56 (head)
alembic heads   -> 4d4079f9be56 (head)
alembic check   -> No new upgrade operations detected.
```

No new migration was needed for this work; no model changed.

---

## Technical debt

1. Demo `income_tax` values do not reconcile with the cumulative ledger's
   derived withholding. Harmless for a demo, misleading as an example.
2. `CumulativeTaxService.get_latest_cumulative_base` selects the highest
   `period_month` in the year rather than specifically month `N-1`. Correct
   for sequential monthly processing; would need revisiting for out-of-order
   or retroactive runs.
3. `json_encoders` in the Pydantic schemas is deprecated in Pydantic v2
   (38 warnings). It is inert — Decimal already serializes as a string.
4. No 2027 tax rule set exists, so `tax-status` for 2027 correctly returns
   404. A rule set must be seeded before the 2027 year rolls over.

---

## Not implemented (deliberately out of scope)

Frontend, authentication, JWT/RBAC, chatbot, LLM/RAG, STT/TTS, PDF/OCR,
Excel import, Docker, WSL, microservices. Write/calculate payroll endpoints
are also out of scope; this MVP is the read path.
