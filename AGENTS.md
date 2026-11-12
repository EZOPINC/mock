# Codex Instructions - Mock Exam Platform

## Locate the task

- Work on one clearly defined task at a time and identify the owning Django app.
- Consult `docs/MODULE_MAP.md` before exploring implementation files.
- Read `docs/architecture.md` only when architecture context is needed.
- Follow `docs/DEVELOPMENT_RULES.md`; distinguish observations from recommendations.
- Documents are navigation aids. Never treat documentation as more authoritative than source.
- Do not assume prior phases/roadmaps describe the current implementation accurately.

## Inspect efficiently

- Read only relevant mapped files and their direct dependencies.
- Start with paths, symbols and focused excerpts rather than complete files or broad dumps.
- Use rg for bounded searches; avoid repeatedly scanning files already inspected.
- Scan the whole repository only when requested or needed to resolve a dependency.
- Exclude .git, .venv, node_modules, caches, logs, staged uploads and generated/collected assets.
- Do not inspect or print credentials, local environment values or personal records.

## Implement safely

- Prefer the smallest safe patch; reuse existing services, models and UI components.
- Avoid unrelated refactoring, speculative features, dependencies and architectural changes.
- Explain necessary cross-app dependencies before expanding agreed scope.
- Preserve master Question IDs, immutable revisions/translations and historical attempts/sessions.
- Use domain workflows/tagging services; do not bypass guards, querysets or SQL constraints.
- Preserve authentication, ownership, CSRF, eligibility and active-mock confidentiality.
- Keep Mock Test scoring/timer/autosave changes within explicitly authorized scope.
- Add migrations only when necessary; preserve backward compatibility.
- Never apply migrations, install dependencies or deploy for a documentation-only task.
- Update documentation only when architecture, interfaces or file locations change.

## Verify and report

- Run targeted tests first; expand only for failures or justified cross-module risks.
- Use existing PostgreSQL/concurrency/migration tests for affected integrity behavior.
- Avoid unnecessary tests/builds for documentation-only or reversible low-impact styling tasks.
- Verify diff scope; do not revert unrelated user changes.
- Return concise changed-file, behavior, test-result and remaining-issue summaries.
- Do not print full code/docs, credentials or verbose logs in the final response.
- Follow a task-specific final-output format when supplied by the user.
