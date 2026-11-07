# Development and production configuration

Keep the same code and migrations on both hosts. Only the private `.env` differs.
Process environment variables override `.env`; restart the application after changing
either. The ASGI/WSGI entry points still use `config.settings`.

| Host | One-time setup |
| --- | --- |
| Development | Copy `.env.example` to `.env`; set your local secret/database values. `DJANGO_ENV=dev`, `DJANGO_DEBUG=True`. |
| Production | Copy `.env.production.example` to `.env`; set a unique secret, production PostgreSQL credentials, real allowed hosts and HTTPS origins. `DJANGO_ENV=prod`, `DJANGO_DEBUG=False`. |

Do not copy the development `.env` over the production file when updating code.
If using only process environment variables, no `.env` file is needed. Existing
local files without `DJANGO_ENV` keep working as `dev`. Production rejects debug,
wildcard hosts, missing hosts and disabled HTTPS redirects.

Production needs working HTTPS. Set `DJANGO_TRUST_PROXY_HTTPS=True` only when a
trusted proxy removes client-supplied `X-Forwarded-Proto` and sets it correctly;
otherwise leave False. Incorrect proxy configuration can cause redirect loops.
HSTS defaults to zero until HTTPS is verified; configure
`DJANGO_SECURE_HSTS_SECONDS` afterward. Django may report an HSTS warning while
this remains zero. Database TLS uses the existing `DATABASE_SSLMODE` variable.

Optional `DJANGO_STATIC_ROOT` and `IMPORT_STAGING_ROOT` accept absolute paths.
Staging must be private, writable and outside any publicly served directory.
The production web server must serve collected static assets; `collectstatic`
copies assets but does not serve them.

For ordinary updates, keep the server environment file and run:

```text
python manage.py check --deploy
python manage.py migrate --noinput
python manage.py collectstatic --noinput
```

Restart the application using your existing process manager. No settings edits
are required after migrations. New future configuration variables may require
an explicit environment update. This change does not install or configure a
production application server.

## Files and ignore rules

- Change **only `.env` on each host** for secrets, domain, database and environment.
- Tracked configuration: `config/settings.py`, both example environment files,
  `.gitignore`, and this guide. Do not ignore these files or Django migrations.
- Ignored private configuration: `.env`, `.env.*` except the two example files,
  `secrets/`, `*.pem`, `*.key`.
- Ignored runtime/build files: `.venv/`, `__pycache__/`, `*.py[cod]`,
  `staticfiles/`, `.import-staging/`, `.tools/`, `logs/`, `*.log`, `*.pid`, `*.sock`.
- Keep source `static/` and compiled `static/css/tailwind.css` tracked.

Ignore rules prevent new untracked files being added; they do not remove secrets
that were already tracked. Custom runtime directories inside the repository need
their own ignore entry. Paths outside the repository are outside Git's scope.

Reference: [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
