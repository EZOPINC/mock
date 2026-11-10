# Phase D3 — multi-topic question tagging

Question keeps its Subject, legacy `topic` FK, revision pointers, translations
and QuestionExam associations. `QuestionTopic(question, topic, is_primary)` adds
tags without copying masters/content. `Question.topics` is a read convenience.

## Invariants and synchronization

- Unique question/topic pairs and a partial unique constraint enforce at most one
  primary. The pair index covers Question lookups; Topic has its FK index.
- All tags must belong to Question.subject. Classified questions require exactly
  one primary matching Question.topic. Unclassified questions have no tags and a
  NULL pointer. Deferred PostgreSQL guards verify final state at commit, including
  direct SQL writes. Temporary intermediate state is allowed only within a transaction.
- Writers lock the master Question. SQL guards reject cross-subject tags,
  association reassignment and Question subject changes while tags remain. D2
  prevents Topic subject moves. PROTECT FKs also protect secondary-tag Topics.
- PostgreSQL is the authoritative legacy synchronization boundary; no signals or
  recursive tag→question triggers. Updating Question.topic promotes that Topic,
  retaining the former primary as secondary. **Clearing it removes all tags.**
- `questions.tagging.set_question_topics(question_or_id, topic_ids,
  primary_topic_id=...)` replaces the entire set transactionally. IDs must be
  distinct and in the same Subject; nonempty sets require a selected primary.
  An empty list unclassifies. Concurrent replacements serialize; the last
  completed replacement defines the set, rather than merging competing edits.
- Individual QuestionTopic.save/delete are validated. A primary with remaining
  secondaries cannot be deleted until a replacement is explicitly chosen.
  Use the replacement service for primary switches/bulk edits; direct M2M
  add/remove/clear and guarded queryset bulk writes are not supported write APIs.
  Refresh other previously loaded Question instances after tag writes.

## Admin and read integration

Question Admin labels the existing field **Primary topic** and adds **Additional
topics**, prefilled from existing tags. Options are scoped by native JavaScript
and independently validated against the bound Subject on the server. Duplicate,
foreign-subject and secondary-without-primary choices fail. Clear all tags before
changing Subject. Existing change-question permission controls these fields; no
public editing endpoint is added.

Admin has an assigned-topic filter alongside the legacy primary-topic filter.
`questions.selectors.questions_by_topics(ids, queryset=...)` matches any assigned
topic and returns distinct masters. Public callers must pass a published/authorized
base queryset. General Question public filtering uses this helper. Empty ID lists
return no matches; language translations never multiply master results.

Existing `Question.objects.filter(topic=...)` still means primary topic. Mock and
Practice eligibility retain their current primary-topic rules; multi-topic quotas
belong to D4. Previous-Year paper numbering/order and pinned revision IDs remain.
Retagging does not rewrite answers, scores, translations or frozen classifications.

## Migrations and rollback

Migration `questions.0004` adds the through-model; `0005` backfills each non-null
legacy assignment as primary and installs the guards. Apply both before running
D3 code. Backfill replay is idempotent for a consistent database and preserves
existing associations. Pre-existing subject mismatches abort rather than guessing
repairs. Questions with no Topic remain unclassified.

Rollback to questions 0003 preserves legacy primary pointers, but secondary tags
would be lost. A guard refuses rollback while any secondary exists, before
removing triggers/tables. Export/review mappings and prepare an approved conversion
if necessary; do not bypass the guard to drop data. A primary-only reverse/reapply
preserves Question/revision/paper IDs; newly introduced association IDs may be
recreated and must not be treated as historical question identifiers.

`python manage.py audit_taxonomy` now verifies tag Subject consistency and primary
pointer alignment. Tests cover migrations, raw SQL commit rejection, concurrent
replacements, admin editing/filtering, bilingual imports and existing learning
services. No difficulty normalization, attempt changes or D4 selection rules.

Local validation: 255 distinct targeted PostgreSQL tests passed across focused
runs. Django system/migration checks and collectstatic passed. One older migration
test now restores all current migration leaves after testing its original target;
its historical assertions and security tests are unchanged.

Local backfill created 217 primary tags and retained 230 unclassified questions.
Complete-row fingerprints across 14 existing tables were unchanged. The expanded
taxonomy audit reported zero tag/Subject or primary-pointer mismatches.
