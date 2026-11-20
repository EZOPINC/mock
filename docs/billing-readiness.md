# B6 billing readiness report

## Outcome

Critical billing checks pass in the local PostgreSQL test database. This is conditional readiness for simulated billing, not approval to collect real payments. Cross-module validation is not fully green, and the workspace has pre-existing documentation conflict markers. No real provider, credentials, payment, runtime data inspection or production migration was introduced by B6.

## Executed validation

| Check | Result |
|---|---|
| `python manage.py test billing --noinput` | 110 tests passed, including 9 new B6 security/performance cases |
| `python manage.py test mock_tests practice revision previous_year imports.tests imports.test_unified accounts.test_authentication accounts.test_dashboard accounts.test_account_sections --noinput` | 330 tests: 328 passed, 2 Previous-Year presentation assertions failed |
| `python manage.py check` | Passed |
| `python manage.py makemigrations --check --dry-run` | Passed; no new migration needed |

Tests used the existing virtual environment and PostgreSQL test runner, including separate-connection concurrency tests, financial database guards and the existing Revision migration regression. Runtime database contents, production migration state, production configuration and production logging were not inspected.

## Verified boundaries

- Free: persistent shared exam selection; one distinct Mock pattern with unlimited retakes; 50 configured lifetime distinct Practice master IDs; revisits/translations/revisions do not consume additional units. Separate-connection races cannot select two exams/Mock sets or spend the final question slot twice. Premium starts bypass these Free allocations and do not reset them.
- Premium: all-exam Mock/Practice access, idempotent activation/renewal, early extension, late renewal, automatic timestamp expiry and approved refund revocation. Existing attempts/results, sessions, bookmarks, revision history and Free ledgers survive expiry/refund. Resume/history remain owner-scoped.
- HTTP authorization: ordinary/guest users cannot operate the simulator, grant Premium through Admin, edit usage records, transfer an allocation with posted user IDs, or activate by posting browser status/price/plan flags. Mutation paths enforce their roles, ownership and CSRF. Financial views, manual grants, plan management, refund approval and exports remain distinct permissions.
- Payments: pending/failed events do not grant access; duplicate and late events cannot grant twice or reverse finalization. Provider/order/payment references, amount and currency must match. NaN, signaling NaN and infinities are rejected as validation errors. Injected failures after subscription/refund writes roll back the financial and entitlement changes, preserve the received receipt and permit safe retry.
- Simulation: explicit opt-in and DEBUG/non-production checks are enforced both at settings load and at runtime. Unsafe production configuration fails closed. No real gateway is configured.
- Data/audit: source review found no payment-credential/PAN/CVV/banking storage fields or billing request-payload logging. A synthetic sensitive-field marker posted to checkout is discarded, absent from the stored quote and captured logs, and cannot activate Premium. This is source/test evidence, not a scan of private runtime records or production logs. Audit/document/reference immutability, database finalization guards, tax snapshots, credit notes, export permissions, spreadsheet-cell escaping and export digests pass their tests.
- Previous-Year Papers retain public guest access and stateless paper-practice behavior with no billing allocation calls. Import routes remain under `/admin/question-import/`, enforce staff plus import/Question/paper permissions, ownership and CSRF, and do not gain access from a Premium plan.

## B6 fixes and performance evidence

- `billing/usage.py`: recheck active status on the locked owner before a new allocation; an old in-memory active user can no longer allocate after database deactivation. Load only candidate-question usage IDs and count lifetime usage in SQL, rather than materializing every historical usage ID.
- `billing/payments.py`: reject non-finite provider amounts before comparison, avoiding an unhandled signaling-NaN comparison at the verification boundary.
- `billing/test_security.py`: nine regression checks cover crafted requests, stale owner status, ignored sensitive fields, late rollback/retry, malformed amounts and query budgets.

Measured feature evaluation uses three SELECTs for Free and two for Premium, including an account with 30 historical subscription terms. Free Practice pool policy uses nine test queries including the savepoint pair (seven data queries); its two usage reads are candidate-filtered membership and SQL COUNT. Existing `(user, status, ends_at)` subscription indexing and unique `(user, question)` usage indexing support these paths. Query counts are regression bounds, not a production latency or load certification. Existing question eligibility/selection costs are unchanged.

## Unresolved release issues

1. `previous_year.test_public_solutions.PublicPaperSolutionsTests.test_missing_optional_language_uses_available_single_column_content` and `previous_year.test_viewer.PaperViewerTests.test_monolingual_direct_answers_are_highlighted_and_open` expect exactly one `class="question-content translation-panel"` wrapper, but the current reader renders through the shared reading components. Both fail with count zero. Previous-Year source/tests are unchanged by B6; reconcile the reader/test presentation contract separately. Do not describe the full regression run as green.
2. Literal `<<<<<<<`, `=======` and `>>>>>>>` markers remain in `docs/MODULE_MAP.md` at validation time, even though Git's unmerged index entries were cleared. Existing staged UI/documentation work was left intact. Resolve these markers before release.
3. Deployment readiness remains unverified: apply/review billing migrations through 0009, configure and assign billing roles, review plan prices/features and seller/tax/retention settings, and confirm backups and production logging/access controls. Retention eligibility never authorizes automatic erasure. Restrict production application DB privileges so privileged DDL/TRUNCATE cannot bypass ordinary history guards.

## Required before a real gateway

- Implement and test the selected provider adapter with authenticated server-side confirmation/webhook verification, provider-specific signature/replay checks, strict merchant/order/payment/refund association, INR amount/minor-unit validation, and immutable provider references. Browser callbacks must remain display-only. Store gateway secrets outside financial records and redact sensitive inbound data from logs.
- Add durable retry/recovery and operational monitoring for paid-but-unfulfilled receipts, provider timeouts, duplicate/out-of-order callbacks, refund failures, and reconciliation discrepancies. The simulator's authorized manual retry path is not an unattended gateway ingestion/operations system.
- Validate seller/customer invoicing requirements, configured tax treatment, invoice/credit-note format and numbering, and retention policy for the actual business before live invoicing; B5 records do not assume GST registration or provide filing/compliance approval.
- Validate production security configuration and least-privilege processor/staff/database roles; keep simulation disabled. Run provider sandbox end-to-end, disaster recovery and representative-volume tests. Accounting exports currently buffer output and perform related-record lookups; large-volume export/load behavior remains unbenchmarked.

No gateway integration, unrelated refactor, scoring/timer/question-selection change or schema migration was performed in B6.
