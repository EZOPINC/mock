# Architecture

Authority: **Mock Exam Platform — Database & Import Specification v1.0**, supplied as the approved Phase 0 specification. This document describes the approved target; the implementation status below distinguishes existing functionality. Changes require explicit review and approval.

## Structure

A modular Django monolith uses the Django ORM and one PostgreSQL UTF-8 database as the single data source for users, the centralized Question Bank, associations, attempts, and import audits. Development and automated tests use PostgreSQL; no SQLite fallback. The interface uses Django Templates, HTML, plain CSS, and vanilla JavaScript.

| Application | Responsibility |
|---|---|
| `core` | Shared foundation, home page, database readiness endpoint |
| `accounts` | Custom `AbstractUser` user model and authentication foundation |
| `exams` | Authorities, exams, optional stages, subjects, topics |
| `questions` | Central Question Bank, immutable published revisions, exam and source associations |
| `imports` | Administrative CSV/XLSX validation, preview, transactional confirmation, audit |
| `previous_year` | Historical papers and ordered revision associations; public published-paper browsing |
| `mock_tests` | Versioned patterns and sections, timed attempts, saved answers and scoring |
| `practice` | Filtered sessions, saved responses, immediate feedback and progress |

`config` holds project configuration and entry points; it is not a domain app.

## Navigation and access

| Destination | Approved access and behavior |
|---|---|
| Home | Existing public `/` page |
| Health | Existing public `/health/`; database query, HTTP 200 when ready, 503 on database failure |
| Administration | Existing `/admin/`; Django staff authentication and permissions |
| Previous Year | Public, no login; only published papers with revisions approved for publication |
| Mock Test | Authentication required; pattern determines distribution and language |
| Practice | Authentication required; exam/subject/topic filtering |
| Imports and publication | Administrative operations with permission checks |

Future route paths, menu hierarchy, and detailed administrative roles are not specified. CSRF protection, safe redirects, and permission checks are mandatory.

## Questions and languages

Each Question represents one language. English (`en`) and Bengali (`bn`) are independent records, with no translation grouping. Preserve original Unicode question text, options, and explanations. A Question's language cannot change across revisions.

Question stores identity, classification, publication/review state, and a nullable current-revision reference. QuestionRevision stores language, content, options, answer, and explanation. Published revisions are immutable. Historical papers and responses reference specific revisions rather than mutable current content. A Topic must belong to the Question's Subject; a Question may belong to multiple exams and sources.

Implemented in Milestone 2.2: `current_revision` is the working pointer; the additional `published_revision` pointer preserves approved live content while a new draft awaits review. `published_at` permanently identifies revisions that have been published. Revision content is append-only. Reusable transactional services create revisions, review, and publish with parent-row locks. Public consumers use `questions.services.published_questions()` or `get_published_revision()`, never the working pointer. See [D17](decisions.md#milestone-22-clarification--2026-11-03).

## Workflows

- **Previous Year:** resolve exam, optional stage, year, paper, part, and session; associate revisions using original numbering and order. A question may appear in multiple papers. Publish only after the paper and its referenced revisions are approved.
- **Mock Test:** use the active ExamPattern for an exam/stage. ExamPatternSection controls subject counts, order, `en`/`bn`/`mixed` eligibility, and optional marks overrides. Mixed permits both languages without fixed proportions. There is no student mock-test language selector. Validate counts and published availability before activation. Persist revisions, order, and effective marks when creating an attempt; enforce autosave, timing, expiry, submission, and scoring on the server. Do not expose answer keys before submission.
- **Practice:** select published questions by exam and optional subject/topic, avoid duplicate questions in a session, save responses, and show immediate answer feedback and explanation.
- **Import:** admin preview and confirmation create auditable drafts in one transaction; explicit review and publication follow. See [import contract](import-contract.md).

## Milestone 1.1 implementation inspected

Milestone 2.3 supersedes the import deferral for the single-paper administrative CSV/XLSX workflow. It adds private expiring preview staging, explicit alias/taxonomy resolution, transactional draft import, and batch/row audit models. A narrow internal draft-paper association option is used only during import; review, question publication, paper publication, and public visibility remain separate and validated. Source-scoped deduplication remains deferred. See [import guide](import-guide.md) and D20 in [decisions](decisions.md).

Later implementation status: Milestone 3.1 adds paper administration, transactional publication/unpublication, and public year-grouped paper lists and solutions. Paper associations preserve historical published revisions; new associations require the approved live revision and matching exam membership. Published papers must be unpublished before editing. Exam detail now links to its scoped paper list. Imports and source-scoped deduplication are deferred until the core application is usable (D19); see [decisions](decisions.md) for paper identity and duplicate-question enforcement (D18). The original Milestone 1.1 snapshot below remains historical context.

All eight apps are installed. Only `accounts.User` and its initial migration are implemented as application models; six domain apps remain skeletons. `core` supplies home and health views. Django Admin, authentication/session/CSRF middleware, shared templates, static CSS, ASGI/WSGI entry points, password validators, environment configuration, and timezone-aware timestamps are configured. Timezone defaults to UTC; debug defaults to false; session and CSRF cookies require HTTPS when debug is false.

Existing nine tests cover PostgreSQL, home/health, health failure, the custom user, password hashing, admin login/session/access, and CSRF. The target domain workflows above are not yet implemented. No functionality is added by Milestone 1.1A.

See [database design](database-design.md) and [decisions](decisions.md). Approved boundaries exclude OCR/PDF extraction, difficulty functionality, payments/subscriptions, advanced analytics, translation grouping, React, DRF, Redis, Celery, Docker, and microservices.


## Unified import (Milestone 2.3B)

User-approved General Questions module: `general_question.views` provides public
General import collections/solutions and staff-only whole-batch review/publication.
It reuses ImportBatch and existing Question services. The dedicated
`general_question` app now owns this module, with an admin-only batch proxy. Published-only browsing supports exam/subject/topic/language filters.
Signed snapshots, CSRF, permissions and atomic row-locked services protect the
separate whole-batch Review and Publish actions. See [import guide](import-guide.md).

The administrative import interface now requires Previous Year Questions or
General Question Bank mode. It shares bounded parsing, private expiring staging,
editable preview and transactional confirmation. Previous Year imports use one
exam/year and optional stage with draft-paper creation/reuse. General imports use
selected exams or explicitly resolved row exams, without paper records. Batch
taxonomy/language defaults fill missing row values only. Incomplete subject,
language or answer blocks confirmation; publication/immutability services remain
unchanged. D21 supersedes earlier single-paper/global-file-hash import rules; see
[import guide](import-guide.md).


## Dedicated General Questions app (2026-11-04)

At the user's explicit request, general_question is a ninth domain app alongside
previous_year. It owns General collection browsing, filters, templates, tests and
whole-batch review/publication services. The GeneralQuestionBatch proxy over
ImportBatch provides a distinct Django Admin module without copying records or
creating a new data table. Its migration adds proxy-model metadata/permissions
only. Existing URLs and the general_questions namespace remain unchanged;
Question and QuestionRevision remain solely in the central questions app.
