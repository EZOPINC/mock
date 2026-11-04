# Import contract

Authority: approved Phase 0 **Database & Import Specification v1.0**, including its reviewed Questions.xlsx mapping. The workbook itself was not supplied for this milestone; the source reports one worksheet, 100 data rows, 22 named columns, and an unnamed trailing column. The list below expands grouped headers from that source; it does not assert a verified physical column order.

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
| 18 | `verification_notes` | Recognized `pending_review`/`reviewed` values map to Question.review_status |
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

The approved review does not define header/order normalization, multi-value delimiters, alias catalogue, maximum file/row sizes, exact required-cell/blank-option rules, unknown verification_notes handling, source_name derivation, source-ID ingestion, date parsing, paper order derivation, or metadata size limits/storage schema. The workbook is needed to independently verify physical header order and sample values. These gaps must be settled before implementing their respective parser/confirmation behavior; no new rules are assumed here.
