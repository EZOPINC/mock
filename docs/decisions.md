# Architecture decisions

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

Architecture changes require explicit review and approval. Record each approved change with:

| Field | Required content |
|---|---|
| ID / date | Unique decision ID and actual decision date (YYYY-MM-DD) |
| Status / approval | Proposed, approved, or superseded; explicit approval reference |
| Decision | Exact change and any decision it supersedes |
| Reason | Problem, rationale, and relevant tradeoffs |
| Impact | Affected apps/models/import contracts, historical integrity, compatibility, and migration needs |

Unspecified details are clarification items, not implied decisions. Milestone 1.1A introduced documentation only; D17 records the later Milestone 2.2 clarification.
