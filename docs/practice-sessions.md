# Persistent Practice Engine

Current reference, 2026-11-12. For the student setup use [difficulty/language setup](practice-taxonomy.md).
For its revision-specific consumer use [Revision Bank and sessions](saved-questions.md).

## Ownership and shared records

practice/models.py owns PracticeSession and PracticeQuestion. PracticeQuestion is the
implemented response model; the old PracticeResponse name was a target-design label.
Rows store master IDs, approved revision IDs, order, answer/correctness/time and frozen
classification. Content/translation text stays in the protected Question Bank snapshots.

New Practice sessions store `configuration.language` via
`start_session(..., language="both")`. English/Bengali choices restrict the locked,
rechecked candidate pool to complete published translations in that language; Both
keeps all eligible versions. The server renders the frozen choice for questions and
feedback. Retries preserve the original configuration. Historical sessions without
this key retain legacy display behavior. Revision sessions use their existing workflow.

| Session kind | Scope | Owner-facing workflow |
|---|---|---|
| practice | Required Exam/Subject; optional Topic | Module difficulty/language Practice Sets |
| revision | Null Exam/Subject/Topic | Filtered personal Revision Bank selections |

RevisionSession is a revision-only proxy, not a copied engine or additional response table.
Account/Practice lists and statistics filter normal Practice separately from revision kind.
Session states are in_progress/completed/abandoned; pause means leaving an open session.

## Services to reuse

| Entry point in practice/services.py | Responsibility |
|---|---|
| start_session | Validate normal Practice scope/count/token; lock owner/candidates; recheck eligibility |
| assemble_session | Internal shared snapshot/order assembly after caller selection validation |
| submit_answer | Lock owned session, validate A-D, grade frozen revision, lock feedback, auto-complete |
| abandon_session | Close an open session as abandoned without changing prior answers |
| complete_session | Finish a revision-kind session early, retaining unanswered rows |
| progress / performance | Read persisted totals/accuracy and frozen classification groupings |

The existing service accepts counts 10/20/30/50/available; the current student difficulty
page starts all available questions at the selected level. Do not confuse service support
with visible configuration controls.

Same-answer retries return stored feedback. Conflicting retries fail. The first successful
answer wins under the parent lock. Invalid submissions roll back without changing results.
The last answered row completes automatically. Completed/abandoned history cannot be edited.

For revision kind, the first-answer path calls revision.sessions.record_review in the same
transaction. This updates the existing owner bookmark once; it never recreates a removed
bookmark or infers mastery from correctness. Plain Practice does not update revision counts.

## Frozen history and eligibility

Creation uses questions.eligibility and active exam membership, complete primary content
and matching supported translations. One bilingual master counts once. Creation rechecks
under Question locks; later publication, tags or bookmark changes do not replace its rows.

Unique constraints cover user/start_token, session/master and session/order. Checks enforce
positive order, valid session kind/scope, and coherent unanswered/submitted fields. Model/
queryset guards reject unsupported snapshot writes/deletes; services use internal flags.

Existing configuration_matches supports historical taxonomy filters/legacy Topic semantics
and returns an existing matching owned session before current-pool validation. Revision has
its own request-spec comparison for retry safety, then reuses the same persisted engine.

## Routes, rendering and feedback

practice/urls.py wires session, answer, summary and abandonment. Reads are authenticated
and owner-scoped; answer/abandon writes use POST/CSRF. Revision has separate owner-scoped
routes in revision/session_views.py and rejects ordinary Practice IDs there.

practice/views.question_context prepares the row's pinned translations, progress and
bookmark state. templates/practice/question_panel.html is shared with Revision. Templates
hide answers before submission; afterward the stored feedback and approved explanations
are displayed. English/Bengali versions in the frozen revision remain available.

Resume chooses the next unanswered row; explicit question links revisit answered rows.
Summaries show total/answered/correct/incorrect/remaining and correct-over-answered accuracy.
Previous-Year reader practice is temporary and does not create these persisted records.

## UI and checks

Normal Practice uses native POST enhanced by static/js/practice-ui.js. Revision answers use
static/js/revision-session.js with partial feedback plus a native POST fallback. Bookmark
forms remain outside answer forms and independent of any mock autosave/review controls.
Small-screen palettes are hidden by CSS while next/previous and session tools remain.

Targeted references: practice/tests.py, practice/test_taxonomy.py, practice/test_difficulty.py
and revision/test_sessions.py. Run python manage.py test practice --noinput for engine scope;
include Revision tests when changing shared assembly/answer/model behavior. Historical test
counts are not current verification results. No tests were run for this documentation edit.
