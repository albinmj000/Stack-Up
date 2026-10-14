# Stack Up Finance Security Review

**Review date:** 2026-10-14
**Scope:** Read-only review of authentication and user-data isolation, relevant
FastAPI routes and database ownership checks, statement uploads and storage,
AI request scoping, CORS/configuration, and existing tests.

## Findings

| # | Severity | File | Lines | Finding | Confidence |
|---|----------|------|-------|---------|------------|
| 1 | Medium — fixed | `frontend/mobileApiUrl.js` | 1–27 | Mobile builds now require an absolute HTTPS API URL and reject malformed/relative URLs, credentials, query strings, and fragments. Regression tests cover accepted and rejected values. | 8/10 |

## User-data isolation tests added

`tests/test_user_data_isolation_api.py` creates two users in a temporary
database and exercises the FastAPI routes with separate session tokens. It
checks account/profile listing and account switching, statement and transaction
reads/deletes, bank-account assignment, upload bank-account selection,
category and income-inclusion updates, and foreign statement IDs on `/message`.
It also verifies that an Assistant request as User A passes only User A's
transactions into its AI context.

These tests passed for the covered routes and fixture cases. They did not
establish or test every route, every authentication lifecycle, production
database configuration, or deployment settings; this report is not a security
certification.

## Remediation and verification

1. `npm test` — **15 passed**, including mobile API URL validation.
2. `python -m unittest discover -s tests` — **98 passed**, including the
   two-user route and AI-context tests.
3. `npm run build:mobile` and `npm run cap:sync` — **passed**.
4. `npm run build` — **passed**.
5. `npm run lint` — **0 errors**; one pre-existing React hook dependency
   warning remains in `frontend/src/App.jsx`.
6. The mobile URL validator was also checked by invoking a mobile build with
   an HTTP API URL; the build rejected it as expected.

## Limitations

This follow-up fixed the reported mobile URL validation issue and added
automated isolation tests; it did not alter production settings or deploy the
application. Review the authentication, upload validation, secrets/logging,
CORS, and production environment independently before making any broader
security claim.
