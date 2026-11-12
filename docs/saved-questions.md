# Saved Questions, Revision Bank and Revision Sessions

Current reference, 2026-11-12. The R1/R2/R3 features are implemented, not separate engines.
Use [MODULE_MAP](MODULE_MAP.md) for files and [Practice engine](practice-sessions.md) for
shared answer/snapshot behavior. [Topic exploration](topic-exploration.md) covers live discovery.

## Personal bookmarks and access

revision.SavedQuestion stores user, master Question, saved_at, optional personal_note,
reviewed_at, review_count and is_mastered. The user/master pair is unique; no attempt or
paper-question ID substitutes for a master. Repeated save preserves existing notes/progress.
Notes are escaped/private and limited to 10,000 characters. Unsave deletes only the caller's
personal state, including notes/progress, while historical session rows remain intact.

| Endpoint | Contract |
|---|---|
| POST /revision/questions/<question_id>/save/ | Idempotently save an accessible master for the authenticated owner |
| POST /revision/questions/<question_id>/unsave/ | Idempotently remove only that owner's bookmark |
| GET /revision/ | My Revision Bank: global owner counts, filters, 20-row pagination |
| GET /revision/saved/<pk>/ | Owner-scoped bookmark detail; no read-triggered progress writes |
| POST /revision/saved/<pk>/manage/ | note/mastered/needs_revision/reviewed actions |
| GET /revision/saved/<pk>/remove/ | Confirmation page |
| POST same remove route with confirm=yes | Confirmed removal through the R1 service |

Session-authenticated writes require CSRF. Bookmark requests with Accept: application/json
return only question_id/saved; unauthenticated requests return 401 and unavailable saves 404.
Native forms return to a validated local next URL. Guest sign-in preserves question context.
Bookmark permission accepts a published active-exam question or the user's own frozen history;
this does not authorize reading unpublished content through the bank.

## Bank UI and eligibility

My Revision Bank is under My account and in account-section navigation, not a standalone
header item. Cards use compact checkbox-style Save for revision controls where applicable;
success announcements are commented out in static/js/bookmarks.js; error feedback remains.

Counts cover all of the user's bookmarks, distinct reviewed questions and mastered questions,
independent of filters. Filters cover Exam, Subject, Part, Module, Chapter, Topic and mastery.
Hierarchy filters include primary/secondary tags and deduplicate masters. Sorting supports
saved date and normalized published difficulty. Pagination retains filters.

Readable content uses only the current approved revision, active exam membership and complete
English/Bengali translations. Working drafts are excluded. Questions in the caller's open
Mock Tests are withheld. Unavailable bookmarks retain their notes/progress with content-free
placeholders and remain removable. Notes are never serialized into related-question pages.
Manual mark-reviewed updates reviewed_at/count; ordinary GET/detail/refresh does not.
Mastery is an explicit independent action, not a consequence of an answer's correctness.

## Personalized sessions

Start Revision at /revision/start/ accepts all eligible saved questions or the same bank
filters and an optional positive limit up to 10,000. Blank means all; a limit uses up to
the available count. Selection randomizes unique master IDs. Empty/invalid selections create
no session. Question availability is rechecked under locks before freezing the set.

RevisionSession is a proxy over PracticeSession(kind=revision). The same PracticeQuestion
records store approved revision IDs, order, frozen classification, answers and correctness.
Revision scope has null Exam/Subject/Topic FKs, allowing mixed exams/subjects without inventing
an arbitrary owning Exam. Normal Practice retains its required scope and separate statistics.

| Route under /revision/ | Purpose |
|---|---|
| sessions/ | Paginated owner history |
| sessions/<id>/ | One pinned question; resume next unanswered or explicit question order |
| POST sessions/<id>/questions/<row_id>/answer/ | Shared Practice submission; AJAX fragment or native redirect |
| POST sessions/<id>/questions/<row_id>/mastery/ | Update the existing owner's bookmark mastery |
| GET sessions/<id>/finish/ | Early-completion confirmation |
| POST finish/ with confirm=yes | Complete, preserving unanswered rows |
| GET sessions/<id>/results/ | Total/attempted/correct/incorrect/unanswered and accuracy; incorrect=1 subset |

Pause is navigation away from persistent state. First successful submission locks feedback
and atomically updates an existing SavedQuestion once. Session locking prevents duplicate
or concurrent answer requests from recounting. The hook never recreates a removed bookmark.
Last-answer completion is automatic; early completion also preserves unanswered rows.

Completed results and pinned translations remain historical after bookmark deletion,
retagging or newer publication. Resume follows Practice's frozen-history policy, whereas
new bank/exploration reads use current eligibility. No timer or Mock scoring is added.

## Schema and verification references

| Migration | Purpose |
|---|---|
| revision/0001_initial | Unique owner/master bookmark |
| revision/0002_savedquestion_is_mastered_and_more | Backward-compatible note/progress defaults |
| practice/0002_practicesession_kind_alter_practicesession_exam_and_more | Shared kind/scope constraint and nullable revision context |
| revision/0003_revisionsession | Proxy registration; no additional question/session response table |

Tests: revision.tests, revision.test_bank, revision.test_sessions and relevant shared Practice
regressions. No new application tests or database commands were run for this documentation edit.
AI/mobile token adapters are not implied. Exploration routes exist, but per-question Explore
Topic controls were removed; do not restore them accidentally while changing bookmark UI.
