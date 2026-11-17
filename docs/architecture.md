# Project Architecture

Source-verified reference, 2026-11-12. Source code overrides this document.
Use MODULE_MAP.md for navigation and DEVELOPMENT_RULES.md for change safety.
This consolidates older roadmap notes into the current implementation.
The tracked filename is `docs/architecture.md`; retain its casing in links.

## Stack and layout

- Python with Django `>=5.2.19,<5.3`; PostgreSQL via psycopg 3.
- `requirements.txt` also declares python-dotenv, openpyxl and defusedxml.
- A modular Django monolith uses server-rendered templates and session authentication.
- Vanilla JavaScript enhances forms, navigation and asynchronous saves.
- Tailwind 4.3.5 is pinned with checksums in `tools/tailwind-lock.json`.
- `assets/tailwind.css` is source; `static/css/tailwind.css` is compiled output.
- `tools/build_css.py` uses a standalone compiler; Node/npm is not required.
- `static/css/site.css` and feature stylesheets provide fallback/scoped presentation.
- `templates/base.html` loads shell assets; bookmark CSS follows feature head assets.
- `config/` holds settings, root URLs, admin customization, ASGI and WSGI.
- Settings load environment values; never copy local values into documentation.
- PostgreSQL is required; settings provide no SQLite fallback.
- `manage.py`, `requirements.txt`, `templates/`, `static/` and `tools/` are shared roots.
- Ignore virtual environments, caches, staged uploads and collected/generated assets.

## App boundaries

| App | Owns | Main consumers |
|---|---|---|
| `core` | Curated home catalogue; database readiness endpoint | Public landing/shared shell |
| `accounts` | Custom User, registration, account views, learning dashboard | User-owned workflows |
| `exams` | Authorities, exams, stages and normalized academic taxonomy | Question discovery |
| `questions` | Master identities, immutable content, translations, topic/exam/source tags | All assessment/content apps |
| `imports` | Bounded ingestion, staged correction/pairing, confirmation and audit | Staff UI; General collections |
| `previous_year` | Papers, ordered approved-revision associations, public reader | Imports, admin, students |
| `general_question` | General-import collections and whole-batch review/publication | Staff/public collections |
| `mock_tests` | Pattern/rule configuration, immutable shared demo publications, timed attempts, autosave and scoring | Authenticated exams |
| `practice` | Untimed snapshots, answer locking, feedback and progress | Practice and Revision sessions |
| `revision` | Bookmarks/notes/mastery, bank, revision selection, topic exploration | Registered students |
| `billing` | Configurable plans, feature entitlements and subscription terms | Central read-only access policy; staff admin |

`config` is project wiring, not a domain app. `questions` has no standalone URL module.
Question admin is in `questions/admin.py`; student rendering is downstream.
`general_question` is the package; its URL namespace is `general_questions`.

## Models and identity

- `accounts.User` extends AbstractUser and is AUTH_USER_MODEL.
- ExamAuthority -> Exam -> ExamStage is the exam catalogue, with protected relations.
- Authorities/exams have active flags; a stage belongs to one exam.
- Subject is independent of exam membership.
- Academic paths: Subject -> optional Part -> optional Module -> optional Chapter -> Topic.
- Each hierarchy node has its Subject anchor and at most one immediate parent.
- Modules may attach to Subject; Chapters to Subject/Part/Module; Topics to any ancestor.
- Names/slugs are scoped to actual parents; stable codes identify existing nodes.
- Model validation and PostgreSQL triggers guard codes and established ancestry.
- Topic immediate-parent moves within its Subject differ from immutable parent nodes.
- Question is the deduplication identity, not a language, paper row or attempt row.
- Question has one Subject, legacy primary topic, and multiple QuestionTopic tags.
- All tags share its Subject; classified questions have one matching primary tag.
- QuestionExam supplies many-exam membership; there is no direct Subject-to-Exam ownership.
- QuestionSource and QuestionSourceReference retain provenance and page references.
- QuestionRevision stores numbered content, answer, difficulty and publication time.
- QuestionTranslation stores language content, unique within each revision/language pair.
- Primary-language revision fields remain for compatibility with older consumers.
- Configured languages are English (`en`) and Bengali (`bn`).
- current_revision is working content; published_revision is the approved live pointer.
- Master answer/difficulty mirror the working revision; scoring uses frozen content.
- A new revision resets review status; an older published revision can remain live.
- Revision content is append-only, including drafts; publication permits one guarded timestamp write.

## Shared interfaces and dependencies

| Interface | Responsibility / return |
|---|---|
| `questions.services.create_question` / `create_revision` | Create masters/new multilingual snapshots |
| `questions.services.mark_reviewed` / `publish_question` | Explicit review/publication; optional expected revision ID |
| `questions.services.published_questions` | Published master queryset and approved content preloads |
| `questions.eligibility.eligible_question_ids` | Eligible master-ID set by exam/language/optional scope |
| `questions.tagging.set_question_topics` | Atomic tag replacement and legacy primary synchronization |
| `questions.selectors.questions_by_topics` | Distinct masters for explicit topic IDs |
| `previous_year.services.published_papers` | Public papers; fails closed on invalid associations |
| `practice.discovery.PracticeTaxonomy` | Eligible descendant pools and frozen filter labels |
| `practice.services.assemble_session` / `submit_answer` | Shared snapshots and locked feedback |
| `revision.selectors.visible_questions` | SQL eligibility plus owner-specific open-mock exclusions |
| `revision.exploration.related_questions` | Scoped, source-excluding related master queryset |

Publication alone is not full eligibility: exam activity, translations and access rules matter.
`exams.selectors.subjects_for_exam` derives membership, not full question eligibility.
`mock_tests.services.eligible_question_ids(section)` is a section adapter with a different signature.
Imports depend on Question workflows/paper models; General collections depend on import audit.
Revision reuses Practice services; Practice lazily calls the Revision first-answer review hook.
Account dashboard excludes revision-kind sessions from ordinary Practice statistics.

## Billing foundation, Free usage and Premium lifecycle (B1–B5)

- `billing` shares the existing PostgreSQL database and references `AUTH_USER_MODEL`.
- `SubscriptionPlan` configures Free/Premium tier, INR price, active status and Premium duration (30/90/365 days). Premium covers all supported exams; there are no exam-specific billing associations.
- B1 seeds active Free and three inactive Premium duration variants with zero placeholder prices. Staff must configure Premium prices and entitlements before enabling them. B2 configures Free Mock to one set and Free Practice to 50 distinct questions with lifetime periods; Revision remains unchanged. These are database configuration, not runtime pricing/limit constants.
- `PlanEntitlement` configures enabled access, optional usage limit (null = unlimited, zero = no usage), and usage period (lifetime, UTC calendar day or subscription term). Free has no subscription term.
- `UserSubscription` stores a half-open term `[starts_at, ends_at)`, active/cancelled/expired/revoked status, optional predecessor and frozen plan/price snapshot. Later plan edits never rewrite recorded terms or prices. Existing pre-B3 snapshots are explicitly marked as inferred current configuration; their original prices were not recorded.
- `billing.services.subscription_for` selects the latest-starting effective active Premium term (primary key breaks ties). Lifecycle-issued terms remain valid if their sales plan is later deactivated; legacy terms retain the earlier active-plan requirement. `plan_for` otherwise resolves active Free without creating subscription rows. Expired, future, cancelled or revoked terms do not grant current Premium access. Feature enablement still uses plan entitlements.
- `evaluate_access`, `mock_access`, `practice_access`, `revision_access` and `require_access` provide centralized decisions. Anonymous/inactive accounts, missing/inactive Free configuration and missing/disabled entitlements fail closed. Premium entitlements replace rather than merge with Free entitlements.
- Generic `evaluate_access` accepts trusted `used`/`requested` units; it does not reserve usage. Mock/Practice starts use `billing.usage` for actual allocation. Existing content eligibility, ownership, selection rules, scoring, timers and snapshots remain authoritative.
- `billing.providers.SubscriptionProvider` retains the earlier subscription-verification contract. B4 adds `PaymentProvider` with server-side order creation/event verification and a local simulated implementation. Future Razorpay/Cashfree adapters must authenticate confirmations; no real provider or credentials are configured.
- The first successful Free Mock/Practice start persistently selects the account's exam (`FreeExamSelection`). M1 replaces per-user Mock pattern selection with the exam's designated shared Free Demo. Legacy `FreeMockSelection` records remain stored but do not restrict the designated demo. New Free starts copy its immutable MockSet; Premium starts retain per-attempt random/manual selection.
- Free Practice records distinct master Question IDs in `FreeQuestionUsage` before session assembly, including unanswered questions. P1 `available` starts prioritize unseen masters in batches controlled by `PRACTICE_FREE_SESSION_SIZE` (default 10), capped by the configured lifetime allowance (initially 50). A quota-limited final batch is partial; small scopes may include allocated revisits without extra usage. Allocated-only scopes and historical sessions remain revisitable, while a request needing new questions after quota exhaustion gets the existing upgrade prompt. Registration, answers, refreshes, translations and later revisions do not allocate another unit. Premium and explicit numeric count behavior remain unchanged. See `docs/practice-sessions.md`.
- Start transactions lock the account before checking policy/ledgers. One-to-one exam/mock choices and a unique user/master constraint backstop the locks. Ledger writes commit with attempts/sessions; failed starts roll back all allocations. Admin exposes ledgers for permission-gated inspection only, with no add/change/delete operations.
- Effective Premium bypasses Free exam/set/question limits but still requires an enabled feature. Premium starts neither consume nor reset Free ledgers. After expiry, Free selections and remaining allowance persist. Existing unfinished attempts, idempotent start tokens, owned sessions and history remain accessible, including those created during Premium. New Free starts for questions delivered only during Premium consume Free allowance; those historical sessions remain revisitable without a new allocation.
- B2 backfills pre-existing non-Premium Mock/Practice delivery: earliest start selects the Free exam; earliest Mock in that exam selects the set; distinct Practice master IDs across earlier Free sessions consume lifetime usage. Legacy use over 50 is retained, with zero new allowance. Recorded Premium term dates identify historical Premium delivery regardless of current cancellation or plan activity, since past status transitions were not recorded. Revision-kind sessions are excluded. No historical rows are rewritten.
- Previous-Year Papers and Revision workflows do not call the allocation services and retain existing access behavior. Guests cannot start Mock/Practice sessions; setup pages explain Free selection and display Premium upgrade messages on denied starts.
- `billing.lifecycle` owns activation, renewal, explicit expiration, revocation and approved-full-refund revocation. Every operation requires an active staff actor with `billing.manage_subscriptions`, an audit reason and a globally unique idempotency key. Identical retries return the original term; reusing a key for another request fails. Account locks serialize grants/renewals with each other and Free allocation; the audit event and term/status write commit atomically.
- Monthly, Quarterly and Yearly plans use the configured 30/90/365-day durations, rather than calendar-month arithmetic. Early renewal appends a new term from the latest active allocated expiry, including queued renewals; late/exact-expiry renewal starts from the operation timestamp. Original terms stay immutable. Activation rejects an existing allocation and directs staff to renewal. Each new term snapshots its own plan code/name/tier, duration, price and currency.
- End-date checks restore Free access immediately without a job. `expire_subscription` can additionally record expired status and an audit event after the term ends. Revocation and approved full refund revoke only the associated term, including a future renewal; independently allocated terms remain intact. Full-refund approval records its reference in the audit payload and processes no money. No operation resets Free ledgers or deletes learning/subscription history.
- `SubscriptionEvent` retains actor, kind, key, reason, request and aware effective/creation timestamps. Lifecycle-managed terms reject direct model/queryset edits; event mutation and subscription/event deletion are rejected. Legacy empty-snapshot ORM creation remains compatible for existing integrations/tests; administrative issuance uses the audited service exclusively.
- Subscription and event Admin records are read-only. The subscription changelist links to a CSRF-protected lifecycle form for authorized billing managers (`billing/forms.py`, `templates/admin/billing/`). Use normal view permissions for Admin inspection and the separate lifecycle permission for writes. No public direct-activation route is introduced.

### Simulated purchase and financial ledger (B4)

- Financial records stay in `billing` and the existing PostgreSQL database: `PaymentOrder` freezes account, plan/quote, INR amount, currency, checkout key and provider references; `PaymentTransaction` keeps the immutable payment reference/amount with pending/failed/success status; `PaymentEvent` retains each server-created provider receipt and processing result; `Refund` records a completed full simulated refund and approval actor. Model/queryset guards retain records and protect references and snapshots. Admin is read-only for these models.
- `BILLING_SIMULATION_ENABLED` defaults to false and requires explicit environment configuration. Enabling it requires `DEBUG=True`, a non-production `DJANGO_ENV` and `IS_PRODUCTION=False`. Production/DEBUG-off settings fail at startup; runtime guards also reject unsafe settings overrides. No implicit test-runner bypass exists: tests explicitly enable the simulator and DEBUG.
- `/billing/` lists active plans and the signed-in account's recent orders. Authenticated CSRF-protected checkout creates an idempotent pending purchase using server-side plan configuration, never submitted price/currency/status. Pricing remains available when simulation is disabled, but purchasing is unavailable. Status and subscription confirmation pages are owner-scoped and never consume browser payment-status parameters. Confirmation requires a paid ledger order with an associated subscription.
- Simulator POST controls require active staff with both `billing.run_simulated_payments` and `billing.manage_subscriptions`. Ordinary students can create test orders in an explicitly enabled environment, but cannot choose success/failure/refund outcomes. Authorized operators use their own status page or a student's read-only PaymentOrder Admin page. Disabled/production environments expose no controls and reject direct calls. GET cannot create or confirm payment; CSRF remains enforced.
- `simulate_payment` persists an authenticated local provider receipt, then `process_payment_event` verifies it through the adapter. No public unverified webhook endpoint exists. Verified provider, order/payment references, outcome, amount and currency must match the frozen order before fulfillment. Receipts store only whitelisted fields, with no arbitrary browser payload, card or banking information.
- Processing locks the account, order and event in that order. Unique checkout/event/order/payment references and one-to-one purchase/subscription/refund links backstop idempotency. Created/pending orders can become paid or failed; failed orders are terminal and require a new checkout. Paid orders ignore late pending/failed/success events; refunded orders cannot reactivate. Duplicate same-ID events and distinct repeated success/refund events cannot allocate another term or refund.
- Confirmed payment calls the existing lifecycle calculation via an internal fulfillment boundary with the frozen server quote. A first purchase grants a term; another order renews from the latest allocated expiry. The lifecycle audit records a renewal-kind grant for either case, with a stable order-derived key and the confirming operator. Later plan price/duration edits or deactivation do not alter an already quoted purchase. No browser route can call this boundary directly.
- Provider receipts commit before fulfillment. If fulfillment fails, transactional ledger/entitlement writes roll back while the receipt remains `received` for authorized retry. Successfully processed/ignored events retain a timestamp and result. A full refund records the full original amount, preserves the successful payment transaction, revokes only the purchased term through B3, and changes the order to refunded. No real money is collected or returned; Free ledgers and learning history are untouched.

### Financial operations and audit readiness (B5)

- `billing/audit.py`, `finance.py`, `accounting.py` and `exports.py` own controlled operational writes, reviewed seller/tax/retention settings, invoice/credit-note snapshots, settlement/reconciliation evidence and reference-based accounting CSVs. All models remain in billing/PostgreSQL. See `docs/billing-operations.md` for permissions, office workflows, tax configuration boundaries and export semantics.
- `FinancialAuditEvent` is append-only. Plan/entitlement Admin edits require `manage_plans` and a reason. Manual activation/renewal requires `grant_premium`, refund approval requires `approve_refunds`; `manage_subscriptions` alone no longer grants either authority. Separate permissions cover financial views, document issuance, reconciliation, configuration review and CSV export. `configure_billing_roles` creates explicit managed groups but enrolls no users and grants no simulator access.
- A `RefundApproval` freezes approver/reason before financial confirmation. Confirmation uses that approval; an operator cannot implicitly approve without the new permission. Subscription-only refund actions cannot bypass the financial workflow for paid terms. Approval moves no money and revokes no entitlement by itself.
- `BillingConfiguration` requires explicit review before invoice issuance. No registration or tax treatment is assumed. `BillingDocument` freezes seller, customer/order reference, quote, net/tax/total, component breakdown, India financial year and actual invoice date. `DocumentSequence` and configuration/order locks provide unique per-year/per-kind numbers. Full-refund credit notes reference the original invoice and preserve its amounts and seller/tax snapshots. These are invoice-ready office records, not a statutory-compliance or filing integration.
- `Settlement` stores supplied gross/fees/fee-tax/net evidence with arithmetic constraints; no gateway charges or settlements are fabricated. `ReconciliationRecord` appends statement observations/corrections; latest payment/settlement status is derived while prior evidence remains immutable. CSVs cover sales, payments, refunds, fees/settlements and document-based tax summaries; downloads audit reason, date filters, row count and file digest.
- Financial/audit retention days and legal hold configure review eligibility, not automatic deletion. PostgreSQL history guards supplement ORM protections: immutable audit/document/refund/evidence rows reject updates/deletes, processing records allow only valid finalization transitions, and invoice counters advance monotonically. No new database, gateway, GST filing or general ledger is added.

## Question and taxonomy workflow

1. Staff create a master/draft through admin forms and Question services.
2. Edits create a new numbered revision and its language snapshot.
3. Review validates working content; publication selects its approved revision.
4. Consumers read the published pointer or an already-frozen approved revision.
5. Tag services synchronize current classification without rewriting historical content.
6. Descendant discovery includes secondary tags and deduplicates master IDs.
7. Taxonomy integrity audits inspect ancestry and compatibility assumptions.

## CSV/XLSX import workflow

1. Staff access `/admin/question-import/`; permission requirements depend on mode.
2. parse_upload accepts UTF-8 CSV/XLSX within byte/row/column/cell bounds.
3. Formula/error cells, macros and external-link workbooks are rejected.
4. staging stores owner-bound expiring JSON with token locks and version digests.
5. validate resolves selection, exams, language/translations, taxonomy and row errors.
6. Source-local translation groups need explicit approval of their current signature.
7. Corrections invalidate stale approvals; duplicate text warns rather than merging masters.
8. Missing named Parts/Modules/Chapters/Topics can be proposed under an existing Subject.
9. Preview resolution stages proposals; confirmation persists them atomically.
10. Row resolution never auto-creates Subjects; explicit privileged admin actions differ.
11. confirm_import rechecks owner/permissions, locks exams/taxonomy and revalidates.
12. It creates pending-review drafts, topic/exam/source links and optional draft paper rows.
13. ImportBatch/ImportedQuestion retain original/corrected/resolved audit metadata.
14. Staging tokens and file/context uniqueness prevent duplicate confirmation/import.

Default bounds: 5 MB upload, 2,000 rows, 64 columns, 32,000 characters per cell.
Staging defaults to two hours; its configured root is private server-side storage.
General mode creates no paper. Previous-Year mode targets one unpublished paper/exam.
Import does not silently publish questions; review/publication remain explicit.

## Previous-Year and General collections

- PreviousYearPaper belongs to an Exam with optional Stage/Subject/configuration metadata.
- PaperQuestion binds a master to a fixed approved revision, number and display order.
- Paper constraints prevent duplicate master/order/number associations within a paper.
- The controlled _import_draft path can attach draft questions to unpublished import papers.
- Paper publication checks nonempty rows, membership and declared counts under locks.
- Published paper editing requires unpublication; old approved references remain historical.
- Public browsing is Exam -> Year -> Paper -> direct-answer or paper-practice mode.
- paper_answer gives reader feedback without creating persistent PracticeSession records.
- GeneralQuestionBatch is an ImportBatch proxy filtered to general-mode collections.
- General public views expose published questions; staff actions check signed fingerprints.
- transition_batch atomically reviews/publishes the inspected working revisions.

## Mock Test workflow

M1 adds `ExamPattern.is_free_demo` and immutable `MockSet`/`MockSetQuestion` publications. Publishing draws once through the existing selector and freezes pattern configuration, question/revision IDs, sequence and marks. A conditional database constraint permits one active demo per exam across stages. Free users copy this publication into separate attempts and can retake it without limit; Premium keeps selecting through the existing rules. New starts recheck publication/exam membership without substituting other questions. Nullable `MockAttempt.mock_set` links new Free attempts; old attempts/subscriptions remain unchanged. See `docs/shared-free-mock.md` for Admin workflow, replacement/retirement, database guards and upgrade tests.

1. Admin configures ExamPattern, sections, totals, duration and marking defaults.
2. Optional SectionSelectionRule selects exactly one taxonomy scope and a quota.
3. Rules support normalized difficulty and random/manual choices with descendant tags.
4. ManualRuleQuestion records explicit ordered master choices.
5. Availability checks quotas/overlap; allocation prevents duplicates across sections.
6. Activation is explicit; active/previously attempted configurations have guarded edits.
7. start_attempt locks owner/configuration/candidates and rechecks eligibility.
8. MockAttempt freezes configuration/deadline; AttemptQuestion freezes revision/order/marks.
9. Resume keeps the existing open attempt rather than selecting a fresh set.
10. save_response checks owner, action, row, version, UUID token and position.
11. Retry recognition applies to the latest save token/version pair.
12. Conflicts return 409; finalized attempts reject changes; expiry is server-authoritative.
13. Finalization awards positive marks, subtracts penalties and scores unanswered rows zero.
14. It freezes totals/section results; active responses do not serialize answer keys.
15. expire_mock_attempts exists; external scheduling is not established by this scan.

refresh_attempt, status checks and relevant views can finalize elapsed attempts.
History uses frozen revisions/marking, not current taxonomy or mutable master answers.

## Practice and Revision sessions

- Practice UI: category/authority -> exam -> subject -> module -> difficulty -> session.
- Eligible module cards replace the old hierarchy-dropdown setup.
- Subjects without eligible modules can continue with the whole subject.
- Difficulty uses published values; unspecified difficulty is an explicit choice.
- The current UI defaults to up to ten questions per Free session (configurable), within the remaining lifetime quota; Premium retains all eligible questions at that level. Service counts/filter support remains.
- PracticeSession/PracticeQuestion persist revisions/order, answers and classification.
- submit_answer gives immediate feedback, locks the answer and auto-completes the last row.
- A repeated identical answer is safe; changing an answered row is rejected.
- SavedQuestion is unique per user/master, with note, timestamps, review count and mastery.
- Save/unsave are authenticated CSRF-protected POSTs with minimal JSON support.
- Bookmark permission can include owned frozen history; readable bank content is stricter.
- My Revision Bank lives under My account and in account-section navigation.
- Bank filters cover exam/hierarchy/mastery/sorting; unavailable rows show placeholders.
- Mark-reviewed is explicit; simply reading a page does not increment review_count.
- RevisionSession proxies PracticeSession with kind=revision, not another table/engine.
- Practice kind requires Exam/Subject; revision kind has null Exam/Subject/Topic.
- Revision supports all eligible bookmarks or filters plus an optional question limit.
- start_revision serializes/rechecks selection and reuses shared snapshot assembly.
- First-answer submission invokes record_review in the same transaction for revision kind.
- Refresh/retry/resume do not recount; the hook does not recreate removed bookmarks.
- Mastery is explicit and independent of correctness; completed results remain historical.
- Pause is navigation away; resume chooses the next unanswered row or explicit question link.
- Revision supports early completion with unanswered rows retained and incorrect-only results.

## Topic exploration and presentation boundaries

- Registered users can reach question-topic and related-scope routes under `/revision/`.
- Stored paths support skipped levels and primary/secondary topic associations.
- Scopes expand through Topic/Chapter/Module/Part/Subject; Subject includes unclassified rows.
- Discovery excludes the source master and filters by active Exam and published difficulty.
- Related pages paginate 20 rows and batch translations/tags/bookmark state.
- Revision eligibility withholds questions in the user's open mock attempts.
- Exploration also blocks a requested scope containing an owner's open-mock question.
- Brief user-row locks coordinate exploration rendering with Mock Test starts.
- Exploration uses live approved content; existing session snapshots remain frozen.
- Per-question Explore Topic controls were removed; routes/helpers remain implemented.
- Bookmarks use compact checkbox-style toggles; success prompts are commented out.
- Active Mock bookmark actions stay separate from review flags and autosave semantics.

## Integrity, known drift and verification limits

- Constraints, guarded model saves and row locks provide complementary integrity layers.
- Deferred primary-tag triggers require coherent pointer/tag state at transaction commit.
- Some reverse migrations intentionally reject data incompatible with older schemas.
- Attempts, Practice history and content snapshots have protected mutation/deletion paths.
- Historical decisions and mobile proposals are explicitly labeled; current guides consolidate earlier milestone wording.
- Legacy Practice forms/filter assets coexist with module/difficulty setup; verify consumers.
- No AI/external-learning integration or general mobile token API is configured.
- This reference is statically verified against source, URL mappings and migration operations.
- Runtime data, installed PostgreSQL version, deployment topology and job schedules are unverified.
- No tests, database commands, CSS builds or deployment checks were run for this documentation task.
