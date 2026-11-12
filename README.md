# Mock Exam Platform

A modular Django 5.2/PostgreSQL application with a centralized multilingual Question
Bank, Previous-Year Papers, timed Mock Tests, untimed Practice Sets and a personal
Revision Bank. Django Templates, Tailwind CSS and vanilla JavaScript provide the UI.

## Start here

| Need | Reference |
|---|---|
| Find the owning app, service or test | [Module map](docs/MODULE_MAP.md) |
| Understand app boundaries and workflows | [Architecture](docs/architecture.md) |
| Change code safely / select targeted checks | [Development rules](docs/DEVELOPMENT_RULES.md), [Codex instructions](AGENTS.md) |
| Inspect persistence and constraints | [Database design](docs/database-design.md) |
| Understand prior choices and supersession | [Decision record](docs/decisions.md) |
| Configure environment values | [Environment configuration](docs/environment-configuration.md) |

These references describe current source. Historical milestones and proposed mobile
contracts are not evidence of missing functionality or authorization for new work.

## Local setup (PowerShell)

Use a Python version compatible with Django 5.2 and a local PostgreSQL server.
There is no SQLite fallback. Dependencies are bounded in `requirements.txt`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Put the generated key in DJANGO_SECRET_KEY and configure your own PostgreSQL login
in .env. Never commit .env. Process environment values take precedence over .env.
See the environment guide for development/production flags; no local values are
included in this document.

In psql, a PostgreSQL administrator can create a dedicated local development role
and database. The password prompt avoids embedding a password in SQL:

```sql
CREATE ROLE mock_exam LOGIN CREATEDB;
\password mock_exam
CREATE DATABASE mock_exam OWNER mock_exam;
```

CREATEDB is needed for the development/test role because Django creates a separate
test database. The role also needs access to PostgreSQL's maintenance database.
Do not give a production runtime role test-database privileges unnecessarily.

```powershell
python manage.py check
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/ and /admin/. There is no default administrator.
GET /health/ checks database readiness and returns 200 or 503 without connection details.
Enable DJANGO_DEBUG only locally. With debug disabled, session/CSRF cookies require HTTPS.
Timezone defaults to UTC; timestamps are timezone-aware. collectstatic uses STATIC_ROOT.

## Implemented workflows and access

| Workflow | Current behavior |
|---|---|
| Catalogue | Public active authorities/exams; shared Subject/Part/Module/Chapter/Topic taxonomy |
| Question Bank | Master questions with immutable revision-bound English/Bengali content; explicit review/publication |
| Imports | Staff CSV/XLSX upload, preview correction/pairing, atomic confirmation and audit at /admin/question-import/ |
| Previous-Year Papers | Public published papers; direct answers or temporary paper-practice feedback |
| General collections | Public published import collections; permissioned whole-batch review/publication |
| Mock Tests | Authenticated fixed attempts, server deadlines, autosave, review flags and frozen scoring |
| Practice Sets | Authenticated exam/subject -> module -> difficulty -> persistent untimed feedback |
| Revision Bank | Authenticated notes/mastery, filters, saved-question sessions and historical results |
| Topic exploration | Registered-user scoped related questions; protected during open mocks; routes remain but card controls were removed |

Profile at /accounts/profile/ shows account details; /accounts/learning-space/ shows
learning activity. My Revision Bank is under the My account dropdown and the account
section navigation. Registration/login preserve safe next destinations; logout is POST.
Question cards use compact Save for revision controls. Save/remove success prompts
are currently commented out; error feedback remains active.

## Focused operational references

- [Import contract](docs/import-contract.md) and [import guide](docs/import-guide.md).
- [Flexible taxonomy](docs/flexible-taxonomy.md) and [topic tags](docs/multi-topic-questions.md).
- [Mock selection rules](docs/mock-selection-rules.md) and [execution](docs/mock-test-execution.md).
- [Practice engine](docs/practice-sessions.md) and [Practice setup](docs/practice-taxonomy.md).
- [Revision Bank/sessions](docs/saved-questions.md) and [topic exploration](docs/topic-exploration.md).
- [UI foundation](docs/ui-foundation.md); [future mobile proposal](docs/mobile-readiness.md).

## Checks and stylesheet builds

Start with the owning app's targeted tests from DEVELOPMENT_RULES.md. Examples:

```powershell
python manage.py test practice --noinput
python manage.py test revision --noinput
python manage.py test mock_tests.test_execution --noinput
python manage.py makemigrations --check --dry-run
```

Use the full test suite only when scope/failures justify it. Tests require PostgreSQL
and create a separate test database; test results are not implied by these commands.

```powershell
python tools/build_css.py
python tools/build_css.py --check
```

The CSS tool downloads a checksum-verified standalone compiler when absent; later
builds use its cache. Edit assets/tailwind.css/shared templates, not generated
static/css/tailwind.css. No Node/npm or runtime CDN is required.

This README is a source reference, not deployment instructions or a new feature approval.
