# Module Map

Navigation reference verified against source on 2026-11-12; source overrides documentation.
Start with the owning app, then read only its listed files and direct dependencies.
Use `docs/architecture.md` for architecture context and `docs/DEVELOPMENT_RULES.md` for safety.

## Project entry points

| Location | Responsibility / starting point |
|---|---|
| `manage.py`, `requirements.txt` | Django commands and dependency bounds |
| `config/settings.py` | Apps, PostgreSQL, auth/languages, import bounds, security flags |
| `config/urls.py` | App mounts; custom import route precedes admin |
| `config/admin.py` | PlatformAdminSite/PlatformAdminConfig; taxonomy admin ordering |
| `config/asgi.py`, `config/wsgi.py` | Server entry points; deployment is not specified |
| `templates/base.html`, `templates/components/header.html` | Asset order, shell and account dropdown |
| `templates/components/icon.html`, `templates/questions/translations.html` | Shared SVGs and revision-bound bilingual rendering |
| `templates/questions/reading_question.html`, `reading_option.html`, `reading_explanations.html`, `questions/templatetags/reading.py` | Paired bilingual stems/options for timed attempts, finalized mock reviews, Practice and previous-year reader; one native radio per answer choice |
| `assets/tailwind.css`, `tools/build_css.py`, `tools/tailwind-lock.json` | CSS source, standalone build and pinned checksums |
| `assets/shell.css`, `tools/verify_membership_ui.py` | Shared membership navigation, home/auth/billing presentation; opt-in desktop/mobile Edge checks |
| `assets/design-system.css`, `assets/learning.css`, `assets/student.css`, `static/js/theme.js` | Semantic light/dark/sepia tokens, learning/account/public presentation and local appearance preference; `docs/DESIGN_SYSTEM.md`, `docs/UI_REGRESSION_CHECKLIST.md` |
| `static/css/site.css`, `static/css/bookmarks.css` | Fallback styles and submit-button-specific bookmark overrides |

## App ownership and route mounts

| App / namespace | Mount | Responsibility / dependency |
|---|---|---|
| `core` / root names | `/`, `/health/` | Curated catalogue; database readiness |
| `accounts` / `accounts` | `/accounts/` | Custom user, session authentication, dashboards |
| `exams` / `exams` | `/exam-authorities/` | Active catalogue and normalized taxonomy |
| `questions` | Admin/downstream views | Master content, approval, translations, tags, eligibility |
| `imports` / `imports` | `/admin/question-import/` | Staff ingestion -> Question workflows / optional paper rows |
| `previous_year` / `previous_year` | `/previous-year/` | Publication/reader -> approved QuestionRevision |
| `general_question` / `general_questions` | `/general-questions/` | ImportBatch proxy collections -> review/publication |
| `mock_tests` / `mock_tests` | `/mock-tests/` | Patterns/rules -> timed snapshots and scoring |
| `practice` / `practice` | `/practice/` | Module difficulty/language setup -> shared untimed engine |
| `revision` / `revision` | `/revision/` | Personal bank, Practice proxy sessions, topic discovery |
| `billing` / `billing` | `/billing/`, Admin | Pricing, test checkout/status, financial ledger, Premium lifecycle, Free allocations |


## Documentation lookup

| Need | Current reference |
|---|---|
| Setup and implemented entry points | `README.md` |
| Model inventory / persistence constraints | `docs/database-design.md` |
| Decision rationale / superseded rules | `docs/decisions.md` (historical status summary, not a roadmap gate) |
| Import fields vs staff workflow | `docs/import-contract.md`, `docs/import-guide.md` |
| Practice setup vs shared engine | `docs/practice-taxonomy.md`, `docs/practice-sessions.md` |
| Personal bank/sessions / live discovery | `docs/saved-questions.md`, `docs/topic-exploration.md` |
| Current UI / historical summary | `docs/ui-foundation.md`, `docs/ui-migration-summary.md` |
| Mobile contracts | `docs/mobile-readiness.md` (proposals only) |

## Models and data ownership

| File | Important classes / relationships |
|---|---|
| `accounts/models.py` | User(AbstractUser); AUTH_USER_MODEL |
| `billing/models.py` | SubscriptionPlan, PlanEntitlement, UserSubscription, SubscriptionEvent, FreeExamSelection, FreeMockSelection, FreeQuestionUsage; Free fallback is service logic |
| `billing/models.py` financial ledger | PaymentOrder, PaymentTransaction, PaymentEvent, Refund; protected references and quote snapshots |
| `billing/models.py` financial operations | FinancialAuditEvent, BillingConfiguration, BillingDocument, DocumentSequence, RefundApproval, Settlement, ReconciliationRecord |
| `exams/models.py` | ExamAuthority, Exam (optional admin-editable public description), ExamStage, Subject, Part, Module, Chapter, Topic; HierarchyNode validates ancestry |
| `questions/models.py` | Question, QuestionRevision, QuestionTranslation, QuestionTopic, QuestionExam, QuestionSource, QuestionSourceReference |
| Questions ERD | `docs/erd/questions-erd.html` (offline interactive), `docs/erd/questions-erd.md` (Mermaid/column reference), `questions-schema.json` and `.mmd` sources in that directory; regenerate with `python tools/generate_questions_erd.py` using `tools/questions_erd_template.html` |
| `imports/models.py` | ImportBatch, ImportedQuestion; contextual import uniqueness and row audit |
| `previous_year/models.py` | PreviousYearPaper, PaperQuestion; revision/order and paper invariants |
| `general_question/models.py` | GeneralQuestionBatch proxy over general ImportBatch rows |
| `mock_tests/models.py` | ExamPattern (is_free_demo), ExamPatternSection, SectionSelectionRule, ManualRuleQuestion, MockSet, MockSetQuestion, MockAttempt, AttemptQuestion |
| `practice/models.py` | PracticeSession, PracticeQuestion, PracticeQuerySet; kind/scope and immutable snapshots |
| `revision/models.py` | SavedQuestion; RevisionSession proxy and revision-only manager |

## Shared service interfaces

| File | Entry points to reuse |
|---|---|
| `questions/services.py` | create_question, create_revision, add_translation, mark_reviewed, publish_question, published_questions, get_published_revision |
| `questions/tagging.py` | set_question_topics(question, topic_ids, primary_topic_id=...); save_tag/delete_tag |
| `questions/eligibility.py` | eligible_question_ids(exam_id, subject_id=..., topic_id=..., language_mode=..., question_ids=...) -> ID set |
| `questions/selectors.py` | questions_by_topics(topic_ids, queryset=...) -> distinct masters |
| `exams/selectors.py` | active_authorities, active_exams, subjects_for_exam; membership is not full eligibility |
| Exam catalogue backup/restore | `exams/exam_taxonomy.py`, `exams/management/commands/export_exam_taxonomy.py`, `import_exam_taxonomy.py`; `docs/exam-taxonomy.md`, `Data/Exams/exam_taxonomy.json`; code-scoped Authority → Exam → Stage, separate from subjects |
| All-subject taxonomy backup | `exams/subject_taxonomy.py`: export_taxonomy; `exams/management/commands/export_subject_taxonomy.py`; restore with existing import_subject_taxonomy and optional --create-subjects; `exams/test_subject_taxonomy_export.py`, `docs/subject-taxonomy.md` |
| Bulk subject-file imports | `exams/management/commands/import_subject_taxonomies.py`; sorted Data/Subjects JSON files, per-file transactions, JSONL results logs, dry-run and backup exclusion; `exams/test_bulk_subject_taxonomy.py`, `docs/subject-taxonomy.md` |
| Sub-module spelling/first attachment repair | `exams/subject_taxonomy.py`: normalize_taxonomy accepts sub_modules aliases and rejects unknown fields; --attach-submodules supports first same-Module assignment; `exams/migrations/0009_chapter_initial_submodule_assignment.py` guards |
| Explicit Module Part correction | `exams/management/commands/reassign_module_part.py`; preview default, exact source/destination codes, transactional model save with scoped DB authorization in `exams/migrations/0010_explicit_module_part_reassignment.py`; `exams/test_module_part_reassignment.py` |
| Optional Sub-module | `exams/models.py`: Submodule and Chapter.submodule; `exams/migrations/0008_optional_submodule.py` guards; JSON/CSV contracts in `docs/subject-taxonomy.md` and `docs/import-contract.md`; Practice/revision traversal and mock ancestor rules include this level |
| Unused old taxonomy purge | `exams/taxonomy_purge.py`, `exams/management/commands/purge_subject_taxonomy.py`; explicit subjects + old-code manifest, preview default, block external references, transactional apply; `exams/test_taxonomy_purge.py` |
| `exams/integrity.py` | taxonomy_integrity_counts; audit command consumes it |
| `imports/parsing.py` | parse_upload, columns_for, preview_page_size; bounded CSV/XLSX |
| `imports/translation_input.py`, `imports/language.py` | normalize_translations, normalize_language, infer_language |
| `imports/taxonomy.py`, `imports/pairing.py` | TaxonomyCatalogue.resolve/propose/persist; groups_for approval signatures |
| `imports/validation.py`, `imports/context.py` | validate, selection, row_exams; mode, exam_ids, context_hash |
| `imports/staging.py`, `imports/permissions.py` | create/load/save/locked/digest/cleanup; require_import_permission |
| `imports/services.py` | confirm_import(data, user); owner/permission checks, locks, revalidation, atomic audit/writes |
| `previous_year/services.py` | publish_paper, unpublish_paper, published_papers |
| `general_question/services.py` | general_batches, batch_questions, fingerprint, transition_batch, require_batch_permission |
| `mock_tests/services.py` | validate_configuration, activate_pattern, deactivate_pattern, publish_free_demo, retire_free_demo, available_patterns, select_questions, start_attempt |
| `mock_tests/rules.py` | eligible_for_rule, validate_rule_layout, selection_tasks, rule_snapshot |
| `mock_tests/languages.py` | Mock-only eligibility: English/Bengali sections require both published translations |
| `mock_tests/execution.py` | refresh_attempt, save_response, submit_attempt, confirmation_counts |
| `practice/discovery.py` | PracticeTaxonomy.selected_ids/snapshot/options; difficulty_pools, configuration_matches |
| `practice/services.py` | start_session (incremental Free default batches), assemble_session, submit_answer, abandon_session, complete_session, progress, performance |
| `revision/services.py` | can_save, set_saved(user, question_id, saved=...), attach_saved_state |
| `revision/selectors.py` | visible_questions, bank_rows, bank_counts, topic_scope, filter_bank, with_question_content, hydrate_content |
| `revision/sessions.py` | request_spec, start_revision(user, parameters), record_review |
| `revision/exploration.py` | taxonomy_path, question_paths, related_questions, scope_has_open_mock, filter_related |
<<<<<<< HEAD
| `accounts/dashboard.py` | dashboard_context; ordinary Practice stats exclude revision kind |
| `billing/services.py` | subscription_for, plan_for, evaluate_access, mock_access, practice_access, revision_access, require_access; generic feature policy |
| `billing/usage.py` | reserve_mock, practice_pool, record_practice; account-locked Free lifetime allocations inside Mock/Practice start transactions |
| `billing/lifecycle.py` | activate_subscription, renew_subscription, expire_subscription, revoke_subscription, revoke_for_full_refund; permission-gated, audited, idempotent term writes |
| `billing/payments.py`, `billing/providers.py` | create_order, process_payment_event, simulate_payment, replay_payment_event; PaymentProvider interface and guarded simulated provider |
| `billing/accounting.py`, `billing/finance.py`, `billing/audit.py` | Reviewed seller/tax/retention configuration, invoice/credit-note issuance, refund approvals, settlements, reconciliation corrections, append-only audit |
| `billing/exports.py`, `billing/roles.py` | Accounting CSV exports with audit digests; configure_roles via configure_billing_roles command; no user enrollment |
| `billing/providers.py`, `billing/admin.py`, `billing/tests.py` | Future verification contract, permission-controlled staff configuration, targeted model/policy tests |
=======
| `accounts/dashboard.py` | dashboard_context; ordinary Practice stats exclude revision kind; bounded resume/recent records and Revision bank counts, eight read queries |
>>>>>>> a8835ecec8eee5751ea49cdb3c48ba1f5772da32

## Views, forms, admin and templates

| App | Files / symbols / UI |
|---|---|
| `core` | `core/views.py`: home/health; `core/urls.py`; `templates/core/home.html` |
| `billing` | `billing/views.py`, `billing/urls.py`: pricing, checkout, status, confirmation and authorized POST-only simulation; `templates/billing/`; read-only ledger Admin with guarded test controls |
| `accounts` | `accounts/views.py`: RegisterView/ProfileView/LearningSpaceView; `accounts/forms.py`: RegistrationForm; `accounts/urls.py`, `accounts/admin.py`; `templates/accounts/` |
| `exams` | `exams/views.py`: authorities/exam_list/exam_detail; `exams/urls.py`, `exams/admin.py`; taxonomy inlines use a request-field budget and filtered overflow links in `templates/admin/exams/taxonomy_change_form.html`; `templates/exams/` |
| `questions` | `questions/admin.py`: QuestionAdmin/QuestionRevisionAdmin; `questions/forms.py`: RevisionForm/TranslationForm/QuestionAdminForm/NewQuestionAdminForm; `templates/questions/` |
| `imports` | `imports/views.py`: upload/preview/confirm/cancel/complete; `imports/forms.py`: UploadForm/ImportSubjectForm/ImportTopicForm; `imports/urls.py`, `imports/admin.py`; `templates/imports/` |
| `previous_year` | `previous_year/views.py`: paper_list/paper_year/paper_context/paper_detail/paper_answer; `previous_year/forms.py`: PaperSelectionForm; `previous_year/urls.py`, `previous_year/admin.py`: paper forms retain small question inlines, replace oversized formsets with a filtered/paginated PaperQuestionAdmin link; child edits retain parent permissions/publication guards; `templates/admin/previous_year/previousyearpaper/change_form.html`, `templates/previous_year/`; `previous_year/test_admin_field_budget.py` |
| `general_question` | `general_question/views.py`: index/collection/manage/manage_batch; `general_question/forms.py`: GeneralQuestionFilters; topic dropdowns share `exams/selectors.py`: topics_with_ancestry with imports to avoid per-label parent queries; `general_question/urls.py`, `general_question/admin.py`; `templates/general_question/` |
| `mock_tests` | `mock_tests/views.py`: test_start/attempt_detail/save_answer/attempt_status/confirm_submit/results; `mock_tests/urls.py`; inline forms in `mock_tests/admin.py`; `templates/mock_tests/` |
| `practice` | `practice/views.py`: configure/difficulty/question_context/session_view/answer/summary; `practice/forms.py`: PracticeDifficultyForm and legacy PracticeStartForm; `practice/urls.py`; `templates/practice/` |
| Revision bank | `revision/views.py`: bookmark/dashboard/detail/manage/remove; `revision/forms.py`: BankFilters/NoteForm/RevisionStartForm; `templates/revision/dashboard.html`, `templates/revision/detail.html` |
| Revision sessions | `revision/session_views.py`: start/history/session_view/answer/mastery/finish/results; `templates/revision/session.html`, `templates/revision/session_body.html`, `templates/revision/results.html` |
| Topic exploration | `revision/exploration_views.py`: question_topics/explore; `revision/exploration_forms.py`: RelatedFilters; `templates/revision/question_topics.html`, `templates/revision/explore.html` |
| Shared bookmark | `revision/templatetags/revision_tags.py`: bookmark_control; `templates/revision/bookmark.html`, `static/js/bookmarks.js`, `static/css/bookmarks.css` |

Practice and Revision have no dedicated admin.py; not every app has every conventional file.
Explore routes/helpers remain; per-question explore_control calls were removed from cards.

## Frontend and endpoint contracts

| UI change | Starting files / constraints |
|---|---|
| Account/header nav | `templates/components/header.html`, `templates/accounts/account_navigation.html`, `static/js/navigation.js`; bank is under My account |
| Bilingual options/solutions | `templates/questions/translations.html`, `templates/questions/selectable_option.html`; no active-mock keys |
| Practice/Revision question panel | `templates/practice/question_panel.html`; keep shared answer/bookmark forms unnested |
| Practice/Revision reading and feedback | `templates/practice/reading_panel.html`, included by question_panel for both engines; Revision retains data-revision-answer; `tools/verify_exam_ui.py`, `tools/verify_learning_ui.py` check student journeys |
| Mock execution | `templates/mock_tests/attempt.html`, `static/js/mock-test.js`, `static/css/mock-test.css`; save/version/timer contracts |
| Practice setup | `templates/practice/subjects.html`, `templates/practice/configure.html`, `templates/practice/difficulty.html`; subject then module then difficulty/language |
| Practice feedback | `templates/practice/session.html`, `static/js/practice-ui.js`, `static/css/practice.css` |
| Revision AJAX feedback | `templates/revision/session_body.html`, `static/js/revision-session.js`; native POST fallback |
| Paper modes/feedback | `templates/previous_year/paper_detail.html`, `static/js/paper-practice.js`, `static/css/paper-modes.css` |
| Paper reading/navigation | `templates/previous_year/reading_solutions.html`, `static/js/paper-reader.js`; opt-in browser check: `tools/verify_exam_ui.py` |
| General Questions translation inspection | `templates/general_question/collection.html`, `solution.html`; shared reading helper's opt-in `reserve_editions` keeps empty English/Bengali slots in public collections and staff working-revision review |
| Import preview/edit | `templates/imports/preview.html`, `static/js/import-preview.js`, `static/js/import-upload.js`, `static/css/imports.css` |
| Shared icon/style | `templates/components/icon.html`, `assets/tailwind.css`; do not hand-edit compiled Tailwind |
| Bookmark labels/status | `templates/revision/bookmark.html`, `static/js/bookmarks.js`; success announcements use the existing visually hidden live region |

Mock save JSON uses action/version/UUID token/position and answer-row/review fields.
Bookmark routes use master IDs; session answer routes use PracticeQuestion row IDs.
Mock autosave question_id identifies an AttemptQuestion row, not a master Question.
Bookmark JSON has question_id and saved only; HTML redirects validate local next.
Revision detail/remove uses owner-scoped SavedQuestion IDs, not master IDs.
Explore uses kind/node ID with from_question, exam and prefixed difficulty parameters.

## Common task -> smallest useful inspection set

| Task | Read first | Direct dependency / tests |
|---|---|---|
| Question editing/publication | `questions/services.py`, `questions/models.py`, `questions/admin.py` | `questions/test_multilingual.py`, `questions/tests.py` |
| Subject Admin taxonomy lists | `exams/admin.py`: PartInline/ModuleInline/ChapterInline/TopicInline | `exams/test_admin_taxonomy.py`; existing taxonomy admin tests |
| Taxonomy/tag paths | `exams/models.py`, `questions/tagging.py` | `exams/test_flexible_taxonomy.py`, `questions/test_topic_tags.py`; trigger migrations |
| Import columns/matching | `imports/parsing.py`, `imports/translation_input.py`, `imports/taxonomy.py`, `imports/validation.py` | `imports/test_taxonomy_import.py`, `imports/test_wide_format.py` |
| Import confirmation | `imports/services.py`, `imports/staging.py`, `imports/context.py` | `imports/tests.py`, `imports/test_unified.py` |
| Paper publication/reader | `previous_year/services.py`, `previous_year/models.py`, `previous_year/views.py` | `previous_year/test_modes.py`, `previous_year/tests.py` |
| Mock quotas/selection | `mock_tests/rules.py`, `mock_tests/services.py`, `mock_tests/models.py` | `mock_tests/test_selection_rules.py`, `mock_tests/test_attempts.py` |
| Shared Free Mock Demo | `mock_tests/models.py`, `mock_tests/services.py`, `mock_tests/admin.py`, `billing/usage.py` | `mock_tests/test_free_demo.py`; `docs/shared-free-mock.md`; additive migrations mock_tests 0007–0008 |
| Free Mock/Practice limits | `billing/usage.py`, `billing/models.py`, Mock/Practice start services | `billing/test_usage.py`; Mock/Practice concurrency and Previous-Year regressions |
| Premium lifecycle/Admin grants | `billing/lifecycle.py`, `billing/models.py`, `billing/admin.py`, `billing/forms.py` | `billing/test_lifecycle.py`; billing regression and migration tests |
| Simulated checkout/financial ledger | `billing/payments.py`, `billing/providers.py`, `billing/views.py`, `billing/models.py` | `billing/test_payments.py`; config fail-closed, ownership, CSRF, idempotency and PostgreSQL concurrency tests |
| Financial Admin/audit/exports | `billing/admin.py`, `billing/finance_forms.py`, `billing/accounting.py`, `billing/finance.py`, `billing/exports.py` | `billing/test_finance.py`; migrations 0008 operations models, 0009 PostgreSQL history guards; `docs/billing-operations.md` |
| Mock save/scoring | `mock_tests/execution.py`, `mock_tests/views.py`, `static/js/mock-test.js` | `mock_tests/test_execution.py` |
| Practice selection/feedback | `practice/discovery.py`, `practice/services.py`, `practice/views.py` | `practice/test_taxonomy.py`, `practice/test_difficulty.py`, `practice/tests.py` |
| Incremental Free Practice allocation | `practice/services.py`, `billing/usage.py`, `config/settings.py`: PRACTICE_FREE_SESSION_SIZE | `practice/test_incremental.py`; `docs/practice-sessions.md`; existing Free exam/usage models, no migration |
| Bank/bookmarks | `revision/views.py`, `revision/services.py`, `revision/selectors.py` | `revision/tests.py`, `revision/test_bank.py` |
| Revision sessions | `revision/sessions.py`, `revision/session_views.py`, `practice/services.py` | `revision/test_sessions.py`; Practice regressions |
| Topic discovery | `revision/exploration.py`, `revision/exploration_views.py` | `revision/test_exploration.py`; current visibility policy |
| Authentication/account pages | `accounts/views.py`, `accounts/urls.py`, `accounts/dashboard.py` | `accounts/test_authentication.py`, `accounts/test_account_sections.py`, `accounts/test_dashboard.py` |
| Home catalogue | `core/views.py`, `templates/core/home.html` | `core/test_homepage.py`, `core/test_navigation.py` |

## Schema and maintenance navigation

| Concern | Migration or command path |
|---|---|
| Flexible paths/parent guards | `exams/migrations/0004_flexible_academic_taxonomy.py` |
| Initial Module Part assignment | `exams/migrations/0006_module_initial_part_assignment.py`; same-subject null-to-Part only |
| Initial Chapter Module assignment | `exams/migrations/0007_chapter_initial_module_assignment.py`; same-subject root-to-Module only; importer requires `--attach-unassigned-chapters` |
| Translation backfill | `questions/migrations/0003_backfill_translations.py` |
| Deferred primary-tag checks | `questions/migrations/0005_primary_topic_compatibility.py` |
| Import context/audit compatibility | `imports/migrations/0002_unified_import.py` |
| Mock deadline/backfill constraints | `mock_tests/migrations/0004_backfill_attempt_deadlines.py`, `mock_tests/migrations/0005_mockattempt_mock_attempt_deadline_valid_and_more.py` |
| Advanced selection rules | `mock_tests/migrations/0006_sectionselectionrule_manualrulequestion_and_more.py` |
| Shared revision scope | `practice/migrations/0002_practicesession_kind_alter_practicesession_exam_and_more.py`, `revision/migrations/0003_revisionsession.py` |
| Taxonomy audit | `exams/management/commands/audit_taxonomy.py` |
| Subject taxonomy JSON import | `exams/subject_taxonomy.py`, `exams/management/commands/import_subject_taxonomy.py`; format: `docs/subject-taxonomy.md` |
| Staging cleanup | `imports/management/commands/cleanup_import_staging.py` |
| Mock expiry | `mock_tests/management/commands/expire_mock_attempts.py` |

Commands exist; external scheduling and live migration state were not verified here.
