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

Taxonomy columns include optional `submodule_code` and `submodule` (display name)
between Module and Chapter. `topic_code` resolves the full path through a
Sub-module when present. Parent columns on question rows describe/validate the
ancestry; they do not require redundant parent foreign keys on a Chapter. The
CSV/XLSX taxonomy samples include these optional columns; older files remain valid.

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
| correct_answer, difficulty_level | Shared versioned answer and difficulty. Use Easy, Medium or Hard (case-insensitive). Blank, missing or Any stores unrated difficulty. |
| question_kind | Optional master classification used by mock selection. Use Logical, Static or Unclassified (case-insensitive). Blank or missing defaults to Unclassified. Paired language rows must agree on any supplied values. |
| current_as_of, expires_on | Optional YYYY-MM-DD dates for subjects with an expiry policy. Without an explicit expiry, use the current-as-of date or first successful import date plus the configured calendar years. Expiry is the first ineligible date for new mocks and practice. Paired language rows must agree on supplied dates. Other subjects ignore these columns with a warning. |
| language | Configured language; normalization/inference rules live in imports/language.py |
| subject, topic | Existing Subject resolution and optional primary Topic name/mapping |
| part, module, submodule, chapter | Named hierarchy scoped to resolved Subject/ancestors; sub_module aliases submodule |
| subject_code, part_code, module_code, submodule_code, chapter_code, topic_code | Stable taxonomy codes; conflicts/invalid ancestry block confirmation; sub_module_code aliases submodule_code |
| additional_topic_codes | Secondary topics, separated by semicolon/comma/pipe; deduplicated within the same Subject |
| exam_categories | Existing-exam resolution only when row mapping is selected; otherwise preserved metadata |
| previous_year_tags | Audit metadata; never overrides the form-selected paper |
| source_code | Optional private source identifier. Codes are normalized to uppercase. A new code needs a document on at least one row. Existing codes can be reused with locators alone. |
| source_document, source_publisher | Document and optional publisher shared by rows with the same code. Conflicting values block confirmation. Without a code, the document follows the legacy reference path and the publisher remains import metadata. |
| source_page, source_question_number | Optional page and original question number stored on the question's source reference. The original question number can also supply a missing question_number header. |
| review_status, verification_notes, comments | Source audit metadata, not editorial approval |
| created_date, updated_date, updated_by | Source metadata, never replacements for system timestamps/User identity |
| handwritten_mark_unverified, needs_review, source_row | Extraction/audit metadata; not an answer or publication signal |

The original 22-column format remains a supported subset, not an exhaustive current schema.
HEADER_ALIASES in imports/parsing.py defines accepted alternate names, including review_flag,
review_notes, source_doc, source_pg and source_row_id. Keep only one header per canonical key.

The upload page now contains an expandable complete field reference. The simplest
recommended single-language CSV header is:

```csv
question_number,question_text,option_a,option_b,option_c,option_d,correct_answer,topic_code,language
```

`correct_answer` is technically an optional upload header so a missing answer can
be corrected in preview, but a verified A/B/C/D value is mandatory to confirm.
Question content and options cannot be blank. Subject must resolve from a row
name/code, the Topic/ancestor codes, an explicit mapping, the form default, or an
existing unique Unidentified fallback; it is never silently created. Language
must resolve from row/form/inference. Taxonomy tagging is optional for legacy
imports, but existing `topic_code` is recommended for reliable classification.
The Topic's whole stored ancestry is resolved automatically; ancestor columns
need not be repeated. If supplied they must agree with the current path, including
the corrected West Bengal Part. Row identifiers are not database Question IDs.

Wide bilingual rows instead need question_number (or its source-number header
fallback), shared correct_answer, and at least one complete language block:
question_text_en, option_a_en, option_b_en, option_c_en, option_d_en and/or the
equivalent `_bn` fields. Explanation suffix fields are optional. Generic content
columns may be omitted when complete language headers are present. Both language
editions inherit the one master Question's primary and secondary tags.

Form fields are separate from CSV requirements: choose General or Previous Year;
General requires selected Exams and a mapping strategy; Previous Year requires
one Exam and Year, with optional Stage/draft Paper/name/Part/Session. CSV `part`
means taxonomy Part; form Part means the paper identity component. Worksheet
selection is needed by name for a workbook containing multiple sheets.

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
- Missing named Parts/Modules/Submodules/Chapters/Topics can be proposed under that Subject in preview.
- Confirmation creates proposed nodes atomically; preview resolution itself writes no domain rows.
- A new code needs its corresponding name; omitted child codes can be generated.
- Existing code/name conflicts and inconsistent ancestry are rejected, not silently rewritten.
- Taxonomy codes ignore case and outer whitespace, matching normalized database
  uniqueness; stored codes/names are not rewritten. Header aliases are normalized
  before duplicate detection, so both submodule_code and sub_module_code cannot
  appear together. Unknown headers remain errors.
- New named Submodules require a resolved Module parent in preview. A new Topic
  beneath a Submodule requires a Chapter; the importer does not invent unsupported
  direct Submodule/Topic foreign keys. A Submodule alone is valid ancestor context
  and gives a path/warning without silently attaching a Topic tag.
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
imports.test_wide_format, imports.test_taxonomy_import and imports.test_taxonomy_integrity. These are test entry points,
not a claim that a historical test count validates today's checkout.
