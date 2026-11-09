# Mock Exam Platform — Milestone 1.2

The unified Previous Year / General Question Bank CSV/XLSX import workflow is available at `/admin/question-import/`.
See [import guide](docs/import-guide.md) for permissions, the 22-column contract,
preview corrections, confirmation, cleanup, and explicit review/publication steps.

Modular Django monolith using Django 5.2 LTS, PostgreSQL, Django Templates,
HTML and CSS. Python 3.12+ and PostgreSQL 14+ are required. No domain models
are implemented beyond `accounts.User` (extends `AbstractUser`).

## Local setup (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Put the generated key in `DJANGO_SECRET_KEY` in `.env`. Set the database
variables to your own PostgreSQL database and login. Never commit `.env`.
Process environment variables take precedence over `.env`.

For dev/prod switching, see [environment configuration](docs/environment-configuration.md).
Production uses its own `.env` copied from `.env.production.example`; normal
migrations do not require edits to `config/settings.py`.

Using a PostgreSQL administrator, create a dedicated local development role
and database (the password prompt avoids embedding a password in SQL):

```sql
CREATE ROLE mock_exam LOGIN CREATEDB;
\password mock_exam
CREATE DATABASE mock_exam OWNER mock_exam;
```

Run the SQL in `psql` connected to your local server. `CREATEDB` is needed
only for the development/test role: Django creates and destroys a separate
`test_<DATABASE_NAME>` database for tests. The role also needs access to the
`postgres` maintenance database. There is no SQLite fallback.

With `.env` configured:

```powershell
python manage.py check
python manage.py migrate
python manage.py createsuperuser
python manage.py test
python manage.py runserver
```

Open http://127.0.0.1:8000/ and http://127.0.0.1:8000/admin/.
`GET /health/` executes a database query and returns JSON with HTTP 200
when PostgreSQL responds, or HTTP 503 without connection details on failure.
`createsuperuser` prompts for credentials; no default admin is installed.

## Structure and configuration

- `config`: settings and URL, ASGI and WSGI entry points.
- `core`: home page, database readiness check and foundation tests.
- `accounts`: custom user, initial migration, admin registration and tests.
- `exams`, `questions`, `imports`, `previous_year`, `mock_tests`, `practice`:
  app skeletons reserved for later milestones.
- `templates`, `static`: shared templates and CSS.

All required variables are listed in `.env.example`. `DJANGO_DEBUG` accepts
`True` or `False` and defaults to `False`; enable it only for local development.
Timezone defaults to UTC; timestamps are timezone-aware. With debug disabled,
session and CSRF cookies require HTTPS. Static files are served by `runserver`
in debug mode; `collectstatic` writes to `staticfiles/`.

Foundation tests use PostgreSQL and cover connectivity, the home and health
endpoints, database failure handling, custom user/password hashing, admin
authentication, session persistence, access control and CSRF enforcement.

## Student access and navigation

Students can register at `/accounts/register/`, log in at `/accounts/login/`,
and view their username, optional email, and account creation date at
`/accounts/profile/`. Registration validates passwords and signs the student
in. Logout uses a CSRF-protected POST from the shared navigation.

Home, `/exam-authorities/`, and `/previous-year/` are public. `/mock-tests/`
and `/practice/` require login and preserve a safe `next` destination through
login or registration. Previous-year papers and mock tests use configured domain data. Practice supports persistent untimed sessions with immediate feedback.
The responsive menu supports touch, native button keyboard activation, and
Escape to close and return focus. Links remain visible without JavaScript.

Run `python manage.py test` for the foundation and student authentication,
permission, redirect, CSRF, and navigation tests, all using PostgreSQL.
No new models or migrations are required for Milestone 1.2.

This milestone does not include domain functionality or deployment setup.

## Mock test execution (Milestone 4.3)

Authenticated students can start configured active patterns at `/mock-tests/`,
resume fixed attempts, save/change/clear answers, mark questions for review, and
submit for scored results with bilingual review. Deadlines and scoring use the
frozen attempt configuration; no browser-provided marks or answer keys are trusted.
See [execution behavior and expiry](docs/mock-test-execution.md).

Run scoped checks with `python manage.py test mock_tests --noinput`,
`python manage.py check`, and `python manage.py makemigrations --check --dry-run`.

## Practice sessions (Milestone 5.1)

Open `/practice/` after login, choose an exam category, exam, subject and optional
Topic, then select 10/20/30/50 questions or the available count. Each submitted
answer locks and reveals feedback. Skip freely, pause by leaving, and resume
without a timer. Answering every question completes the session; unfinished
sessions can be explicitly abandoned. Practice history is separate from mock scores.
See [practice workflow and integrity](docs/practice-sessions.md).

Run `python manage.py test practice --noinput` for scoped PostgreSQL tests.

## UI stylesheet build (Phase 1.1)

The shared shell uses compiled Tailwind CSS; `site.css` remains the fallback.
No Node/npm or CDN runtime is required. Run `python tools/build_css.py` after
changing shared templates or `assets/tailwind.css`; use `--watch` while editing
and `--check` to verify the generated asset. The first build downloads a pinned,
checksum-verified standalone compiler into `.tools/`. The compiled
`static/css/tailwind.css` works with normal `python manage.py collectstatic --noinput`.
See [UI foundation](docs/ui-foundation.md) for design tokens and migration rules.

UI Phase 1.2 updates the homepage, shared navigation, cards, CTAs, footer and
breadcrumbs using the same compiled stylesheet. Rebuild with
`python tools/build_css.py` after editing these templates. Routes, authentication
and homepage data sources remain unchanged. See [UI foundation](docs/ui-foundation.md).

UI Phase 1.3 refreshes exam discovery and previous-year papers with responsive
cards, browser-only card filters, clearer selection controls and a bilingual paper
reader. Existing server queries, URLs and publication/feedback behavior are unchanged.
Rebuild shared CSS with `python tools/build_css.py`; see [UI foundation](docs/ui-foundation.md).

UI Phase 1.4 adds a focused mock-exam shell, always-visible timer/progress bar,
section-aware question palette and persistent navigation/submit actions. All
questions remain on one scrolling page. Autosave, API contracts, timer enforcement
and scoring are unchanged. Run `python manage.py test mock_tests --noinput` for
scoped checks; rebuild the stylesheet with `python tools/build_css.py`.

UI Phase 1.5 modernizes Practice configuration, one-question sessions, feedback,
progress and summaries. Native POST submission, locked answers and session resume
are preserved. Run `python manage.py test practice --noinput` for scoped checks
and `python tools/build_css.py` to rebuild the shared compiled styling.

UI Phase 1.6 turns `/accounts/profile/` into the student dashboard with recent
mock/practice activity, progress summaries and the existing account details.
A read-only, user-scoped context helper reuses saved learning records. Login,
registration, permissions and safe redirects are unchanged; no social sign-in or
new account-management features are added. Run
`python manage.py test accounts core.test_navigation --noinput` for targeted checks.

UI Phase 1.7 completes custom import and review styling and the shared UI cleanup.
See [UI migration summary](docs/ui-migration-summary.md) for phases 1.1-1.7,
asset build instructions and final targeted verification.

My Account has separate Profile (`/accounts/profile/`) and Learning Space
(`/accounts/learning-space/`) pages. Profile contains account details; Learning
Space contains the existing mock/practice dashboard and resume/result links.
Both require login, and the existing login destination remains Profile.

