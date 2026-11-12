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
| `assets/tailwind.css`, `tools/build_css.py`, `tools/tailwind-lock.json` | CSS source, standalone build and pinned checksums |
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
| `exams/models.py` | ExamAuthority, Exam, ExamStage, Subject, Part, Module, Chapter, Topic; HierarchyNode validates ancestry |
| `questions/models.py` | Question, QuestionRevision, QuestionTranslation, QuestionTopic, QuestionExam, QuestionSource, QuestionSourceReference |
| `imports/models.py` | ImportBatch, ImportedQuestion; contextual import uniqueness and row audit |
| `previous_year/models.py` | PreviousYearPaper, PaperQuestion; revision/order and paper invariants |
| `general_question/models.py` | GeneralQuestionBatch proxy over general ImportBatch rows |
| `mock_tests/models.py` | ExamPattern, ExamPatternSection, SectionSelectionRule, ManualRuleQuestion, MockAttempt, AttemptQuestion |
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
| `exams/integrity.py` | taxonomy_integrity_counts; audit command consumes it |
| `imports/parsing.py` | parse_upload, columns_for, preview_page_size; bounded CSV/XLSX |
| `imports/translation_input.py`, `imports/language.py` | normalize_translations, normalize_language, infer_language |
| `imports/taxonomy.py`, `imports/pairing.py` | TaxonomyCatalogue.resolve/propose/persist; groups_for approval signatures |
| `imports/validation.py`, `imports/context.py` | validate, selection, row_exams; mode, exam_ids, context_hash |
| `imports/staging.py`, `imports/permissions.py` | create/load/save/locked/digest/cleanup; require_import_permission |
| `imports/services.py` | confirm_import(data, user); owner/permission checks, locks, revalidation, atomic audit/writes |
| `previous_year/services.py` | publish_paper, unpublish_paper, published_papers |
| `general_question/services.py` | general_batches, batch_questions, fingerprint, transition_batch, require_batch_permission |
| `mock_tests/services.py` | validate_configuration, activate_pattern, deactivate_pattern, available_patterns, select_questions, start_attempt |
| `mock_tests/rules.py` | eligible_for_rule, validate_rule_layout, selection_tasks, rule_snapshot |
| `mock_tests/languages.py` | Mock-only eligibility: English/Bengali sections require both published translations |
| `mock_tests/execution.py` | refresh_attempt, save_response, submit_attempt, confirmation_counts |
| `practice/discovery.py` | PracticeTaxonomy.selected_ids/snapshot/options; difficulty_pools, configuration_matches |
| `practice/services.py` | start_session, assemble_session, submit_answer, abandon_session, complete_session, progress, performance |
| `revision/services.py` | can_save, set_saved(user, question_id, saved=...), attach_saved_state |
| `revision/selectors.py` | visible_questions, bank_rows, bank_counts, topic_scope, filter_bank, with_question_content, hydrate_content |
| `revision/sessions.py` | request_spec, start_revision(user, parameters), record_review |
| `revision/exploration.py` | taxonomy_path, question_paths, related_questions, scope_has_open_mock, filter_related |
| `accounts/dashboard.py` | dashboard_context; ordinary Practice stats exclude revision kind |

## Views, forms, admin and templates

| App | Files / symbols / UI |
|---|---|
| `core` | `core/views.py`: home/health; `core/urls.py`; `templates/core/home.html` |
| `accounts` | `accounts/views.py`: RegisterView/ProfileView/LearningSpaceView; `accounts/forms.py`: RegistrationForm; `accounts/urls.py`, `accounts/admin.py`; `templates/accounts/` |
| `exams` | `exams/views.py`: authorities/exam_list/exam_detail; `exams/urls.py`, `exams/admin.py`; SubjectAdmin lists PartInline/ModuleInline/ChapterInline/TopicInline using standard Django Admin; `templates/exams/` |
| `questions` | `questions/admin.py`: QuestionAdmin/QuestionRevisionAdmin; `questions/forms.py`: RevisionForm/TranslationForm/QuestionAdminForm/NewQuestionAdminForm; `templates/questions/` |
| `imports` | `imports/views.py`: upload/preview/confirm/cancel/complete; `imports/forms.py`: UploadForm/ImportSubjectForm/ImportTopicForm; `imports/urls.py`, `imports/admin.py`; `templates/imports/` |
| `previous_year` | `previous_year/views.py`: paper_list/paper_year/paper_context/paper_detail/paper_answer; `previous_year/forms.py`: PaperSelectionForm; `previous_year/urls.py`, `previous_year/admin.py`; `templates/previous_year/` |
| `general_question` | `general_question/views.py`: index/collection/manage/manage_batch; `general_question/forms.py`: GeneralQuestionFilters; `general_question/urls.py`, `general_question/admin.py`; `templates/general_question/` |
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
| Mock execution | `templates/mock_tests/attempt.html`, `static/js/mock-test.js`, `static/css/mock-test.css`; save/version/timer contracts |
| Practice setup | `templates/practice/subjects.html`, `templates/practice/configure.html`, `templates/practice/difficulty.html`; subject then module then difficulty/language |
| Practice feedback | `templates/practice/session.html`, `static/js/practice-ui.js`, `static/css/practice.css` |
| Revision AJAX feedback | `templates/revision/session_body.html`, `static/js/revision-session.js`; native POST fallback |
| Paper modes/feedback | `templates/previous_year/paper_detail.html`, `static/js/paper-practice.js`, `static/css/paper-modes.css` |
| Import preview/edit | `templates/imports/preview.html`, `static/js/import-preview.js`, `static/js/import-upload.js`, `static/css/imports.css` |
| Shared icon/style | `templates/components/icon.html`, `assets/tailwind.css`; do not hand-edit compiled Tailwind |
| Bookmark labels/status | `templates/revision/bookmark.html`, `static/js/bookmarks.js`; success announcements currently commented out |

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
| Mock save/scoring | `mock_tests/execution.py`, `mock_tests/views.py`, `static/js/mock-test.js` | `mock_tests/test_execution.py` |
| Practice selection/feedback | `practice/discovery.py`, `practice/services.py`, `practice/views.py` | `practice/test_taxonomy.py`, `practice/test_difficulty.py`, `practice/tests.py` |
| Bank/bookmarks | `revision/views.py`, `revision/services.py`, `revision/selectors.py` | `revision/tests.py`, `revision/test_bank.py` |
| Revision sessions | `revision/sessions.py`, `revision/session_views.py`, `practice/services.py` | `revision/test_sessions.py`; Practice regressions |
| Topic discovery | `revision/exploration.py`, `revision/exploration_views.py` | `revision/test_exploration.py`; current visibility policy |
| Authentication/account pages | `accounts/views.py`, `accounts/urls.py`, `accounts/dashboard.py` | `accounts/test_authentication.py`, `accounts/test_account_sections.py`, `accounts/test_dashboard.py` |
| Home catalogue | `core/views.py`, `templates/core/home.html` | `core/test_homepage.py`, `core/test_navigation.py` |

## Schema and maintenance navigation

| Concern | Migration or command path |
|---|---|
| Flexible paths/parent guards | `exams/migrations/0004_flexible_academic_taxonomy.py` |
| Translation backfill | `questions/migrations/0003_backfill_translations.py` |
| Deferred primary-tag checks | `questions/migrations/0005_primary_topic_compatibility.py` |
| Import context/audit compatibility | `imports/migrations/0002_unified_import.py` |
| Mock deadline/backfill constraints | `mock_tests/migrations/0004_backfill_attempt_deadlines.py`, `mock_tests/migrations/0005_mockattempt_mock_attempt_deadline_valid_and_more.py` |
| Advanced selection rules | `mock_tests/migrations/0006_sectionselectionrule_manualrulequestion_and_more.py` |
| Shared revision scope | `practice/migrations/0002_practicesession_kind_alter_practicesession_exam_and_more.py`, `revision/migrations/0003_revisionsession.py` |
| Taxonomy audit | `exams/management/commands/audit_taxonomy.py` |
| Staging cleanup | `imports/management/commands/cleanup_import_staging.py` |
| Mock expiry | `mock_tests/management/commands/expire_mock_attempts.py` |

Commands exist; external scheduling and live migration state were not verified here.
