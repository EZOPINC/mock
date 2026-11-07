# Architecture decisions

Milestone 3.2 public Previous Year finalization (2026-11-04): reuse the completed
viewer and canonical slug-scoped routes. Standardize breadcrumbs/titles and fail
closed for papers whose revision translation set is missing, approval is absent,
or configured subject no longer matches. Verified-only solution components show
an unavailable state without revealing option highlights. No model/migration,
import-workflow or mock-test changes. See previous-year-viewer.md.

## D24 — Original-roadmap Milestone 3.1 administrative completion (2026-11-04)

Reuse the existing PreviousYearPaper/PaperQuestion models and multilingual revision
relationships. Add optional duration_minutes, total_marks, instructions, subject
and expected_question_count; actual count remains derived. Duration/count are
positive when set, marks are nonnegative, and a specified paper Subject restricts
question associations. Mixed-subject papers leave Subject blank. Draft assembly
may be incomplete but not over capacity; publication requires an exact declared
count. Count refers to master questions, not translations. The additive migration
preserves existing records with blank configuration. Admin groups these fields,
shows actual/expected count and retains explicit publication and readonly published
content. Import preview honors paper subject/capacity. Existing public navigation
and mock preview are preserved with no new UI functionality. See
[administration guide](previous-year-administration.md).

Milestone 2.3D (2026-11-04): the user approved exam/year/paper navigation and a
responsive Previous Year viewer over existing paper/revision/translation models.
Add a scoped year selection route, preserve old viewer URLs and pinned revisions,
apply English-before-Bengali ordering only in viewer prefetching, and provide
native collapsed verified-answer disclosures. Reuse stage/part/session as paper
labels; no duplicate paper models, migrations or test engine. See
[viewer design](previous-year-viewer.md).

**Current override:** Milestone 2.3C / D23 below supersedes earlier independent-
language/translation-grouping exclusions. Historical entries remain as a record.

Authority: approved Phase 0 **Mock Exam Platform — Database & Import Specification v1.0** supplied for Milestone 1.1A. Original approval date was not provided. The entries below were recorded on **2026-11-03**; that is the documentation date, not an invented approval date. All entries have status **Approved in Phase 0**.

| ID | Decision | Reason / resulting impact in the approved design |
|---|---|---|
| D01 | Modular Django monolith; eight apps; Django ORM and PostgreSQL as the single data source | Central Question Bank shared across workflows. PostgreSQL also used for automated tests; no SQLite fallback. |
| D02 | Django Templates, HTML, plain CSS, vanilla JavaScript, Django Admin | Keep the agreed simple stack; no React, DRF, Redis, Celery, Docker, or microservices. |
| D03 | Custom User extending AbstractUser before initial migrations | Shared authentication identity; already implemented in Milestone 1.1. |
| D04 | Previous-year pages are public | No login required; expose only published papers whose referenced revisions are approved for publication. |
| D05 | Mock and Practice require authentication | Attempts, responses, and progress are linked to users. Permission checks, CSRF, and safe redirects are mandatory. |
| D06 | No student mock-test language selector | ExamPatternSection determines `en`, `bn`, or `mixed`; mixed has no fixed language proportions. |
| D07 | English/Bengali questions are independent records | Preserve original Unicode; no translation grouping; language cannot change across a Question's revisions. |
| D08 | Exam patterns control question distribution | Versioned patterns define totals/duration/default marks; sections define subject counts/language/order/optional marks. Exactly one active pattern per exam/stage; validate counts and published availability before activation. |
| D09 | Published question revisions are immutable | Papers and attempts reference exact revisions; PROTECT historical revisions and referenced patterns. Pattern versions referenced by attempts cannot change. |
| D10 | Snapshot attempt questions, order, and effective scoring values | Preserve historical results; no repeated Question identity; enforce timing, autosave, expiry, finalization, and scoring server-side. Hide answer keys before submission. Blank answers score zero; penalties are nonnegative. |
| D11 | Preserve completed attempts/results permanently unless retention is explicitly approved | Do not silently delete historical results or introduce a retention policy. |
| D12 | Practice reuses published Question Bank records | Filter by exam/subject/topic, avoid repeated questions per session, save responses, give immediate feedback and explanation. |
| D13 | Imports default to draft and require explicit publication | Preview, validate and revalidate; reject the entire batch on any invalid row; confirm atomically with audit records. |
| D14 | Explicit import mappings and source-aware duplicate prevention | Reject ambiguous taxonomy; use file hashes/source-scoped IDs; do not silently merge similar content. Preserve source metadata rather than interpreting numeric review_status or updated_by as application identity. |
| D15 | Foreign keys, uniqueness/check constraints, and transactional cross-row validation | Enforce topic/subject and stage/exam consistency, nullable paper identity, allowed languages/answers, positive counts/duration, and nonnegative penalties. Avoid redundant indexes. |
| D16 | Implement domain models by milestone | Milestone 1.1 implements foundation and User only. Do not create all approved models at once. |

See [architecture](architecture.md), [database design](database-design.md), and [import contract](import-contract.md) for the exact rules and unresolved implementation details. OCR/PDF extraction, difficulty functionality, payments/subscriptions, advanced analytics, and translation grouping are outside the approved scope.

## Milestone 2.2 clarification — 2026-11-03

**D17 — Approved within the Milestone 2.2 request:** distinguish the working revision from the live revision. `Question.current_revision` points to the latest working revision; add nullable `Question.published_revision` for the approved live content. Add nullable, service-managed `QuestionRevision.published_at` as a permanent publication marker: a pointer alone cannot identify older published revisions after replacement. New drafts reset working review to pending without changing the live pointer or publication status. Review applies to the current working revision; explicit publication replaces the live pointer only after review. Revisions are append-only, including drafts, so content edits use the requested new-revision operation; no historical rows are overwritten or deleted.

Reason: preserve previously approved content while preparing and reviewing updates, and retain publication history and immutable content for future papers and attempts. Impact: two additional nullable fields in the new questions initial migration; future consumers must use `published_questions()` / `get_published_revision()` and the published pointer, never the working pointer. Question-row locks serialize revision numbering, review, and publication. Optional expected revision IDs reject stale review/publication requests. Bulk workflow writes are rejected because they bypass validation and locks. Only concurrency tests use TransactionTestCase.

The Question source ID remains nullable and is not globally unique. Its source-scoped uniqueness key remains unspecified in Phase 0 and must be approved before import deduplication is implemented; Milestone 2.2 introduces no guessed source scope.

## Milestone 3.1 clarifications — 2026-11-03

**D18 — Previous Year Paper identity and history:** identity compares exam, optional stage, year, and trimmed, case-insensitive paper_name/part/session. Optional part/session blanks normalize to NULL; the PostgreSQL expression uniqueness constraint coalesces optional identity values, so NULL and empty values cannot create duplicates. This avoids requiring PostgreSQL 15's NULLS NOT DISTINCT feature. Add a derived, noneditable `PaperQuestion.question` FK solely to enforce database uniqueness of (paper, Question identity) across revisions; its value is taken from the selected revision during validated saves. Order and original question number are also unique per paper, and order/year must be greater than zero.

New or explicitly replaced associations require the Question's approved live revision and matching QuestionExam association. A working draft's pending review does not invalidate a previously reviewed, permanently marked published revision (D17). Existing rows keep historical published revisions after Question Bank updates, including paper republication; they are never automatically refreshed. Publication revalidates historical approval and exam membership under paper/question row locks and rejects empty papers. Public queries fail closed for invalid papers and inactive taxonomy. Public detail rendering holds the paper lock until its rows are rendered to prevent concurrent draft edits from appearing after a visibility check.

Published paper composition/metadata is edited only after explicit unpublication, followed by revalidation and republication. Admin provides a permission-protected complete-paper preview. All paper FKs use PROTECT; guarded model/queryset writes prevent bulk bypass of the workflow. Impact: two new previous_year models and their initial migration; reusable publication/query services and public guest browsing; no question revision migration or automatic replacement.

**D19 — Scope sequencing approved in the Milestone 3.1 request:** Excel/CSV import and source-scoped deduplication are deferred until the core application is usable. The future import contract remains a design reference; this milestone implements neither import nor deduplication.

## Future changes

### D20 — Import release (2026-11-04)

Approved by the explicit Milestone 2.3 request, which supersedes D19's deferral for CSV/XLSX import only; source-scoped identity remains deferred. Batch-selected Exam/Paper is authoritative. Legacy review_status and verification_notes are retained as audit metadata; **neither marks a Question reviewed** (this supersedes the earlier verification_notes mapping). Preview writes no domain/audit rows; expiring private JSON staging is uploader-owned. ImportBatch/ImportedQuestion are the two new audit models; batch adds paper FK, unique staging UUID, and mapping_metadata, and row audit adds source_metadata containing bounded original/corrected values. Completed file hashes are unique globally, conservatively blocking repeat uploads without merging content. Errors block the entire transaction; content matches are warnings.

Smallest integration change: PaperQuestion.save accepts an internal `_import_draft=True` option solely to associate an unpublished paper with the current pending-review revision of a new draft Question and matching QuestionExam. Normal manual association validation remains unchanged; paper publication always uses strict reviewed/published checks without this option. Public queries still exclude drafts. No previous_year schema change or revision mutation is required. Questions are later reviewed/published using existing services, followed by explicit paper publication. The operational limits, normalization rules, alias conventions, permission set, and cleanup procedure are documented in [import guide](import-guide.md).

Architecture changes require explicit review and approval. Record each approved change with:

| Field | Required content |
|---|---|
| ID / date | Unique decision ID and actual decision date (YYYY-MM-DD) |
| Status / approval | Proposed, approved, or superseded; explicit approval reference |
| Decision | Exact change and any decision it supersedes |
| Reason | Problem, rationale, and relevant tradeoffs |
| Impact | Affected apps/models/import contracts, historical integrity, compatibility, and migration needs |

Unspecified details are clarification items, not implied decisions. Milestone 1.1A introduced documentation only; D17 records the later Milestone 2.2 clarification.


## D21 - Unified import release (2026-11-04)

### Later approved General Questions module (2026-11-04)

The user requested a Previous Year-like module for General imported questions and
whole-batch administration. Reuse completed General ImportBatch collections and
existing Question Bank records; keep the eight-app monolith with no new models or
migration. Public guest browsing at /general-questions/ shows only approved live
revisions associated with active exams/authorities, with exam/subject/topic/language
filters and paginated solutions. General imports remain draft by default.

Permission-protected management lists all General import batches for staff with
View import batch + Change question. Review entire batch and Publish entire batch
are separate explicit POST operations, using existing review/publication services
in an atomic transaction. Signed revision-state snapshots reject stale submissions;
ordered question locks serialize transitions. Any question validation failure
rolls back the entire batch action. Public pages omit source filenames/uploader
and audit metadata. Previous Year publication and future test engines are unchanged.

Later user-approved subject clarification (2026-11-04): a blank subject with no
explicit mapping/batch default resolves to UnIdentified. Preview is read-only;
confirmation creates or reuses the fallback transactionally, checking Add subject
permission for creation. Code/slug collisions and ambiguous existing fallback
records require resolution. Nonblank unknown labels still require mapping, and
topic/subject validation remains strict. No schema migration is required.

Later user-approved language clarification (2026-11-04): absent row/batch language
may be inferred from question/options Unicode scripts: Bengali letters → bn,
otherwise Latin text → en (including Greek mathematical notation). Explicit
values take precedence; ambiguous/unsupported text still requires correction.
Preview warns about inferred values; original empty values remain in audit and
resolved language is recorded separately. UTF-8 encoding alone is not a language
detector. This supersedes D21's earlier explicit-default-only language rule.

Approved by the Milestone 2.3B request, superseding conflicting D20 import rules.
Use one mandatory two-mode interface with shared parsing, preview and atomic
confirmation. Six headers are mandatory; subject/language/answer become optional
file columns but remain mandatory resolved values at confirmation because the
existing Question Bank requires them. Explicit batch Subject/Topic/Language
defaults fill only missing row values; no automatic English, answer or taxonomy.

Previous Year requires one Exam/Year, optional Stage, and creates/reuses a matching
draft paper using the default name Previous Year Paper when omitted. General
requires one or more Exams, optionally resolves explicit row categories against
existing taxonomy, and creates no paper records. Source tags never override
Previous Year selections. All questions remain draft/pending_review; publication
and revision services remain unchanged.

Necessary audit schema change: nullable ImportBatch.paper for General mode,
context_sha256 plus unique(file_sha256, context_sha256) instead of global file
hash uniqueness. Migration 0002 backfills historical paper contexts, preserving
completed-file guards and old audit links without rewriting migration 0001.
Context is mode, sorted selected exams, exam strategy and normalized paper identity
where applicable; excludes row edits, uploader and classification defaults.
Staging-token uniqueness/idempotency is unchanged. Resolved row associations are
also retained in source_metadata. See [import guide](import-guide.md).


## D22 - Dedicated general_question application (2026-11-04)

Approved by the user's explicit request for a general_question app analogous to
previous_year, superseding the earlier eight-app/module-only implementation.
Move General views/forms/URLs/templates/tests out of questions and batch
publication services out of imports into general_question. Preserve the public
URL prefix and general_questions namespace, import ownership and publication
services. Add GeneralQuestionBatch as a filtered proxy over ImportBatch so Django
Admin has a dedicated General Questions section, showing only completed General
uploads with review/publication counts and links to signed whole-batch controls.
The initial proxy migration records model metadata/permissions and creates no
new storage table. Existing import/question permission checks remain effective;
questions/revisions are not duplicated or moved. Existing imports automatically
appear; no data migration, reimport, or new importer is necessary.


## D23 - Multilingual master questions (2026-11-04)

Approved by the Milestone 2.3C request, explicitly superseding D07 and prior
translation-grouping exclusions. One master Question owns shared answer,
difficulty, subject/topic and exam associations; available QuestionTranslation
rows hold language content within immutable QuestionRevision snapshots. Preserve
existing primary revision fields as compatibility content, and shared revision
answer/difficulty as historical snapshots. New translations create pending-review
revisions; live and paper snapshots never auto-change. Backfill all existing
revisions without merging identities or rewriting earlier migrations.

Bilingual import matching is source-context-local by question number, requires
explicit preview confirmation and agreement of shared attributes, and never
merges ambiguous records. Preserve row audits and exam/year associations.
Language-code validation/configuration supports future locales; infer only en/bn.
Display available translations side-by-side responsively with prefetched queries.
The user's clarification authorizes an authenticated mock question preview only,
without answer keys, attempts, timing or a test engine. See multilingual-questions.md.

## D24 - Wide bilingual extraction imports (2026-11-04)

Reason: the supplied previous-year PDF extraction places English/Bengali content
in explicit per-language columns on the same row. Reuse the existing master,
immutable translations and transactional importer; create no parallel storage.
Impact: accept wide CSV/XLSX alongside existing long rows, preserve extraction
flags in audit, and require corrections for incomplete/conflicting blocks.
Explicit wide columns establish one source-row identity; separate long rows still
require pairing approval. The user explicitly requires verified answer correction
before import. Handwritten marks never populate keys or approve/publish content.
No existing records, associations or migrations change.

## D25 - Mock pattern configuration (2026-11-05)

Reason: Milestone 4.1 introduces configurable mock patterns using the approved
Question Bank. Impact: explicit draft/active/inactive status, pattern default
marks with nullable section overrides, optional subject/topic filters, and
transactional activation with one active pattern per exam/stage. Preserve the
approved en/bn/mixed section language rule and one logical multilingual question.
Active configuration requires deactivation before editing. Activation checks
section totals, maximum marks and distinct-question capacity across overlapping
sections. Availability is not a reservation; generation must recheck later.
Version is retained as descriptive metadata with no invented uniqueness key.
No attempt or test generation functionality is added.

## D26 - Fixed mock attempts and repeat-start safety (2026-11-05)

Reason: Milestone 4.2 requires persistent authenticated mock attempts with a fixed
question set. Impact: MockAttempt and AttemptQuestion pin immutable revisions,
master identities, section/order and effective marks; configuration/labels are
snapshotted. Patterns/sections used by attempts cannot be reconfigured; create a
new version. Start uses a transaction, user/pattern/question locks and a partial
unique open-attempt constraint. Repeat starts resume the same open user/pattern
attempt; insufficient pools leave no partial attempt. Capacity-based selection
handles overlapping filters without repeating a multilingual master. Views are
owner-only and omit solutions. Reserved Submitted/Expired states do not implement
submission or expiry; those, timers, answer saving and scoring remain 4.3.

## D27 - Server-authoritative mock execution (2026-11-05)

Reason: Milestone 4.3 adds timer, answer persistence, submission and scoring.
Impact: extend existing attempts/rows with deadlines, versioned response state
and final results. Parent-attempt locks serialize saves/finalization; global
optimistic versions reject stale writes and latest-request tokens allow retries.
Submission confirmation checks its displayed version. Score with frozen revision
keys and marks, using Decimal; multilingual questions count once and review flags
do not alter scoring. Finalized responses/results cannot change. Active views/API
omit keys/solutions; finalized owner-only review reveals them. Expire on server
access and through the idle-expiry management command; no scheduler is introduced.
Backfill historical deadlines from stored configuration rather than current patterns.
No further engine or Milestone 5.1 work is included.

## D28 - Untimed practice sessions and locked feedback (2026-11-05)

Reason: Milestone 5.1 requires persistent practice and immediate feedback separate
from official mocks. Impact: PracticeSession and PracticeQuestion reuse published
revision/translation snapshots and shared Question Bank eligibility. PracticeQuestion
implements the planned PracticeResponse, with no duplicate storage. Required subject,
optional topic and supported question counts define one unique-master selection pool.
Token-scoped start retries resume their original session. First answer submission locks
the response; same-answer retries are idempotent and conflicting changes fail. Reveal
solutions only after that individual answer. Pause retains In Progress; all answered
completes the session, or the user explicitly abandons it. Parent locks serialize
concurrent responses and abandonment. Freeze classification labels for summaries.
No timing, mock-score integration or Milestone 6.1 functionality is added.

## D29 - Public previous-year viewing modes (2026-11-07)

Reason: the user requests a year-level choice between Direct Answers and Practice
Paper. Impact: mode-aware paper/session navigation, direct highlighted/open solutions,
and per-question selection feedback in the public full-paper practice viewer. Reuse
published paper relationships and pinned multilingual revisions. Do not add session
models or require login: this paper practice is temporary and resets on reload,
while persistent Practice and mock scores remain separate. Server-side POST feedback
validates choices, publication, ownership of the row by its paper and CSRF. No schema
or publication policy changes.
