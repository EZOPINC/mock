# Phase R1: Saved Questions foundation

`revision.SavedQuestion` stores the authenticated user, master Question and save
creation time. The database unique constraint prevents duplicate user/question
pairs. Saving again preserves the original saved_at. Unsave only deletes the
caller's association and succeeds even if it was already removed.

## Endpoints

- POST `/revision/questions/<question_id>/save/`
- POST `/revision/questions/<question_id>/unsave/`

Both require an active authenticated user and CSRF protection for session-authenticated
requests. No user ID or revision ID is accepted. With `Accept: application/json`,
success is exactly `{"question_id": 123, "saved": true}` (false for unsave).
Authentication failure returns 401; unavailable save targets return 404. Neither
endpoint serializes question text, answers, explanations, attempts or scores.
No GET request changes a bookmark. The service layer can be reused by a future
mobile authentication/API adapter; no new authentication mechanism is added here.

Saving is allowed for published questions in active exams, or frozen questions
in the caller's own mock/practice history. Other users' private history grants
no access. Unsave is always scoped to the caller, including after unpublication.
HTML form submissions return to a validated local `next` URL. Guest sign-in links
preserve the page query string and question anchor. No automatic save occurs on GET
or after sign-in: the user returns to the question and can save it there.

## UI and assessment isolation

The shared template tag/control is used by previous-year papers (both modes),
practice questions and mock questions/results. State is loaded in one query per
render, scoped to the signed-in user. Personalized paper responses are not cached.
The control reuses existing button styling. JavaScript sends independent POSTs and
updates all instances of the same question without navigating or submitting an
answer form. Failed/timeout requests can be retried safely. The script does not
read answer inputs, invoke autosave, stop timers or expose solution data.

## Migration

`revision/0001_initial.py` creates only `revision_savedquestion` with user/question
foreign keys, saved_at, and `revision_user_question_unique`. It depends on the
configured user model and `questions/0005_primary_topic_compatibility`. No existing
Question Bank tables or assessment schemas change. Apply with
`python manage.py migrate revision` after existing dependencies are installed.

R1 did not add a saved-question browsing page. Phase R2 adds the bank described below; revision sessions and AI remain out of scope.


# Phase R2: My Revision Bank

Authenticated navigation links to `/revision/`. The dashboard counts all personal
bookmarks, distinct questions explicitly marked reviewed, and mastered questions.
Counts are global to the user, independent of current filters. Lists have 20 records
per page and preserve query parameters in pagination links.

Filters: exam, subject, part, module, chapter, topic and mastery status. Topic paths
include primary and secondary associations and skipped hierarchy levels. Combined
hierarchy filters must match a single topic path. Filters use subqueries and distinct
master bookmarks, so multiple exams/tags cannot duplicate results. Difficulty sorting
uses the published difficulty: easy/beginner/1, medium/moderate/intermediate/2,
hard/difficult/advanced/3; other labels follow alphabetically, after known levels.

`personal_note` is optional (10,000 characters), `reviewed_at` is nullable,
`review_count` defaults to zero, and `is_mastered` defaults to false. Migration
`0002_savedquestion_is_mastered_and_more` adds only these fields in the revision app.
It preserves existing IDs, saved timestamps and the unique user/question constraint.

Detail and removal routes identify the user's SavedQuestion ID, not a Question ID:

- GET `/revision/saved/<pk>/`: detail and management controls; no progress writes.
- POST `/revision/saved/<pk>/manage/`: action `note`, `mastered`, `needs_revision`
  or `reviewed`. Blank personal_note deletes the note. Mark reviewed atomically
  increments review_count and updates reviewed_at; mastery is independent.
- GET `/revision/saved/<pk>/remove/`: confirmation page.
- POST the same route with `confirm=yes`: remove through the existing R1 service.

All mutations enforce login, ownership and CSRF. The R1 endpoints and JSON response
shape are unchanged, and saving an already-saved question preserves notes/progress.

Content uses only the current published revision, active exam availability and the
existing complete English/Bengali translation policy. The bank withholds content for
questions in the user's created/in-progress mock attempts until finalization, without
changing those attempts. It never serves a working draft or substitutes an old
attempt revision. Unavailable bookmarks remain manageable with a content-free
placeholder; their content metadata is also excluded from filter choices. Notes are
private, escaped text. Review actions require currently visible content.

Phase R2 linked Explore Topic to the saved-question topic filter. Phase R4 replaces
that destination with the published Question Bank discovery pages described in
[topic exploration](topic-exploration.md). Phase R2 added no revision-session or AI flow. Phase R3 sessions are described below.


# Phase R3: Personalized revision sessions

Start Revision on the bank preserves its exam/subject/hierarchy/mastery filters.
`/revision/start/` offers the same filters and an optional positive limit (up to
10,000); blank means all eligible saved questions. Limits select up to the available
count. Selection is server-side, deduplicated by master Question and randomized.
Unavailable questions are skipped; empty selections create no session. Repeated
start POSTs with the same user/token/configuration return the existing session,
even if bookmarks or taxonomy changed later.

## Shared engine and migrations

`PracticeSession.kind` distinguishes practice from revision. Normal practice retains
its exam and subject; revision permits both to be null to support questions spanning
multiple exams/subjects. A database constraint enforces these two scopes. The
`RevisionSession` proxy supplies a revision-only manager without another table.

`practice/0002_practicesession_kind_alter_practicesession_exam_and_more` adds kind,
adjusts the two nullable context fields and adds the scope constraint. Existing
sessions default to kind=practice with all snapshots/answers unchanged.
`revision/0003_revisionsession` registers the proxy (no question/answer tables).
Question, QuestionRevision and MockAttempt schemas are unchanged.

Revision creation reuses `practice.services.assemble_session`. Each PracticeQuestion
stores the selected master ID, approved published revision ID, random order and
frozen classification labels. Submission reuses `practice.services.submit_answer`
for correctness, locked feedback and automatic completion. The first successful
answer invokes `record_review` in the same transaction, updating only an existing
SavedQuestion for that owner/master. Session locking makes duplicate/concurrent
submissions count once. Removed bookmarks are not recreated. Mastery remains an
explicit independent POST action and never follows correctness automatically.

## Student flow and history

- `/revision/sessions/`: paginated personal history, including open/completed sessions.
- `/revision/sessions/<id>/`: one frozen question, immediate feedback after answer,
  previous/next navigation, mastery and pause link back to the bank.
- POST `.../questions/<row_id>/answer/`: shared Practice submission. AJAX returns
  the refreshed question/progress fragment; ordinary form POST redirects back.
- POST `.../questions/<row_id>/mastery/`: owner-only mastered/needs_revision update.
- GET `.../finish/`: confirmation; POST with confirm=yes closes the session early,
  retaining unanswered rows. Finishing or answering an already-closed session
  cannot change prior answers. The final answered row also completes automatically.
- GET `.../results/`: total, attempted, correct, incorrect, unanswered and accuracy
  (correct/attempted). `?incorrect=1` links back to incorrect frozen questions.

Pause is navigation away from a persisted session; resume opens the next unanswered
row, matching Practice behavior. Explicit question links allow revisiting any row.
Page refreshes and result views never increment review counts. Completed sessions
retain original answers and scoring after bookmark deletion, retagging or publishing
new revisions. Practice lists/statistics exclude revision-kind records.

## Security and scope

Creation reuses R2 visibility/language eligibility, including excluding questions
in the caller's open mock tests. Publication/retagging are rechecked under Question
locks before freezing the set. Resuming an existing session follows Practice's
frozen-history policy; later bookmark changes or unpublication do not substitute
content. Only complete English/Bengali translations from the frozen approved
revision are rendered. Shared answer/feedback markup remains answer-free until
submission. Every session, answer and mastery lookup is user-scoped; mutations
require authenticated POST and CSRF. GET setup/resume/results are read-only.

R3 introduces no revision-session timer, Mock Test selection/scoring changes, AI,
or topic-exploration behavior in Phase R3. Phase R4 is documented separately.
