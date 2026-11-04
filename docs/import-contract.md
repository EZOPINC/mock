# Import contract

## Wide extraction format extension (2026-11-04)

The current importer also accepts explicit `question_text_en`, `option_a_en`
through `option_d_en`, their `_bn` equivalents and optional per-language
`explanation_en` / `explanation_bn`. A wide source row maps to one master with
only available translations; `language=en,bn` is allowed. Generic content must
agree with an available version; incomplete/conflicting blocks require correction.
Separate long rows retain explicit pairing approval and shared-attribute checks.
`handwritten_mark_unverified` and `needs_review` are audit metadata and preview
warnings only. Verified A/B/C/D answers remain mandatory before confirmation;
no mark becomes an answer automatically. No schema or publication policy changes.
See [import guide](import-guide.md) for header requirements and the reviewed
100-row WBP SI 2019 extraction example.


## Milestone 2.3C override

QuestionTranslation now stores the available per-language text/options/explanation
under a shared Question and immutable revision. The primary-language legacy
QuestionRevision fields remain for compatibility. Difficulty is optional bounded
shared Question/revision text as well as preserved source audit metadata. Repeated
question numbers with distinct languages in one selected paper/import may become
one master only after explicit preview pairing approval and matching shared
attributes; no automatic legacy/cross-paper merge. Same-language duplicates and
existing paper number conflicts remain errors. See [multilingual design](multilingual-questions.md).

Authority: approved Phase 0 **Database & Import Specification v1.0**, including its reviewed Questions.xlsx mapping. The workbook itself was not supplied for this milestone; the source reports one worksheet, 100 data rows, 22 named columns, and an unnamed trailing column. The list below expands grouped headers from that source; it does not assert a verified physical column order.

## Active contract: Milestone 2.3B

Language clarification: when row and batch language are both absent, the importer
infers en/bn from question/options Unicode scripts, displays a preview warning,
and records the result in audit. Ambiguous or unsupported text still needs an
explicit supported language. See the current import guide for precedence.

The latest unified-import request supersedes earlier single-paper and duplicate
scope rules below. Only question_number, question_text, and option_a/b/c/d headers
are required; all other supported headers are optional. Missing subject/language/
answer may be corrected in preview, but confirmation still requires a resolved
Subject, en/bn and A/B/C/D. Row Subject/Topic override explicitly selected batch
defaults. No answer/language/classification is invented.

Previous Year mode uses one selected Exam, required Year and optional Stage,
creating/reusing a draft paper with default name Previous Year Paper. Its source
exam_categories and previous_year_tags are metadata only. General mode requires
multiple-capable Exam selection, has no paper/year/stage, and explicitly chooses
selected exams or row categories with selected fallback. Row categories resolve
unambiguously against existing Exams. Numbers are batch-local in General mode;
Previous Year also checks existing paper numbers. File duplicates are scoped to
canonical import context, not globally. See [current import guide](import-guide.md)
and D21 in [decisions](decisions.md) for the authoritative operational rules. The
Phase 0 workflow/gap sections retained below are historical context when they
conflict with this section.

## Canonical 22 named columns

| # | Header | Model mapping / handling |
|---|---|---|
| 1 | `question_number` | PaperQuestion.question_number; paper-local string, never a global Question ID |
| 2 | `question_text` | QuestionRevision.question_text |
| 3 | `option_a` | QuestionRevision.option_a |
| 4 | `option_b` | QuestionRevision.option_b |
| 5 | `option_c` | QuestionRevision.option_c |
| 6 | `option_d` | QuestionRevision.option_d |
| 7 | `correct_answer` | QuestionRevision.correct_answer |
| 8 | `explanation` | QuestionRevision.explanation, optional; preserve Unicode |
| 9 | `difficulty_level` | Import metadata only; no difficulty functionality |
| 10 | `subject` | Resolve Subject; assign Question.subject |
| 11 | `topic` | Resolve optional Topic; assign Question.topic |
| 12 | `exam_categories` | Explicitly resolve exams; create QuestionExam associations |
| 13 | `previous_year_tags` | Explicitly resolve PreviousYearPaper metadata and PaperQuestion association |
| 14 | `language` | QuestionRevision.language (`en`/`bn`) |
| 15 | `source_document` | QuestionSource.source_document / source association |
| 16 | `review_status` | Preserve as source metadata; numeric values are not review states |
| 17 | `source_page` | QuestionSourceReference.source_page |
| 18 | `verification_notes` | Source review metadata only; Milestone 2.3 supersedes the earlier status mapping; never auto-approves |
| 19 | `comments` | Import review metadata |
| 20 | `created_date` | Source metadata, never the system created_at timestamp |
| 21 | `updated_date` | Source metadata, never the system updated_at timestamp |
| 22 | `updated_by` | Source metadata, never a Django User FK |

Ignore the unnamed trailing column only when empty. Metadata without a dedicated relational field may be retained in a bounded JSONField on an import audit record linked to the imported row. Phase 0 allows this storage approach but does not name the field, bound, or precise owning model. Preserve metadata without inventing new domain functionality.

## Validation and association rules

- Validate file type/size, headers, rows, language, four options, answer keys, subjects, exams, and paper metadata. Allowed languages are `en` and `bn`; allowed answers are `A`, `B`, `C`, `D`. English and Bengali are independent Questions. Preserve original Unicode text and explanations; a Question's language cannot change across revisions.
- Resolve taxonomy with explicit admin-confirmed mappings. Reject unresolved or ambiguous references. Topic is optional but must belong to the selected Subject. Do not silently create or guess taxonomy.
- A Question can belong to multiple exams. `PSC Clerkship` maps to WBPSC / Clerkship only with explicit admin confirmation of that alias.
- `Prelims 2023 (Part-I, Session I)` requires explicit resolution of exam, optional stage, year, paper identity, part, and session. Stage must belong to the exam. Paper identity is unique across exam/stage/year/paper_name/part/session, including nullable fields.
- Preserve historical paper numbering and order. PaperQuestion references a specific QuestionRevision; question_number is not a source/global ID. Paper display_order must be unique within its paper. A question can appear in multiple papers.
- Keep source_document, source_page, and other source metadata. QuestionSourceReference also supports source_question_number; the approved mapping does not say to derive it from question_number. There is no source_question_id column among these 22 headers.

## Preview and transactional confirmation

1. An authorized admin uploads CSV/XLSX.
2. Validate the complete file and resolve explicit mappings.
3. Detect duplicate source IDs, duplicate rows, and possible content duplicates; show row-level errors and preview.
4. Revalidate on confirmation, including references and duplicates.
5. Save the entire valid batch using `transaction.atomic()`: Questions and QuestionRevisions, exam/source associations, draft historical-paper associations, and batch/row audit records. **Any invalid row rejects the entire batch; never partially import.**
6. Admin reviews and explicitly publishes questions and papers. Imports default to draft; review metadata cannot silently publish content. Public papers must reference revisions approved for publication.

ImportBatch tracks uploader, filename, file_sha256, mapping_version, status, row/error counts, and creation/confirmation timestamps. ImportedQuestion links batch, source_row_number, Question, and action. Import is auditable and idempotent. The source does not specify how failed previews are persisted relative to the confirmation transaction.

## Duplicate prevention

Use file hashes and source-scoped identifiers to prevent accidental repeat imports. External IDs are unique within their defined source scope, not globally. Detect repeated rows and possible duplicate content; do not silently merge similar questions. The exact source scope, content fingerprint rules, repeated-file behavior, and row action semantics require approval before implementation.

## Missing contract details

Milestone 2.3 resolves the first-release behavior in [import guide](import-guide.md) and D20 in [decisions](decisions.md). Selected Exam/Paper is authoritative, source-scoped identity remains deferred, and verification_notes never changes editorial review state. The original Phase 0 gap list below is historical context; operational rules now specified in the guide take precedence.

The approved review does not define header/order normalization, multi-value delimiters, alias catalogue, maximum file/row sizes, exact required-cell/blank-option rules, unknown verification_notes handling, source_name derivation, source-ID ingestion, date parsing, paper order derivation, or metadata size limits/storage schema. The workbook is needed to independently verify physical header order and sample values. These gaps must be settled before implementing their respective parser/confirmation behavior; no new rules are assumed here.
