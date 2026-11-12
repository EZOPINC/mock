# Database Design - Current Implementation

Source-verified on 2026-11-12. This replaces the mixed target/implemented inventory.
For workflows use [architecture](architecture.md); for files use [MODULE_MAP](MODULE_MAP.md).
Actual models and migrations are authoritative; no live schema/data audit is claimed.

## Identity and catalogue

| Model | Key relationships / state | Important integrity |
|---|---|---|
| accounts.User | AbstractUser; configured AUTH_USER_MODEL | Django user/auth constraints |
| exams.ExamAuthority | name, code, slug, active flag | Unique code/slug |
| exams.Exam | authority, name, code, slug, active flag | Authority-scoped code/slug |
| exams.ExamStage | exam, name, code, order | Stage must belong to its selected Exam |
| exams.Subject | name, code, slug | Shared independently of Exam |
| exams.Part | Subject anchor, stable code, name/slug/order | Scoped names/slugs; protected established ancestry |
| exams.Module | Subject anchor; optional immediate Part | Direct Subject or Part parent |
| exams.Chapter | Subject anchor; optional immediate Part/Module | At most one non-Subject immediate parent |
| exams.Topic | Subject anchor; optional immediate Part/Module/Chapter | Same-Subject ancestry; optional/skipped levels |

QuestionExam determines exam membership; there is no separate Subject-to-Exam owner.
Codes are stable; parent-scoped names/slugs permit the same label in different branches.
Model validation and PostgreSQL triggers enforce ancestry. Topic moves within an
existing Subject differ from immutable Part/Module/Chapter parent paths.
See [flexible taxonomy](flexible-taxonomy.md) for the exact optional-parent constraints.

## Question Bank

| Model | Persisted role | Important integrity |
|---|---|---|
| questions.Question | Master identity; Subject, legacy primary Topic, working/live pointers, editorial status, mirrored answer/difficulty | Both revision pointers belong to this master; default draft/pending review |
| questions.QuestionRevision | Numbered primary-language content, answer, difficulty, publication timestamp | Unique master/revision number; append-only content, including drafts |
| questions.QuestionTranslation | Language content within one revision | Unique revision/language; primary translation matches compatibility fields |
| questions.QuestionTopic | Master/Topic association and primary flag | Unique pair; one primary; tags share Subject; pointer/tag compatibility |
| questions.QuestionExam | Master/Exam association | Unique pair; indexed exam/question access |
| questions.QuestionSource | Source name/document | Provenance identity |
| questions.QuestionSourceReference | Master/source/page/question-number metadata | Protected provenance references |

The master, not a translation or revision, is the deduplication identity.
Question.correct_answer/difficulty_level mirror working content, not necessarily live content.
Use the approved revision for public rendering and the frozen revision for historical grading.
Working revisions can be pending while an older published revision remains live.
New content/translation changes create new revision snapshots; they do not update old rows.
Publishing has a guarded one-time published_at write, not a general mutation exception.
Language codes use model validators/configuration; current eligibility supports English/Bengali.
source_question_id is optional and not globally unique. No source-identity merge key is implemented.

## Import audit and collections

| Model | Persisted role | Important integrity |
|---|---|---|
| imports.ImportBatch | Uploader, hashes, unique staging token, mode/selection metadata, optional paper, row counts/times | Unique file_sha256/context_sha256 pair; staging UUID unique |
| imports.ImportedQuestion | Batch/source row/master, action, source_metadata | Unique batch/source-row pair; protected audit/master links |
| general_question.GeneralQuestionBatch | Proxy for general-mode ImportBatch records | No separate collection table or copied questions |

Original/corrected/resolved values are bounded audit JSON, not undefined future fields.
Import creates pending-review drafts; metadata cannot silently approve or publish them.
Same file/different canonical import context is distinct. Similar text does not merge masters.
See [import contract](import-contract.md) for pairing, limits and source-metadata rules.

## Previous-Year Papers

| Model | Persisted role | Important integrity |
|---|---|---|
| previous_year.PreviousYearPaper | Exam, optional Stage/Subject, year/name/part/session; publication and optional duration/marks/instructions/declared count | Normalized paper identity; Stage/Subject/count consistency |
| previous_year.PaperQuestion | Paper, master, fixed approved revision, printed number, order | Unique paper/master, paper/order and paper/question_number |

Paper identity compares trimmed case-insensitive textual components and coalesces
nullable components. Part/session blanks normalize rather than creating duplicate identities.
PaperQuestion.question is derived from question_revision during validated saves.
New manual rows use the approved live revision and matching exam membership.
Existing rows retain historical approved revisions after a later publication.
An internal import-only draft path permits attaching new drafts to unpublished papers.
Publication is explicit, transactional and nonempty; declared counts must match exactly.
Published papers must be unpublished before composition/metadata edits.
Public selectors fail closed on invalid paper rows or inactive catalogue membership.

## Mock configuration and attempts

| Model | Persisted role | Important integrity |
|---|---|---|
| mock_tests.ExamPattern | Exam/optional Stage, version, duration/totals/default marks, activation status | Version/activation constraints; guarded active or previously used configuration |
| mock_tests.ExamPatternSection | Ordered quota, optional Subject/Topic/language and mark overrides | Valid scope/language/positive quota/order; frozen once used |
| mock_tests.SectionSelectionRule | Exactly one Subject/Part/Module/Chapter/Topic scope, quota, difficulty and random/manual mode | Rule order unique per section; quotas match section |
| mock_tests.ManualRuleQuestion | Ordered explicit master choices | Unique rule/master and rule/order; validated eligible membership |
| mock_tests.MockAttempt | Owner, pattern, frozen configuration/deadline, status, save version/token/position, aggregate results | One open owner/pattern; coherent deadlines/finalized fields; protected history |
| mock_tests.AttemptQuestion | Attempt/section/master/fixed revision/order, effective marks, answer/review flag/time/awarded marks | Unique attempt/master and attempt/order; approved revision; guarded writes |

Selection allocates overlapping pools globally without repeating a master across sections.
AttemptQuestion rows pin effective marks and revision IDs; later edits do not regrade history.
Server finalization stores totals/sections once; unanswered=0, correct=positive mark,
incorrect=negative deduction. Client data never supplies answer keys, score or deadline.
Autosave versions and UUID tokens are concurrency metadata, not question identity.

## Shared Practice and Revision engine

| Model | Persisted role | Important integrity |
|---|---|---|
| practice.PracticeSession | Owner, kind, optional Exam/Subject/Topic scope, unique start token, frozen configuration, status/times | Practice kind requires Exam/Subject; revision kind has all three scope FKs null |
| practice.PracticeQuestion | Session/master/fixed revision/order, frozen classification, answer/correctness/time | Unique session/master and session/order; coherent answer state; locked after feedback |
| revision.RevisionSession | Revision-only proxy over PracticeSession | No extra session/response table |
| revision.SavedQuestion | Owner/master, saved_at, personal_note, reviewed_at, review_count, is_mastered | Unique user/master; personal state independent of assessment history |

There is no implemented PracticeResponse model; PracticeQuestion owns the response fields.
Normal Practice and Revision share immutable content/order and answer/completion services.
Review tracking updates the existing owner bookmark on the first revision-session answer.
A repeated answer/resume does not recount; mastery is manual and independent of correctness.
Deleting a bookmark removes personal state, not historical session rows/results.
Notes permit up to 10,000 characters; defaults preserve earlier bookmarks.

## Migration and transaction anchors

| Concern | Source |
|---|---|
| Optional parents/stable codes/guarded reverse | exams/migrations/0004_flexible_academic_taxonomy.py |
| Primary translation compatibility/backfill | questions/migrations/0002_questiontranslation_and_more.py; 0003_backfill_translations.py |
| Deferred primary tag/pointer checks | questions/migrations/0005_primary_topic_compatibility.py |
| Contextual import uniqueness/backfill | imports/migrations/0002_unified_import.py |
| Declared paper configuration/count | previous_year/migrations/0002_previousyearpaper_duration_minutes_and_more.py |
| Mock deadline backfill/checks | mock_tests/migrations/0004_backfill_attempt_deadlines.py; 0005_mockattempt_mock_attempt_deadline_valid_and_more.py |
| Detailed selection rules | mock_tests/migrations/0006_sectionselectionrule_manualrulequestion_and_more.py |
| Shared session type/scope | practice/migrations/0002_practicesession_kind_alter_practicesession_exam_and_more.py |
| Personal progress and revision proxy | revision/migrations/0002_savedquestion_is_mastered_and_more.py; 0003_revisionsession.py |

Guarded saves, row locks, uniqueness/check constraints and PostgreSQL triggers work together.
Primary tag/pointer consistency includes deferred commit-time checks; partial intermediate
states are not permission to bypass the atomic tagging workflow. Reverse migrations can
intentionally reject data that an older schema cannot represent safely.

## Limits of this reference

Inspect current Meta constraints/indexes rather than treating an old recommended-index list
as proof of installed indexes. Runtime schema, data health and server version are unverified.
No AI, token-auth mobile API, separate PracticeResponse table or copied Revision engine is
implied by older target diagrams. Feature-specific policies remain in their owning services.
