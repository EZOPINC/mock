# Shared Free Mock Demo (M1)

Mock Tests owns the reusable publication. Billing still owns the selected Free exam and feature access. Premium generation, scoring, timers, response storage and historical attempts keep their existing engine.

## Admin workflow

1. Configure an ExamPattern and its sections/rules normally. Manual selection rules can specify the exact questions before publication; random rules draw once at publication.
2. Either mark `is_free_demo` on a draft and use **Activate validated patterns**, or select an existing pattern and use **Publish as shared Free Demo**. The latter also works for an already active/previously attempted pattern without changing old attempts. The existing per-exam/stage activation rules still apply.
3. Inspect the read-only MockSet and MockSetQuestion records to see the published configuration, master Question IDs, approved revision IDs, section/order and marks. Publication requires the existing ExamPattern change permission; inspection of the new models uses normal model view permissions. There is no public publication endpoint.
4. Only one active designated demo can exist per exam, across all stages. Retire the old designation before publishing another. **Retire shared Free Demo designation** leaves the pattern available to Premium if it is active; deactivating the pattern uses the existing workflow. Both retain its publication and attempts.

Publication is atomic and idempotent per pattern. Reactivating or re-designating an already published pattern reuses its original publication and never draws again. Create a new pattern version to change its frozen configuration/questions. Inactive historical publications are retained, but are not available as Free Demos.

## Models and integrity

- `ExamPattern.is_free_demo` defaults to false. A PostgreSQL conditional unique constraint on exam where status=active and is_free_demo=true backstops the service check. No existing pattern is automatically designated during migration.
- `MockSet` is an immutable one-to-one publication of the existing ExamPattern, with its configuration and publication time. `MockSetQuestion` stores protected section/master/revision references, sequence and marks, with unique master/order constraints. No Question or revision is copied or rewritten.
- Publishing reuses the same eligibility locks and selector as Premium generation. Once published, pattern configuration, sections and rules are locked even after deactivation. Configuration labels and marking/duration rules are retained in the publication snapshot.
- PostgreSQL guards reject snapshot edits/deletes, additions beyond the configured question count, unapproved/mismatched question revisions, and published pattern configuration edits. A deferred constraint checks the complete ordered publication at commit. Exam locks serialize publication/designation and use FOR NO KEY UPDATE so concurrent exam-reference inserts remain compatible.
- `MockAttempt.mock_set` is a nullable protected reference. New Free attempts copy rows from that publication and then use the existing attempt execution/finalization services. Premium and pre-M1 attempts have no shared-set reference and keep their original snapshots.

## Free and Premium access

Free users still select one persistent exam through their first successful Mock/Practice start. They can start only its active, published Free Demo and retake it without a limit. Every Free user receives the same master IDs, approved revisions, order and marks; display-language preferences do not change the question set. Attempts and results remain separate per user/retake. The start form preselects the exam's default when every section supports it and offers the supported display languages. The resolved choice is saved on the attempt.

Billing's earlier FreeMockSelection rows are retained for audit/history but no longer choose or restrict the demo. New Free starts do not create these per-user selections. An old selection for another pattern cannot block the currently designated demo within the already selected Free exam. Practice's lifetime allowance and all subscriptions remain unchanged.

No designated demo means new Free Mock starts fail closed with a Premium prompt; Admin must publish the desired demo after rollout. A newly published question revision or a newly available candidate never changes the frozen revision/selection. Starts still recheck active exam/current publication and exam membership: withdrawn content makes the demo unavailable rather than silently replacing questions. Frozen editions remain the source for language validation and scoring.

For subjects with a question expiry policy, every question in the frozen set must have a future expiry date for new starts. When a demo becomes unavailable, retire it and publish a replacement pattern with a current pool. Existing attempts keep their original question and revision snapshots.

Premium users continue through the original random/manual rule selector on every new attempt, including patterns carrying a demo designation. Existing open attempts resume before new-start entitlement checks; historical questions/results remain untouched even if a demo is replaced, retired or deactivated.

## Rollout and verification

Migrations `mock_tests.0007` and `0008` add fields, publication tables, constraints and guards. They do not backfill/rewrite existing attempts or billing/subscription data. The migration regression verifies old question/revision/order rows, attempt configuration and subscription terms survive an upgrade with is_free_demo=false and mock_set=null.

Targeted coverage is in `mock_tests/test_free_demo.py`: publication/Admin permissions, identical Free questions/revisions, retakes and separate results, legacy selection/resume compatibility, exam restrictions, unchanged Premium selection, withdrawal handling, database guards, publication/start concurrency and additive upgrade preservation. Existing Mock random-engine regression fixtures explicitly use Premium; billing Free-limit fixtures explicitly publish their intended demo.
