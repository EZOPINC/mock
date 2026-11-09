# UI Phase 1.8 — future Android/iOS readiness

Reviewed 2026-11-09. Assessment and proposed contracts, not an implemented API or
approval to change authentication. Django/PostgreSQL remains one modular monolith.
No app, API route, token system, dependency, schema or migration is added.

## Assessment and reusable boundaries

The write-side service layer is already suitable for reuse. Mobile adapters should
call it rather than copy selection, publication, feedback or scoring rules.

| Module | Existing reusable logic | Remaining adapter coupling / later work |
| --- | --- | --- |
| accounts | `dashboard.dashboard_context(user)` reads owner-scoped activity/progress; Django authentication and `RegistrationForm` validate existing accounts | Dashboard returns ORM objects/Decimals; registration creation is driven by `RegisterView.form_valid`. Reuse validators; add explicit account read/write adapters when APIs are approved. |
| exams | `selectors.active_authorities()` and `active_exams()` expose active public taxonomy | Module-specific discovery currently repeats authority/exam filtering in Practice, Previous Year and Mock views. Consolidate gradually with parity tests. |
| questions | `services.published_questions()`, `get_published_revision()`, review/publication services; `eligibility.eligible_question_ids()` | ORM models contain answer keys. They are not safe API response objects; future serializers must allowlist fields. |
| previous_year | `services.published_papers()` enforces visibility; publication/unpublication services preserve pinned revisions | `views.stage_scope`, `paper_context` combine discovery, counts, filtering, locks and forms. `paper_answer` validates choices; template compares answers. Extract data/feedback functions before exposing mobile paper practice. |
| mock_tests | `services.available_patterns`, `select_questions`, `start_attempt`; `execution.refresh_attempt`, `save_response`, `submit_attempt`, `confirmation_counts` | `views.attempt_context` prepares frozen section labels, ordered translations and clock metadata. Index also expires attempts on access. Future API must preserve expiry side effects and use existing write services. |
| practice | `services.start_session`, `submit_answer`, `abandon_session`, `progress`, `performance` | Views assemble eligibility discovery/topic counts, resume configuration checks, default question position and translation queries. Future read selectors should accept explicit IDs/filters, not requests/forms. |

Templates render feedback labels, answer highlights, bilingual columns and formatted
scores. They must not become the source of API business rules. Mock scoring and
persistent Practice correctness already run on the server. Public Previous-Year
practice is temporary, resets on reload and is separate from persistent Practice.

### Proposed service structure

- Keep existing `services.py`, `mock_tests/execution.py` and
  `questions/eligibility.py`; do not add an alternative engine or wrapper per screen.
- Use small app-local `selectors.py` modules for shared reads as needed. Only the
  exam selector extraction is implemented in this phase; other selectors are proposed.
- Views authenticate, parse input, call selectors/services, translate errors and
  render HTML or, later, JSON. Services receive user/IDs/validated values, never
  `HttpRequest`, HTML, Django forms, redirects or browser selectors.
- Keep ownership, transactions, parent locks, eligibility and immutable snapshots
  at service/model boundaries. Existing services sometimes raise `Http404` through
  `get_object_or_404`; future adapters can map this consistently without a broad
  exception redesign now. `save_response` already returns HTTP-oriented status data;
  reuse its version/retry semantics rather than rewriting it.
- Future serializers are separate read projections, not a new database schema.
  Keep model instances internal; use strings for Decimal marks and timezone-aware
  ISO timestamps. Existing Django Templates, Tailwind, URLs and JavaScript stay intact.

## Multilingual representation (proposed)

One master Question, one pinned QuestionRevision per selected question, and its
available QuestionTranslation rows. Missing versions remain absent. No HTML parsing,
language-based master duplication or translation-based counting is needed.

```json
{
  "question_id": 42,
  "revision_id": 57,
  "display_order": 1,
  "original_question_number": "12(a)",
  "translations": [
    {"language": "en", "question_text": "Choose a value.",
     "options": [{"id": "A", "text": "One"}, {"id": "B", "text": "Two"},
                 {"id": "C", "text": "Three"}, {"id": "D", "text": "Four"}]}
  ]
}
```

Example is an active-question projection: no answer key, explanation or correctness
flag. After mock finalization or that Practice question's locked submission, a
separate authorized feedback projection may add those fields. Public direct-answer
papers may expose verified solutions under existing publication rules. Do not expose
a generic revision-detail endpoint that lets active test users bypass those gates.
Preserve raw Unicode/newlines, mathematical symbols and A–D order. Return available
versions in English/Bengali/other-language order without changing eligibility or
introducing a student mock language selector. Escape text in every client renderer.

## Proposed `/api/v1/` contract — documentation only

All paths below have prefix `/api/v1/`. Paths and payloads require review before
implementation; none are registered. IDs identify records; existing web slug URLs remain.

| Methods and relative paths | Access / service boundary |
| --- | --- |
| `GET exam-authorities/`, `GET exam-authorities/{id}/exams/`, `GET exams/{id}/`, `GET exams/{id}/stages/` | Public active taxonomy via exam selectors. |
| `GET exams/{id}/subjects/`, `GET subjects/{id}/topics/?exam_id=…` | Authenticated practice eligibility; return only available subject/topic choices. |
| `GET exams/{id}/previous-year-papers/?stage_id=…&year=…&session=…`, `GET previous-year-papers/{id}/` | Public `published_papers`; include paper metadata and question counts. |
| `GET previous-year-papers/{id}/questions/`, `POST previous-year-papers/{id}/questions/{row_id}/feedback/` | Public published pinned content; direct solutions or temporary practice feedback, with the existing mode distinction. |
| `GET exams/{id}/mock-patterns/` | Authenticated `available_patterns`; include configured sections, duration and marks. |
| `POST mock-attempts/`, `GET mock-attempts/`, `GET mock-attempts/{id}/`, `GET mock-attempts/{id}/questions/` | Authenticated owner; `start_attempt`, frozen rows and refresh/expiry semantics. Repeated starts resume as today. |
| `POST mock-attempts/{id}/answers/`, `GET mock-attempts/{id}/submission-preview/`, `POST mock-attempts/{id}/submit/`, `GET mock-attempts/{id}/results/` | Owner-only `save_response`, `confirmation_counts`, `submit_attempt`. Preserve expected version, retry UUID, position, answer and review flag. Results gated by finalization. |
| `POST practice-sessions/`, `GET practice-sessions/`, `GET practice-sessions/{id}/`, `GET practice-sessions/{id}/questions/` | Owner-only `start_session` with existing start token and exam/subject/topic/count validation. Resume fixed revisions. |
| `POST practice-sessions/{id}/questions/{row_id}/answer/`, `POST practice-sessions/{id}/abandon/`, `GET practice-sessions/{id}/summary/` | Owner-only locked/idempotent feedback, abandonment, progress/performance services. Unanswered rows omit solutions even in summaries. |
| `GET accounts/me/`, `GET accounts/me/progress/`, `POST accounts/register/` | Current user only; existing registration/password validation and dashboard data, with explicit serialization. |
| `POST auth/token/`, `POST auth/refresh/`, `POST auth/logout/` | Proposed code exchange, refresh rotation and device-session revocation; secure authentication design below, not current password login endpoints. |

Future lists need bounded pagination, stable ordering and filters, plus a consistent
error envelope. Translate input errors to 400, unauthenticated to 401, forbidden to
403, missing/foreign-owned records to 404 and version/idempotency conflicts to 409.
Adapters must preserve current ownership behavior and distinguish state conflicts
without changing existing service semantics. Active/private responses use no-store.
Do not expose import/admin publication operations in the student API.

## Future mobile authentication — proposal requiring approval

Keep current Django browser sessions, custom user, password validation, CSRF and
safe redirects unchanged. Mobile token authentication is a separate future adapter
to the same users, not a replacement or Google Sign-In requirement.

Prefer authorization code + PKCE (S256) through the system browser, with tightly
registered redirects and state checks. Native applications are public clients:
never embed a client secret or use a password grant. Authorization can use the
existing first-party Django sign-in experience; choosing an authorization-server
library/provider and registering clients is future approved work.
This follows [RFC 8252](https://www.rfc-editor.org/rfc/rfc8252.html) and
[RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html).

Use short-lived, audience-restricted access tokens (proposed 5–15 minutes; exact
lifetimes and token format require review). Rotate refresh tokens atomically on
every use, retain token-family state and detect reuse; revoke the compromised
family on replay. Store only hashed opaque refresh secrets server-side, enforce
idle/absolute expiry, and revoke on logout or relevant account-security changes.
Keep refresh tokens in iOS Keychain / Android Keystore-backed secure storage;
access tokens preferably in memory. Never put tokens in URLs, analytics or logs.
Concurrent refreshes and lost responses need a reviewed retry policy and tests.

Validate active-user status and ownership on every request. Enforce TLS and token
validation, throttle authentication attempts, and preserve browser CSRF protections
for session-authenticated requests. Token persistence/revocation may need future
schema changes or an approved library; no token storage or auth mechanism exists
as part of this phase.

## Minimum work before mobile implementation and deferred risks

1. Approve API/auth contracts, token lifecycle storage and the future API dependency.
2. Extract transport-neutral paper discovery/feedback and owner-scoped attempt/session
   read selectors; reuse their data in both HTML and future JSON adapters.
3. Implement explicit active/feedback/result projections and contract tests for
   answer-key non-disclosure, ownership, Unicode, pagination and immutable revisions.
4. Test mobile retries and multiple devices against current start tokens, autosave
   versions and finalization locks. Keep server time authoritative; offline answering
   after a deadline is not supported by the current contract.
5. Profile bounded discovery queries when APIs are implemented. Practice currently
   checks eligibility per exam; translation ordering/prefetch code is repeated in
   three viewers. Consolidate only with targeted parity/query-count evidence.

Other risks: template contexts contain full revision objects including solutions;
never JSON-encode them wholesale. Browser redirects and `result_url` values are not
an API contract. Pinned revisions freeze content, but current publication/exam
associations can still affect public discovery; APIs must retain those rules.
No offline cache, background sync, push notifications or mobile UI is introduced.
Significant refactors, token persistence and new endpoints require a separate
approved milestone. Existing security-sensitive tests are unchanged.
