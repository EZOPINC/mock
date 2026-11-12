# Import Contract - Current Implementation

Source-verified on 2026-11-12. This replaces overlapping Phase 0/2.3 override text.
The parser/normalizer/validator are authoritative. Use [import guide](import-guide.md)
for the staff workflow and [MODULE_MAP](MODULE_MAP.md) for implementation navigation.

## Modes and ownership

| Mode | Selection and result |
|---|---|
| Previous Year | Exactly one existing Exam; select/create an unpublished paper within the chosen context; append draft question associations |
| General | One or more existing Exams; no paper; draft questions and General ImportBatch audit |

An active staff importer needs imports/Question Bank permissions and the paper-create
permissions for Previous Year mode. Staging is uploader-owned; confirmation rechecks
ownership/permissions server-side. Inline Add subject/topic is a separate privileged
POST action, not implicit permission for row-driven Subject creation.

## File and content bounds

- UTF-8 CSV or selected XLSX worksheet; plain data only, not executable formulas/macros.
- Defaults: 5 MB upload, 2,000 rows, 64 columns and 32,000 characters per cell.
- XLSX expanded/archive limits and bounded row/staging JSON also apply.
- Required long-form headers are question_number, question_text and option_a through option_d.
- source_question_number can supply a missing question_number header.
- Confirmation requires a valid A/B/C/D answer and complete eligible language content.
- A blank answer can reach preview but blocks confirmation; handwriting is never inferred as truth.
- Empty unnamed trailing cells are allowed; duplicate/unknown headers or extra populated cells fail.
- Preserve Unicode text and source numbering; do not use printed numbers as global master IDs.

## Supported field groups

| Fields | Interpretation |
|---|---|
| question_number | Local grouping/paper number; string identity within the selected import context |
| question_text, option_a, option_b, option_c, option_d, explanation | Primary content/optional explanation in the revision snapshot |
| correct_answer, difficulty_level | Shared versioned answer/difficulty; difficulty is used by existing selection/filter flows |
| language | Configured language; normalization/inference rules live in imports/language.py |
| subject, topic | Existing Subject resolution and optional primary Topic name/mapping |
| part, module, chapter | Named hierarchy scoped to resolved Subject/ancestors |
| subject_code, part_code, module_code, chapter_code, topic_code | Stable taxonomy codes; conflicts/invalid ancestry block confirmation |
| additional_topic_codes | Secondary topics, separated by semicolon/comma/pipe; deduplicated within the same Subject |
| exam_categories | Existing-exam resolution only when row mapping is selected; otherwise preserved metadata |
| previous_year_tags | Audit metadata; never overrides the form-selected paper |
| source_document, source_page | Optional source references; page labels are bounded/validated |
| source_question_number | Original numbering metadata when question_number is also present |
| review_status, verification_notes, comments | Source audit metadata, not editorial approval |
| created_date, updated_date, updated_by | Source metadata, never replacements for system timestamps/User identity |
| handwritten_mark_unverified, needs_review, source_row | Extraction/audit metadata; not an answer or publication signal |

The original 22-column format remains a supported subset, not an exhaustive current schema.
HEADER_ALIASES in imports/parsing.py defines accepted alternate names, including review_flag,
review_notes, source_doc, source_pg and source_row_id. Keep only one header per canonical key.

## Multilingual normalization and pairing

English/Bengali versions belong to one master through immutable QuestionTranslation
rows in a revision. They are not independent masters merely because languages differ.
Primary revision fields remain for compatibility; the primary language stays fixed across revisions.

Long-form rows with the same local number can pair only when languages are distinct,
shared answer/difficulty/Subject/topic sets/exams agree, and the importer explicitly
confirms the current group signature. Corrections invalidate stale pairing approvals.
Same-language duplicates and ambiguous matches block import; there is no cross-paper merge.

Wide format uses complete question_text/option_a/option_b/option_c/option_d blocks
with _en and/or _bn suffixes, plus optional explanation suffixes. It already represents
one master per row and uses the same normalized translation/answer workflow.
Partial blocks fail. Extraction marks remain metadata even when the correct answer is blank.

## Taxonomy and association resolution

- Row values/codes take precedence over batch defaults; mappings resolve ambiguity explicitly.
- Subject must already exist. Only an existing uniquely resolved fallback/default may be reused.
- Missing named Parts/Modules/Chapters/Topics can be proposed under that Subject in preview.
- Confirmation creates proposed nodes atomically; preview resolution itself writes no domain rows.
- A new code needs its corresponding name; omitted child codes can be generated.
- Existing code/name conflicts and inconsistent ancestry are rejected, not silently rewritten.
- Skipped levels are valid. The selected primary Topic and secondary tags must share Subject.
- Secondary tags require an explicit primary Topic.
- Parent-only metadata is context; without a primary Topic it creates no new question classification field.
- Exam values must resolve existing records under the selected mapping strategy; no Exam is auto-created.
- Previous-Year associations target the selected unpublished paper and require append acknowledgment when applicable.

## Confirmation, audit and duplicates

confirm_import revalidates in an atomic transaction under exam/paper/taxonomy locks.
It creates pending-review masters/revisions/translations, associations, optional sources,
ImportBatch and ImportedQuestion. Any blocking error rolls back the entire operation.
Questions and papers are reviewed/published explicitly afterward.

ImportBatch stores mapping/selection metadata. ImportedQuestion.source_metadata retains
bounded original, corrected and resolved row data; this storage is already implemented.

Duplicate protection is file_sha256 plus canonical context_sha256, with a separately
unique staging UUID. Context includes mode, selected exams/mapping strategy and normalized
paper identity when applicable. Changing an alias/correction/uploader does not define a
new question identity. Similar content warns; it never silently merges existing masters.
source_question_id is not globally unique and no automatic source-identity merge key exists.

## Verification references

Targeted tests: imports.tests, imports.test_unified, imports.test_multilingual,
imports.test_wide_format and imports.test_taxonomy_import. These are test entry points,
not a claim that a historical test count validates today's checkout.
