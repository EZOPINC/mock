# Mock test execution - Milestone 4.3

## Student workflow

Log in, open Mock Tests, choose an authority/exam and active pattern, then start.
Attempts keep their original question order, immutable revisions, translations,
configuration and effective marks. Repeated starts resume an open attempt.

Students choose English, Bengali or Both before starting. New attempts freeze this
choice in `configuration.language`; `start_attempt(..., language="both")` validates
the choice and rejects unavailable selected translations before creating an attempt.
The server renders only the selected edition (or both) from the frozen revision.
Resuming from another browser preserves the saved language. Existing attempts without
this key keep their original question sets and legacy display behavior. No migration
or historical attempt update is required. Bilingual sections require both complete
published translations; insufficient pools fail existing activation/availability checks.

The viewer restores saved choices, review flags and current question position.
All questions remain visible on one scrolling page in persisted order. The palette
and Previous/Next scroll to a question; focusing its controls updates the active
question and saved resume position. Choose A-D, clear an answer or toggle
Mark for review. English appears first, Bengali second, stacking on small screens.
Palette colors and accessible labels indicate answered/review/current state.
Review flags never exclude an answer from scoring. Answers and explanations are
absent from active HTML and JSON, rather than merely hidden with CSS.

Wait for **All changes saved** before leaving. Network failures retry the same
request token; an explicit retry remains available after retries are exhausted.
Unsaved changes trigger a browser leave warning. Local unsaved changes cannot be
guaranteed if a browser is forcibly closed or remains offline past the deadline.
Conflicts from another tab require reloading saved state instead of overwriting it.

Review and submit waits for queued saves, then displays answered/unanswered/review
counts. Confirmation carries the current save version; a later save invalidates
that confirmation. Final submission is idempotent. Results show score, percentage,
counts, section performance and review of the pinned question revisions.

## Time and finalization

`expires_at = started_at + frozen duration_minutes`. Additive migrations backfill
existing attempts from their snapshot duration, preserving IDs and references.
The browser countdown uses server time plus elapsed monotonic browser time, with
periodic server synchronization. Changing the browser clock cannot extend time.
The confirmation page returns to results when its remaining deadline elapses.

Every save, resume, status check, submission and results request checks server time
under an attempt-row lock. At or after the deadline the attempt is finalized as
Expired before accepting changes. Late saves return 410 and still commit expiry.
The active viewer polls status to finalize automatically even without answer edits.

When no browser/request is active, expiry is enforced logically by the deadline;
the final result is persisted on next access or by:

```text
python manage.py expire_mock_attempts
```

The command finalizes idle overdue attempts using the same services. No background
scheduler/service or infrastructure is installed by this milestone. Closing a
browser never pauses or extends its deadline.

## Persistence and concurrency

MockAttempt adds expiry/finalization times, last_position, save_version,
last_save_token, total_score, maximum_score, correct/incorrect/unanswered counts
and frozen section_results. AttemptQuestion adds selected_answer,
marked_for_review, answered_at and awarded_marks. Earlier snapshots remain intact.
Database constraints enforce valid options, deadlines, positions and final fields.

`execution.py` owns mutations and scoring. All mutation paths lock the parent
attempt first. The JSON save endpoint requires CSRF, a UUID token, expected global
version, valid persisted position and, for answers, an owned attempt-question ID,
A-D/blank and a strict boolean review flag. Saves increment the global version;
stale requests return 409. An exact retry of the latest accepted token/version
returns success without reapplying it. Browser requests are queued in order.

Submission and autosave serialize on the same lock. If submission wins, a later
save is rejected; if a save wins, scoring includes it. Confirmation detects version
changes. Finalization and all awarded marks/results commit in one transaction;
failures roll back all score changes. Finalized attempts/results reject mutation.

Scoring uses Decimal and the pinned revision answer: correct earns positive_marks,
incorrect deducts negative_marks, blank earns zero. Percentage is score/maximum*100
and may be negative. Multilingual versions count as one master. Results never read
the master working answer or current pattern marking values. Question translations
and published revision content remain immutable. Used pattern versions stay frozen.

## Routes and checks

All routes below require authenticated ownership and send no-store responses:

- `attempts/<id>/`: execution/resume; redirects finalized attempts to results.
- `attempts/<id>/save/`: POST JSON autosave, including position-only saves.
- `attempts/<id>/status/`: GET server clock/finalization status, never answer keys.
- `attempts/<id>/submit/`: GET confirmation, POST version-checked final submission.
- `attempts/<id>/results/`: finalized results and bilingual review only.

These paths are under `/mock-tests/`. Unknown/foreign attempts return 404; save
and submission require POST/CSRF. No external dependencies were added.

Tests use PostgreSQL: `python manage.py test mock_tests --noinput`. Concurrency and
migration tests use TransactionTestCase; normal application tests use TestCase.
Milestone 5.1 and additional engines are outside this change.
