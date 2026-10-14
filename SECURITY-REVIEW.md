# Stack Up Finance Security Review

**Review date:** 2026-10-14
**Scope:** Read-only review of authentication and user-data isolation, relevant
FastAPI routes and database ownership checks, statement uploads and storage,
AI request scoping, CORS/configuration, and existing tests.

## Findings

| # | Severity | File | Lines | Finding | Confidence |
|---|----------|------|-------|---------|------------|
| 1 | Medium | `frontend/vite.config.js` | 5–10 | Mobile builds require a non-empty `VITE_API_BASE_URL`, but do not validate that it uses HTTPS. Since authenticated API requests use credentials, an accidentally configured HTTP base URL could expose login and financial traffic in transit. The mobile URL inspected during this review used HTTPS; this is a conditional build-configuration risk, not evidence that current traffic uses HTTP. | 8/10 |

## Isolation test coverage gap

Existing database tests exercise some user-scoped helpers, but the review did
not find route-level tests proving with two separate users that one account
cannot read or modify the other account's records by supplying its record IDs.
The review also did not find an AI-context isolation test proving that one
user's Assistant request cannot include another user's statements or
transactions.

This is a test-coverage gap, not a confirmed cross-user access vulnerability.
The static review did not establish a confirmed user-data isolation bypass.
This review is not a security certification.

## Recommended remediation and verification

1. Validate `VITE_API_BASE_URL` during mobile builds as an absolute HTTPS URL.
   Add configuration tests proving HTTPS passes and HTTP, malformed, and
   non-absolute values fail.
2. Add route-level tests using separate users A and B. Authenticate as A and
   attempt to access B's statements, statement contents, transactions,
   category/income updates, bank-account assignment, and message requests with
   B's statement IDs. Verify requests are rejected and B's data is unchanged.
3. Add an Assistant scoping test with distinct financial fixtures for A and B.
   Verify B's statement IDs cannot be used by A and B's transaction details
   are never passed into A's AI request context.
4. Run the relevant tests against the actual route and database setup before
   claiming the isolation controls have been verified.

## Limitations

This was a static, read-only review. No source files were changed during the
audit, and no tests were added or run. The findings above are limited to the
evidence inspected; absence of a confirmed bypass is not proof that all routes
or deployment configurations are secure.
