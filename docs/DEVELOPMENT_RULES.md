# Development Rules

Use the [Module Map](MODULE_MAP.md) to find source. The rules below describe boundaries that changes should preserve.

## Domain and security

- Keep views focused on forms, permission checks and orchestration. Reuse domain services and existing UI components. Prefer scoped static assets and progressive enhancement.
- Preserve Question IDs and append-only revisions and translations. Workflows distinguish the working revision, approved revision and frozen historical pointers. Preserve database constraints and deferred taxonomy guards.
- Keep staff access, per-user ownership, CSRF and safe redirects in the server workflow. Learner views use approved content or frozen history. Active mocks withhold answer keys, explanations and protected exploration data.
- Keep import and editorial writes atomic. Preserve uploader-owned staging, signed/hashed inspected state, contextual deduplication and revalidation under locks. Use the existing lock order. Mock and Practice must recheck eligibility before assembling snapshots.
- Preserve request and retry contracts unless the task changes them. In particular, Mock autosave uses a version and retry UUID. Practice idempotency uses start tokens and locked answers.
- Add migrations only for necessary schema/data changes. Record verification and rollback boundaries. Work on test data for database integrity checks.

## Targeted checks

Run the smallest relevant suite first. The table lists labels for `python manage.py test <labels> --noinput`. Concurrency and migration tests require PostgreSQL.

| Change | Test labels |
|---|---|
| Question workflow, translations or tags | `questions` |
| Taxonomy paths and triggers | `exams.test_flexible_taxonomy questions.test_topic_tags` |
| Import parsing, validation or confirmation | `imports` or the relevant test module |
| Staff review workspace | `general_question` |
| Previous-Year paper publication and reader | `previous_year.tests previous_year.test_modes` |
| Mock allocation and frozen sets | `mock_tests.test_selection_rules mock_tests.test_attempts mock_tests.test_free_demo` |
| Mock execution | `mock_tests.test_execution` |
| Practice or Revision | `practice` or `revision` |
| Billing behavior | `billing.test_usage`, `billing.test_lifecycle`, `billing.test_payments` or `billing.test_finance` |

Use `manage.py check` for Django configuration and `makemigrations --check --dry-run` for model changes. Use `tools/build_css.py --check` for changes to compiled inputs. Skip runtime tests and builds for documentation-only edits. Verify diff scope in every case.
