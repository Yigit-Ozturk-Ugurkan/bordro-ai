# Bordro AI frontend

React, TypeScript, Vite, React Router, and Tailwind CSS power the employee
self-service dashboard. All salary, deduction, comparison, and tax values are
rendered from backend responses; no payroll calculations are implemented in
the browser.

## Local development

1. Copy `.env.example` to `.env` if the API is not running at the default URL.
2. From `backend`, start the Windows-safe API with `python -m app`.
3. From `frontend`, run `npm install` and `npm run dev`.
4. Open `http://127.0.0.1:5173/login`.

Use `npm test` for the frontend suite and `npm run build` for the production
build.

## Authentication storage

For this MVP, access and refresh tokens are isolated in `sessionStorage` by
`src/auth/tokenStore.ts`. This avoids persisting tokens across browser sessions
but remains readable to JavaScript in the page, so an XSS flaw could expose
them. A production hardening phase should move refresh credentials to secure,
HTTP-only, same-site cookies alongside a strict Content Security Policy. No
payroll response data is written to browser storage.
