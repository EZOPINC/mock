# Project Architecture

Source-verified reference, 2026-11-12. Source code overrides this document.
Use MODULE_MAP.md for navigation and DEVELOPMENT_RULES.md for change safety.
This consolidates older roadmap notes into the current implementation.
The tracked filename is `docs/architecture.md`; retain its casing in links.

## Stack and layout

- Python with Django `>=5.2.19,<5.3`; PostgreSQL via psycopg 3.
- `requirements.txt` also declares python-dotenv, openpyxl and defusedxml.
- A modular Django monolith uses server-rendered templates and session authentication.
- Vanilla JavaScript enhances forms, navigation and asynchronous saves.
- Tailwind 4.3.5 is pinned with checksums in `tools/tailwind-lock.json`.
- `assets/tailwind.css` is source; `static/css/tailwind.css` is compiled output.
- `tools/build_css.py` uses a standalone compiler; Node/npm is not required.
- `static/css/site.css` and feature stylesheets provide fallback/scoped presentation.
- `templates/base.html` loads shell assets; bookmark CSS follows feature head assets.
- `config/` holds settings, root URLs, admin customization, ASGI and WSGI.
- Settings load environment values; never copy local values into documentation.
- PostgreSQL is required; settings provide no SQLite fallback.
- `manage.py`, `requirements.txt`, `templates/`, `static/` and `tools/` are shared roots.
- Ignore virtual environments, caches, staged uploads and collected/generated assets.

## App boundaries

| App | Owns | Main consumers |
|---|---|---|
| `core` | Curated home catalogue; database readiness endpoint | Public landing/shared shell |
| `accounts` | Custom User, registration, account views, learning dashboard | User-owned workflows |
| `exams` | Authorities, exams, stages and normalized academic taxonomy | Question discovery |
| `questions` | Master identities, immutable content, translations, topic/exam/source tags | All assessment/content apps |
| `imports` | Bounded ingestion, staged correction/pairing, confirmation and audit | Staff UI; General collections |
| `previous_year` | Papers, ordered approved-revision associations, public reader | Imports, admin, students |
| `general_question` | General-import collections and whole-batch review/publication | Staff/public collections |
| `mock_tests` | Pattern/rule configuration, timed attempts, autosave and scoring | Authenticated exams |
| `practice` | Untimed snapshots, answer locking, feedback and progress | Practice and Revision sessions |
| `revision` | Bookmarks/notes/mastery, bank, revision selection, topic exploration | Registered students |

`config` is project wiring, not a domain app. `questions` has no standalone URL module.
Question admin is in `questions/admin.py`; student rendering is downstream.
`general_question` is the package; its URL namespace is `general_questions`.

## Models and identity

- `accounts.User` extends AbstractUser and is AUTH_USER_MODEL.
- ExamAuthority -> Exam -> ExamStage is the exam catalogue, with protected relations.
- Authorities/exams have active flags; a stage belongs to one exam.
- Subject is independent of exam membership.
- Academic paths: Subject -> optional Part -> optional Module -> optional Chapter -> Topic.
- Each hierarchy node has its Subject anchor and at most one immediate parent.
- Modules may attach to Subject; Chapters to Subject/Part/Module; Topics to any ancestor.
- Names/slugs are scoped to actual parents; stable codes identify existing nodes.
- Model validation and PostgreSQL triggers guard codes and established ancestry.
- Topic immediate-parent moves within its Subject differ from immutable parent nodes.
- Question is the deduplication identity, not a language, paper row or attempt row.
- Question has one Subject, legacy primary topic, and multiple QuestionTopic tags.
- All tags share its Subject; classified questions have one matching primary tag.
- QuestionExam supplies many-exam membership; there is no direct Subject-to-Exam ownership.
- QuestionSource and QuestionSourceReference retain provenance and page references.
- QuestionRevision stores numbered content, answer, difficulty and publication time.
- QuestionTranslation stores language content, unique within each revision/language pair.
- Primary-language revision fields remain for compatibility with older consumers.
- Configured languages are English (`en`) and Bengali (`bn`).
- current_revision is working content; published_revision is the approved live pointer.
- Master answer/difficulty mirror the working revision; scoring uses frozen content.
- A new revision resets review status; an older published revision can remain live.
- Revision content is append-only, including drafts; publication permits one guarded timestamp write.

## Shared interfaces and dependencies

| Interface | Responsibility / return |
|---|---|
| `questions.services.create_question` / `create_revision` | Create masters/new multilingual snapshots |
| `questions.services.mark_reviewed` / `publish_question` | Explicit review/publication; optional expected revision ID |
| `questions.services.published_questions` | Published master queryset and approved content preloads |
| `questions.eligibility.eligible_question_ids` | Eligible master-ID set by exam/language/optional scope |
| `questions.tagging.set_question_topics` | Atomic tag replacement and legacy primary synchronization |
| `questions.selectors.questions_by_topics` | Distinct masters for explicit topic IDs |
| `previous_year.services.published_papers` | Public papers; fails closed on invalid associations |
| `practice.discovery.PracticeTaxonomy` | Eligible descendant pools and frozen filter labels |
| `practice.services.assemble_session` / `submit_answer` | Shared snapshots and locked feedback |
| `revision.selectors.visible_questions` | SQL eligibility plus owner-specific open-mock exclusions |
| `revision.exploration.related_questions` | Scoped, source-excluding related master queryset |

Publication alone is not full eligibility: exam activity, translations and access rules matter.
`exams.selectors.subjects_for_exam` derives membership, not full question eligibility.
`mock_tests.services.eligible_question_ids(section)` is a section adapter with a different signature.
Imports depend on Question workflows/paper models; General collections depend on import audit.
Revision reuses Practice services; Practice lazily calls the Revision first-answer review hook.
Account dashboard excludes revision-kind sessions from ordinary Practice statistics.

## Question and taxonomy workflow

1. Staff create a master/draft through admin forms and Question services.
2. Edits create a new numbered revision and its language snapshot.
3. Review validates working content; publication selects its approved revision.
4. Consumers read the published pointer or an already-frozen approved revision.
5. Tag services synchronize current classification without rewriting historical content.
6. Descendant discovery includes secondary tags and deduplicates master IDs.
7. Taxonomy integrity audits inspect ancestry and compatibility assumptions.

## CSV/XLSX import workflow

1. Staff access `/admin/question-import/`; permission requirements depend on mode.
2. parse_upload accepts UTF-8 CSV/XLSX within byte/row/column/cell bounds.
3. Formula/error cells, macros and external-link workbooks are rejected.
4. staging stores owner-bound expiring JSON with token locks and version digests.
5. validate resolves selection, exams, language/translations, taxonomy and row errors.
6. Source-local translation groups need explicit approval of their current signature.
7. Corrections invalidate stale approvals; duplicate text warns rather than merging masters.
8. Missing named Parts/Modules/Chapters/Topics can be proposed under an existing Subject.
9. Preview resolution stages proposals; confirmation persists them atomically.
10. Row resolution never auto-creates Subjects; explicit privileged admin actions differ.
11. confirm_import rechecks owner/permissions, locks exams/taxonomy and revalidates.
12. It creates pending-review drafts, topic/exam/source links and optional draft paper rows.
13. ImportBatch/ImportedQuestion retain original/corrected/resolved audit metadata.
14. Staging tokens and file/context uniqueness prevent duplicate confirmation/import.

Default bounds: 5 MB upload, 2,000 rows, 64 columns, 32,000 characters per cell.
Staging defaults to two hours; its configured root is private server-side storage.
General mode creates no paper. Previous-Year mode targets one unpublished paper/exam.
Import does not silently publish questions; review/publication remain explicit.

## Previous-Year and General collections

- PreviousYearPaper belongs to an Exam with optional Stage/Subject/configuration metadata.
- PaperQuestion binds a master to a fixed approved revision, number and display order.
- Paper constraints prevent duplicate master/order/number associations within a paper.
- The controlled _import_draft path can attach draft questions to unpublished import papers.
- Paper publication checks nonempty rows, membership and declared counts under locks.
- Published paper editing requires unpublication; old approved references remain historical.
- Public browsing is Exam -> Year -> Paper -> direct-answer or paper-practice mode.
- paper_answer gives reader feedback without creating persistent PracticeSession records.
- GeneralQuestionBatch is an ImportBatch proxy filtered to general-mode collections.
- General public views expose published questions; staff actions check signed fingerprints.
- transition_batch atomically reviews/publishes the inspected working revisions.

## Mock Test workflow

1. Admin configures ExamPattern, sections, totals, duration and marking defaults.
2. Optional SectionSelectionRule selects exactly one taxonomy scope and a quota.
3. Rules support normalized difficulty and random/manual choices with descendant tags.
4. ManualRuleQuestion records explicit ordered master choices.
5. Availability checks quotas/overlap; allocation prevents duplicates across sections.
6. Activation is explicit; active/previously attempted configurations have guarded edits.
7. start_attempt locks owner/configuration/candidates and rechecks eligibility.
8. MockAttempt freezes configuration/deadline; AttemptQuestion freezes revision/order/marks.
9. Resume keeps the existing open attempt rather than selecting a fresh set.
10. save_response checks owner, action, row, version, UUID token and position.
11. Retry recognition applies to the latest save token/version pair.
12. Conflicts return 409; finalized attempts reject changes; expiry is server-authoritative.
13. Finalization awards positive marks, subtracts penalties and scores unanswered rows zero.
14. It freezes totals/section results; active responses do not serialize answer keys.
15. expire_mock_attempts exists; external scheduling is not established by this scan.

refresh_attempt, status checks and relevant views can finalize elapsed attempts.
History uses frozen revisions/marking, not current taxonomy or mutable master answers.

## Practice and Revision sessions

- Practice UI: category/authority -> exam -> subject -> module -> difficulty -> session.
- Eligible module cards replace the old hierarchy-dropdown setup.
- Subjects without eligible modules can continue with the whole subject.
- Difficulty uses published values; unspecified difficulty is an explicit choice.
- The current UI uses all questions at that level; service counts/filter support remains.
- PracticeSession/PracticeQuestion persist revisions/order, answers and classification.
- submit_answer gives immediate feedback, locks the answer and auto-completes the last row.
- A repeated identical answer is safe; changing an answered row is rejected.
- SavedQuestion is unique per user/master, with note, timestamps, review count and mastery.
- Save/unsave are authenticated CSRF-protected POSTs with minimal JSON support.
- Bookmark permission can include owned frozen history; readable bank content is stricter.
- My Revision Bank lives under My account and in account-section navigation.
- Bank filters cover exam/hierarchy/mastery/sorting; unavailable rows show placeholders.
- Mark-reviewed is explicit; simply reading a page does not increment review_count.
- RevisionSession proxies PracticeSession with kind=revision, not another table/engine.
- Practice kind requires Exam/Subject; revision kind has null Exam/Subject/Topic.
- Revision supports all eligible bookmarks or filters plus an optional question limit.
- start_revision serializes/rechecks selection and reuses shared snapshot assembly.
- First-answer submission invokes record_review in the same transaction for revision kind.
- Refresh/retry/resume do not recount; the hook does not recreate removed bookmarks.
- Mastery is explicit and independent of correctness; completed results remain historical.
- Pause is navigation away; resume chooses the next unanswered row or explicit question link.
- Revision supports early completion with unanswered rows retained and incorrect-only results.

## Topic exploration and presentation boundaries

- Registered users can reach question-topic and related-scope routes under `/revision/`.
- Stored paths support skipped levels and primary/secondary topic associations.
- Scopes expand through Topic/Chapter/Module/Part/Subject; Subject includes unclassified rows.
- Discovery excludes the source master and filters by active Exam and published difficulty.
- Related pages paginate 20 rows and batch translations/tags/bookmark state.
- Revision eligibility withholds questions in the user's open mock attempts.
- Exploration also blocks a requested scope containing an owner's open-mock question.
- Brief user-row locks coordinate exploration rendering with Mock Test starts.
- Exploration uses live approved content; existing session snapshots remain frozen.
- Per-question Explore Topic controls were removed; routes/helpers remain implemented.
- Bookmarks use compact checkbox-style toggles; success prompts are commented out.
- Active Mock bookmark actions stay separate from review flags and autosave semantics.

## Integrity, known drift and verification limits

- Constraints, guarded model saves and row locks provide complementary integrity layers.
- Deferred primary-tag triggers require coherent pointer/tag state at transaction commit.
- Some reverse migrations intentionally reject data incompatible with older schemas.
- Attempts, Practice history and content snapshots have protected mutation/deletion paths.
- Historical decisions and mobile proposals are explicitly labeled; current guides consolidate earlier milestone wording.
- Legacy Practice forms/filter assets coexist with module/difficulty setup; verify consumers.
- No AI/external-learning integration or general mobile token API is configured.
- This reference is statically verified against source, URL mappings and migration operations.
- Runtime data, installed PostgreSQL version, deployment topology and job schedules are unverified.
- No tests, database commands, CSS builds or deployment checks were run for this documentation task.
