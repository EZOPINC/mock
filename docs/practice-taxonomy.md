# Module and difficulty practice setup

The student flow is Exam category -> Exam -> Subject -> Module -> Difficulty -> Practice.
The subject page lists only modules with eligible questions, including questions
assigned through descendant topics and secondary tags. It has no hierarchy dropdowns
or session-size control. Subjects with no eligible modules offer a whole-subject
continuation instead.

The next page lists difficulty levels present in the selected module's published
questions, with counts. Matching ignores case and surrounding whitespace. Questions
without a difficulty appear under "Unspecified difficulty". Starting uses all eligible
questions at that difficulty in random order. Selection is revalidated under the
existing question locks. Module and difficulty are frozen in the session configuration,
and repeated submissions with the same token reuse the session. Draft difficulty
changes do not affect selection. Existing sessions remain accessible.

The underlying hierarchy discovery and legacy session behavior are described below.

# Practice taxonomy filters — Phase D6

## Behavior and compatibility

Existing Practice → Authority → Exam → Subject URLs remain unchanged. Within a
Subject, Part, Module, Chapter and Topic are optional. A selected parent includes
all descendant topics through the D2 optional-parent relationships. With no child
filters, practice includes all eligible questions in the Subject, including
unclassified questions.

`practice.discovery.PracticeTaxonomy` reuses the shared published-revision
eligibility service, then builds distinct master-question pools from primary and
secondary `QuestionTopic` tags. Only exam-eligible options appear. Unrelated
branches and cross-Subject selections are rejected, even for direct POST/service
calls. Existing mixed English/Bengali eligibility and 10/20/30/50/available-count
limits remain unchanged.

The configuration page sends only names, counts and ancestor IDs to JavaScript.
Native selects work with keyboard/touch. Changes narrow descendant options and
update counts locally without requests. The server validates every submitted
combination and quota; JavaScript is optional. Empty subjects show an explicit
message and disabled Start action.

## Session integrity

Creation still locks the user and candidate Questions transactionally, rechecks
eligibility/tags, and freezes selected published revisions and question order.
New configuration JSON also freezes explicitly selected taxonomy IDs/codes/names.
No schema migration is needed. Existing session rows are not backfilled.

Repeated starts compare the complete scope, including new parent filters. A
matching owned session resumes before checking the current pool, so retagging or
unpublishing cannot replace its questions or prevent reopening it. Legacy sessions
without `taxonomy_filters` retain their original Subject/Topic semantics. Feedback,
answer locking, completion, scoring and revision-based solutions are unchanged.

## Queries and remaining legacy dependencies

Discovery reads eligible questions/translations, four Subject-scoped taxonomy
tables and their eligible topic associations in bounded queries, independent of
the number of rows/tags. Ancestor pools use sets to avoid double-counting. Form
labels use loaded names/counts rather than traversing parent FKs per option.
Existing QuestionTopic FK and unique-pair indexes support these reads.

The legacy `Question.topic` remains intentional:

- Shared `questions.eligibility` still interprets its optional `topic_id` as the
  primary topic, preserving legacy Mock sections without D4 detailed rules.
- Practice performance summaries retain frozen **primary** topic labels; a
  secondary-tag match does not change how the existing summary groups questions.
- PracticeSession.topic records an explicitly selected Topic. Parent-only scopes
  live in configuration JSON; no historical sessions are changed.
- Question Admin retains primary hierarchy filters alongside its any-tag filter.
- D5 import defaults still accept the legacy primary topic mapping, synchronized
  with QuestionTopic. General Question discovery already uses any-tag filtering.

Large eligible pools are still materialized in memory by the shared eligibility
service. Database-side eligibility/pagination can be considered later if actual
scale warrants it; no load testing or selection redesign was introduced here.

## Verification

`python manage.py test practice --noinput`: **40 passed** (including 14 new
taxonomy tests). Django checks, migration dry-run, taxonomy integrity audit,
compiled CSS freshness and static-file discovery passed. No migrations or main
database data updates were performed.

Targeted coverage includes hierarchical/skipped paths, secondary tags, eligibility,
deduplication, quota failures, query counts, bilingual feedback, historical
revisions, legacy resume, permissions, CSRF and existing cross-module workflows.
The local Edge interaction check covers descendant narrowing, clearing unrelated
children, skipped levels, available counts and quota updates.

Cross-module run: 230/232 tests passed. Two existing homepage assertions fail:
`core.test_homepage.ModernHomepageTests.test_homepage_order_dynamic_urls_and_hero_actions`
and `core.test_navigation.NavigationTests.test_home_keeps_dynamic_categories_and_active_exam_links`.
Both expect `<h1 id="home-heading">`, absent from the current homepage. Homepage
templates and these unrelated tests were left unchanged. All authentication,
publication, ownership and answer-key security assertions in the targeted run passed.
