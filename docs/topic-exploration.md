# Phase R4: Explore Topic and related questions

Current UI status (2026-11-12): per-question Explore Topic controls were removed from
Revision Bank/detail, Previous-Year, Practice and mock-result cards. The routes,
services and templates below remain implemented for registered users; they are not
planned features. Question cards instead retain the shared Save for revision control.
Bookmark success announcements are commented out; existing POST/CSRF behavior remains.

## Routes and taxonomy

- GET `/revision/questions/<question_id>/topics/` lists primary and secondary
  QuestionTopic paths for an eligible published master question.
- GET `/revision/explore/<kind>/<node_id>/` explores a selected topic, chapter,
  module, part or subject. Only these five model kinds are accepted.
- `from_question=<master_id>` preserves the source, excludes it from related
  results, and offers a link back to the authenticated user's saved source when
  present. Source questions are independently checked for current visibility.
- `exam=<id>` and `difficulty=level:<normalized value>` filter the related set.
  `difficulty=level:` explicitly selects unspecified difficulty. Exam choices and
  difficulty choices come only from eligible questions in the current scope.

Navigation shows stored names, stable codes and model IDs. Paths follow immediate
parent foreign keys, so absent intermediate levels are skipped. The page displays
only taxonomy information already held by the models; no educational text is
created. Breadcrumb links expand to actual stored ancestors. Questions without
any topic can still explore their Subject.

## Discovery and visibility

`revision.exploration.related_questions` reuses R2's `visible_questions` eligibility
and `topic_scope` descendant selectors. Correlated EXISTS queries over QuestionTopic
and QuestionExam return each master once, regardless of translation, exam or tag
multiplicity. Subject scopes also include eligible unclassified questions.
Content comes from the current published revision, never the working draft or an
attempt's frozen revision. Only complete, matching English/Bengali translations are
rendered. Existing explanations are offered through the shared answer-disclosure
partial. Unknown or inaccessible source questions return 404; invalid filters show
errors and no results rather than silently broadening the selection.

Confidentiality is enforced on direct links as well as visible controls. A scope
containing any question in the requesting user's created/in-progress Mock Tests
returns a content-free 403 page. Broader ancestor scopes are protected too. Another
user's attempts do not block their public question access. The GET views briefly
lock the requesting user's row, matching Mock Test start's lock, so an attempt
cannot be created between checking the scope and rendering related content. No
attempt is refreshed, finalized or modified by exploration.

## Pagination and performance

Related results use 20 master questions per page. Pagination retains filters and
source. Taxonomy ancestors are loaded with bounded select_related joins; the
current scope's descendants stay in SQL subqueries. Translations, subjects and
tags are joined/prefetched in batches. Bookmark state is annotated for the current
user. Query count is independent of the number of page rows and source topic
paths. Existing foreign-key/unique indexes are used; no new schema/index migration
is introduced. There is no unrestricted all-question browse route.

## Revision integration and boundaries

Saved source links are derived using the authenticated user, not a user-supplied
bookmark owner or bookmark ID. Related pages never serialize personal notes,
mastery or another user's saved state. Exploring is read-only. Bookmarking an
already-saved related question preserves notes/progress through the R1 service.
Revision-session question sets, approved revisions, answers and results are
untouched. Exploration reflects live published content/taxonomy; frozen session
content can therefore differ from a question's current exploration context.

An open/expired-but-unfinalized mock can temporarily block its topic and ancestor
scopes until the user submits it or the existing Mock Test flow finalizes it.
Empty scopes show a clear message and links to broaden/reset selection. No AI,
external content, selection/scoring/timer changes or deployment changes are added.
