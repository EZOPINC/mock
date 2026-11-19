# Module Map

Find the owning app and read the relevant row only. Start with the listed entry point and inspect direct dependencies as needed. Use [architecture](architecture.md) for cross-app design and [development rules](DEVELOPMENT_RULES.md) for integrity and test guidance.

| Area | Start in source | Reference |
|---|---|---|
| Setup and routing | `config/settings.py`, `config/urls.py`, `config/admin.py` | [Setup](../README.md), [Environment](environment-configuration.md) |
| Home and navigation | `core/views.py`, `templates/core/home.html`, `templates/components/header.html` | [Design system](DESIGN_SYSTEM.md) |
| Accounts | `accounts/views.py`, `accounts/dashboard.py`, `accounts/urls.py` | [Architecture](architecture.md#app-boundaries) |
| Exam and subject taxonomy | `exams/models.py`, `exams/selectors.py`, `exams/admin.py` | [Flexible paths](flexible-taxonomy.md), [Exam import/export](exam-taxonomy.md), [Subject import/export](subject-taxonomy.md) |
| Question bank and editorial workflow | `questions/models.py`, `questions/services.py`, `questions/tagging.py`, `questions/admin.py` | [Multilingual storage](multilingual-questions.md), [Topic tags](multi-topic-questions.md), [Translation rollout](question-translation-rollout.md) |
| CSV/XLSX column and row validation | `imports/parsing.py`, `imports/validation.py`, `imports/translation_input.py`, `imports/pairing.py` | [CSV contract](import-contract.md) |
| Import confirmation and duplicate decisions | `imports/views.py`, `imports/services.py`, `imports/context.py`, `imports/duplicates.py`, `imports/sources.py`, `imports/staging.py` | [Staff import guide](import-guide.md) |
| General Questions workspace | `general_question/review_views.py`, `review_forms.py`, `review_services.py` in the same app. Whole batches use `general_question/services.py`. | [Workspace and rollback notes](question-workspace.md) |
| Previous-Year papers | `previous_year/models.py`, `previous_year/services.py`, `previous_year/views.py` | [Admin](previous-year-administration.md), [Paper reader](previous-year-viewer.md) |
| Exam appearances | `previous_year/appearance_input.py`, `previous_year/appearances.py`, `general_question/appearance_views.py` | [Import format](import-contract.md), [Staff verification](question-workspace.md) |
| Mock configuration and selection | `mock_tests/models.py`, `mock_tests/admin.py`, `mock_tests/rules.py`, `mock_tests/languages.py`, `mock_tests/services.py` | [Selection rules](mock-selection-rules.md), [Free Demo](shared-free-mock.md) |
| Mock attempts and scoring | `mock_tests/execution.py`, `mock_tests/views.py`, `static/js/mock-test.js` | [Execution](mock-test-execution.md) |
| Practice | `practice/discovery.py`, `practice/services.py`, `practice/views.py` | [Setup](practice-taxonomy.md), [Sessions](practice-sessions.md) |
| Revision Bank and related topics | `revision/services.py`, `revision/sessions.py`, `revision/selectors.py`, `revision/exploration.py` | [Saved questions](saved-questions.md), [Topic exploration](topic-exploration.md) |
| Billing and entitlements | `billing/usage.py`, `billing/lifecycle.py`, `billing/payments.py`, `billing/models.py` | [Billing operations](billing-operations.md), [Readiness](billing-readiness.md) |
| Billing finance and exports | `billing/accounting.py`, `billing/finance.py`, `billing/exports.py`, `billing/admin.py` | [Billing operations](billing-operations.md) |

## Shared boundaries

- Working and published revisions, translation assembly and publication live in `questions/services.py`. Change topic associations through `questions/tagging.py`. Mock and Practice share `questions/eligibility.py` and subject freshness rules.
- Shared reading components live in `templates/questions/` and `questions/templatetags/reading.py`. The staff workspace uses `templates/imports/base.html`, `static/css/question-workspace.css` and scoped JavaScript.
- Shared styles start in `assets/tailwind.css`. Compile with `tools/build_css.py` when editing compiled inputs. See the [UI checklist](UI_REGRESSION_CHECKLIST.md).
- Read [database design](database-design.md) or open the [Questions ERD](erd/questions-erd.html) for schema details. The ERD generator, `tools/generate_questions_erd.py`, inspects a migrated PostgreSQL database.
- Maintenance commands live in each app's `management/commands/` directory. Common ones are `audit_taxonomy`, `cleanup_import_staging` and `expire_mock_attempts`. Deployment schedules are environment-specific.
