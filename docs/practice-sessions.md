# Practice sessions - Milestone 5.1

## Workflow

Authenticated navigation: Practice -> Exam Authority (category) -> Exam -> Subject
-> optional Topic -> number of questions. Only exams/subjects/topics with eligible
published questions appear. Counts are 10/20/30/50, when available, or the available
pool count. A selected topic may have fewer questions than the whole subject;
starting rechecks availability and reports insufficient pools without partial writes.
Practice is untimed and does not create mock attempts or official scores.

The viewer renders one persisted question at a time. The palette and Previous/Next
links allow skipping/revisiting; links never submit answers. Submitting A-D reveals
correct/incorrect, the pinned correct answer and available explanations in all
available translations. The answer is then locked. Neither active HTML nor summary
links reveal keys/explanations for an unanswered question. English is first, Bengali
second; existing responsive translation styles stack them on mobile.

Pause by leaving the page; the session stays In Progress and saved responses remain.
Resume from Practice to the first unanswered question, or revisit any question with
the palette. Answering every question automatically marks the session Completed.
Unfinished sessions may be explicitly Abandoned after confirmation; no new answers
can be submitted afterward. Submitted feedback remains reviewable in both states.
Accuracy uses correct/answered (zero before answering); progress uses answered/total.
Summary displays correct/incorrect/remaining and frozen subject/topic performance.

## Persistence and integrity

PracticeSession stores owner, Exam, required Subject, optional Topic, start token,
configuration snapshot, status, started_at and completed_at. States are In Progress,
Completed and Abandoned; pause does not introduce another state. FK relationships
use PROTECT. Configuration snapshots keep labels, requested and actual question count.

PracticeQuestion implements the earlier planned PracticeResponse relationship;
there is no duplicate response model/table. It stores session, master Question,
pinned QuestionRevision, question order, frozen classification labels/IDs,
selected_answer, is_correct and answered_at. The revision and its translations are
immutable, including the correct answer; no new question or text copies are created.
Frozen classification is summary metadata, not a parallel taxonomy. Unique constraints
cover (session, master question), (session, order) and (user, start token). Database
checks require positive order and coherent unanswered/submitted response state.

Shared eligibility lives in questions/eligibility.py; existing mock-test services
retain their section-aware wrapper. Only approved published revision pointers,
complete valid primary content/translations and active exam associations qualify.
One master counts once, including bilingual content. Practice samples a single
filtered pool without replacement; mock multi-section capacity allocation is unchanged.
Creation locks the user and candidate masters, revalidates the pool, pins revisions
and assembles the entire session in a transaction. A token replay returns its original
session, including after completion, and cannot change its configuration.

Answer submission locks the parent session, grades on the server and commits feedback
and automatic completion together. Same-answer retries return stored feedback;
conflicting retries are rejected. The first concurrent response wins. Session/row
snapshots reject direct edits/deletes and finalized responses remain immutable.
Abandonment uses the same parent lock. Errors roll back partial creation or feedback.

## Routes and checks

All routes live below `/practice/` and require authentication. Session, feedback and
summary views use owner-scoped queries and no-store responses. Unknown/foreign session
or question IDs return 404. Start, answer and abandonment use POST with CSRF. No
JavaScript or asynchronous save is required for feedback, making retry/refresh safe.

- `/`: categories, open sessions and recent completed/abandoned history.
- `/<authority>/`: eligible exams.
- `/<authority>/<exam>/`: eligible subjects.
- `/<authority>/<exam>/<subject>/`: topic/count configuration and POST start.
- `/sessions/<id>/`: one-question viewer; `?question=<order>` chooses a question.
- `/sessions/<id>/questions/<row_id>/answer/`: POST a locked answer.
- `/sessions/<id>/summary/`: progress, classification breakdown and review links.
- `/sessions/<id>/abandon/`: confirmation and POST abandonment.

Run `python manage.py test practice --noinput`, `python manage.py check`, and
`python manage.py makemigrations --check --dry-run` using PostgreSQL. Actual
concurrency tests use TransactionTestCase; application tests use TestCase.
No timers, mock scoring changes, deployment work or Milestone 6.1 is included.
