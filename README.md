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
