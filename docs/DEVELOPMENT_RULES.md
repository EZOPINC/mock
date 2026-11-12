# Development Rules

Source-verified conventions and separately labeled recommendations, 2026-11-12.
Code, current task authorization and applicable instructions override these notes.
Use MODULE_MAP.md to locate ownership before opening implementation/architecture files.

## Observed: organization and implementation style

- A modular Django monolith separates domain models and workflows by app.
- Views generally orchestrate requests/auth/forms and delegate domain writes to services.
- Model clean/save guards enforce workflow invariants; database constraints add protection.
- Plain functions, explicit keyword arguments and Django ValidationError are common.
- Named URL reversals connect shared templates to app-owned views.
- Catalogue selectors and eligible-content selectors differ; choose the correct layer.
- Shared multilingual markup lives in templates/questions rather than app-specific copies.
- Practice/Revision share snapshot assembly, answer locking, progress and question markup.
- Legacy forms/assets remain alongside the current module/difficulty Practice UI.

## Observed: model and migration safety

- QuestionRevision content is append-only even before publication; edits create a new revision.
- Guarded publication can set published_at once; that exception does not permit content edits.
- QuestionTranslation rows are immutable revision-bound snapshots assembled through services.
- Working/published pointers differ; never treat current_revision as live public content.
- Attempts, papers and Practice rows reference approved revisions and master identities.
- Scores/feedback use frozen revisions and marks, not mutable master answer/difficulty fields.
- Protected querysets reject many update/bulk_create/bulk_update/delete operations.
- Save flags such as _assembly/_workflow/_execution are internal workflow boundaries.
- Guards differ by model: Topic.save does not take HierarchyNode.save's full_clean path.
- Raw ORM shortcuts may bypass invariants even when they resemble service operations.
- PostgreSQL triggers enforce ancestry and legacy primary-topic compatibility.
- Deferred primary-tag consistency is checked at transaction commit.
- Backfills and guarded reversals exist; migrations are not uniformly reversible.
- SavedQuestion is personal removable state; content/assessment history has different retention rules.

## Observed: authentication and information boundaries

- accounts.User is the custom auth model; registration uses UserCreationForm/password validation.
- Login/registration validate safe next destinations; Django logout uses POST.
- Sessions, answers, notes and mastery are scoped to the authenticated owner.
- Imports require active staff and mode-specific Question/import/paper permissions.
- General batch transitions require staff permission and an inspected-state fingerprint.
- State-changing HTML actions use POST/CSRF; safe-method decorators restrict read interfaces.
- Existing GET workflow checks can still finalize expired Mock Tests.
- Personalized account/revision/execution responses commonly use never_cache.
- Bookmark JSON is minimal and never serializes answer keys or assessment scores.
- Permission to bookmark owned history does not guarantee readable bank content today.
- Revision eligibility checks publication, active exam membership and complete supported translations.
- Open-mock source questions and related exploration scopes are withheld before submission.
- Related pages use eligible published content, not arbitrary draft revisions.
- Personal notes are escaped/private; HTML action returns validate local redirect targets.

## Observed: transactions, retry and concurrency

- Workflow writes use transaction.atomic and select_for_update on relevant owners/parents/masters.
- Import confirmation uses an internal atomic block, token/context uniqueness and revalidation.
- Mock starts/Revision selection recheck eligibility after acquiring candidate Question locks.
- Tag replacement keeps the legacy pointer and topic set coherent in one transaction.
- Mock autosave uses save_version and latest UUID retry token; preserve 409/410 behavior.
- Practice start tokens are unique per user; Revision also compares the frozen request specification.
- Repeating an identical submitted Practice answer is safe; changing it is rejected.
- Revision review_count increments on first successful answer within the answer transaction.
- Refresh/resume/summary do not recount; mastery is explicit and independent of correctness.
- User-row locks coordinate topic rendering with that user's Mock Test starts.

## Observed: templates, CSS and JavaScript

- Reuse templates/base.html, cards/forms/icons and scoped feature stylesheets.
- assets/tailwind.css is editable source; static/css/tailwind.css is generated output.
- tools/build_css.py checks a pinned standalone compiler and may download it when absent.
- Local/static assets are used without a frontend framework or browser CDN dependency.
- Vanilla JS progressively enhances native forms; the server owns feedback/saves.
- Bookmark forms stay outside answer forms and independent of mock review/autosave actions.
- Shared submit-button selectors outrank a bare class; preserve bookmark reset specificity.
- Bookmark label/pressed state updates in JS; success announcements are currently commented out.
- Scoped mobile CSS hides palettes while preserving question navigation/session controls.
- Exploration routes remain implemented, but repeated per-question controls were removed.

## Observed: testing patterns and targeted commands

Tests use TestCase/TransactionTestCase, clients, patches, MigrationExecutor and query counts.
Concurrency tests use separate connections/threads; database behavior relies on PostgreSQL.
Django tests use a separate test database; keep destructive commands away from runtime data.
Commands below are references, not checks executed for this documentation task.

| Change | Start with |
|---|---|
| Question workflow/tags | `python manage.py test questions --noinput` |
| Taxonomy/trigger behavior | `python manage.py test exams.test_flexible_taxonomy questions.test_topic_tags --noinput` |
| CSV/XLSX normalization | `python manage.py test imports.test_taxonomy_import imports.test_wide_format --noinput` |
| Import persistence/rollback | `python manage.py test imports.tests.ConfirmationTests --noinput` |
| Public paper reader | `python manage.py test previous_year.test_modes previous_year.tests.PaperPublicTests --noinput` |
| General batch administration | `python manage.py test general_question --noinput` |
| Pattern/rule selection | `python manage.py test mock_tests.test_selection_rules mock_tests.test_attempts --noinput` |
| Mock autosave/scoring | `python manage.py test mock_tests.test_execution --noinput` |
| Practice | `python manage.py test practice --noinput` |
| Bank/Revision sessions | `python manage.py test revision.test_bank revision.test_sessions --noinput` |
| Bookmarks/exploration | `python manage.py test revision.tests revision.test_exploration --noinput` |
| Account/navigation | `python manage.py test accounts.test_account_sections core.test_navigation --noinput` |

Relevant checks: `python manage.py check`; `python manage.py makemigrations --check --dry-run`.
Shared Tailwind: `python tools/build_css.py`; verify compiled output with its `--check` option.
Use `python manage.py audit_taxonomy` for pertinent integrity investigations, not routine UI changes.
Run `python manage.py test --noinput` only when scope or failures justify broader testing.

## Recommended future rules: scope and compatibility

- Identify the owning app; inspect mapped files/direct dependencies before broad searches.
- Prefer minimal patches and existing services/components over adjacent speculative refactoring.
- Preserve URL names, JSON shapes, redirect safety and owner checks unless changes are authorized.
- Preserve master IDs, revision numbering, approved references and historical attempt/session snapshots.
- Deduplicate masters across tags, languages, exams and overlapping selection rules.
- Do not automatically add Subjects during import or silently relax taxonomy conflict checks.
- Reuse eligibility/tagging services; a non-null published pointer alone is insufficient authorization.
- Add migrations only for necessary schema/data changes; document compatibility and rollback limits.
- Never edit immutable content or historical results to satisfy a new validation rule.
- Keep credentials, environment values, staged uploads and personal notes out of docs/logs.
- Do not add AI, token/mobile APIs, dependencies or deployment changes without task authorization.
- Run targeted checks first; broaden only for relevant cross-app risks or failures.
- Avoid implementation-mirroring tests for reversible low-impact styling changes.
- Update these references only when architecture, interfaces or locations change.
- Older phase notes are context, not proof of implementation or blanket approval requirements.
- When source and docs differ, follow source and record discrepancies within authorized scope.
