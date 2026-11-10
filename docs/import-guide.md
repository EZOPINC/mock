# Unified administrative question import (Milestone 2.3B)

Phase D5 resolves normalized taxonomy codes and multiple topic tags through the
same preview and transactional import pipeline. Missing taxonomy is never created
automatically. Existing Question IDs, revisions, paper associations and attempts
are not modified. See [multi-topic tagging](multi-topic-questions.md).

## Name-based hierarchy columns

`part`, `module` and `chapter` are optional case-insensitive names, scoped to
Subject and the supplied ancestor path. They can be combined with stable codes,
but names and codes must agree. Unknown/ambiguous values require correction;
missing taxonomy records are never created automatically.

`source_question_number` is optional source metadata when `question_number` is
present. If the `question_number` header is absent, it supplies the required local
question number instead (including original text such as leading zeros).

## Taxonomy columns (Phase D5)

Optional CSV/XLSX columns: `subject_code`, `part_code`, `module_code`,
`chapter_code`, `topic_code`, `additional_topic_codes`.

- Codes are exact, case-sensitive stable codes from existing taxonomy records;
  surrounding whitespace is ignored. Names continue to match case-insensitively.
- Supply any available levels. All supplied primary-path codes must be actual
  ancestors of the deepest supplied node; Subject must agree throughout.
  Intermediate levels may be skipped according to the stored hierarchy.
- A topic code can infer Subject when no explicit Subject is supplied. An explicit
  name/mapping and code must agree. Parent codes can disambiguate identical topic
  names in different branches. Row values take precedence over batch defaults.
- `topic_code` selects the primary topic. Existing name/default topic mapping also
  remains supported. `additional_topic_codes` accepts semicolon, comma or pipe
  delimiters. Secondary topics may be in other branches of the same Subject.
  Repeated codes are deduplicated, including repeats of the primary code.
- Secondary tags require a primary topic. Questions may have no topics. Parent
  codes without a topic validate context only; they do not create a new question
  classification field. Preview warns about this.
- Preview shows full resolved paths and editable code columns, including for old
  uploads. Correct unknown codes, ambiguous names, ancestry and Subject errors
  before confirmation. Use explicit Add subject/topic controls (with permissions)
  or Admin to create missing records; neither prefix matching nor automatic
  creation is performed by validation/confirmation.
- Bilingual pairing requires identical primary and secondary topic assignments;
  corrections invalidate the prior pairing approval. Tags are stored once per
  master via the D3 service, with the legacy `Question.topic` kept synchronized.
- Duplicate-text warnings never merge or update an existing Question. A separate
  draft is created; existing topic tags and exam/year associations remain intact.
  Repeated confirmation remains idempotent. All rows/tags roll back on failure.
- Resolution loads each taxonomy table once per validation, with no per-row
  taxonomy queries. Confirmation locks taxonomy while validating and importing.

CSV and XLSX examples are in [samples/questions-taxonomy.csv](samples/questions-taxonomy.csv)
and [samples/questions-taxonomy.xlsx](samples/questions-taxonomy.xlsx). Replace the
symbolic codes with existing Admin codes before uploading. Both contain the same
English/Bengali pair; approve pairing in preview. Choose Exam/Year in the form for
Previous Year, or one or more Exams for General Question Bank. Legacy files need
none of these additional columns.

## Multilingual enhancement (Milestone 2.3C)

English-only, Bengali-only and bilingual imports now share one master identity
with revision-bound QuestionTranslation rows. For bilingual rows, use the same
question_number within the same selected paper/import context, one row per
language. Inspect and explicitly approve each proposed pairing in preview, then
save/revalidate. Shared answer, difficulty, subject, topic and exams must agree;
same-language duplicates and conflicting pairs remain errors. Every original row
is audited, but one master and (in Previous Year mode) one paper row are created.
This supersedes the unconditional duplicate-number rule below for explicitly
approved translation pairs only. Existing paper number conflicts still block.
See [multilingual design and workflow](multilingual-questions.md).

The latest unified import requirements supersede the earlier single-paper-only
contract. Start at `/admin/question-import/` or Question Bank Admin's **Import
CSV/XLSX** link. One interface shares parsing, preview, correction, validation,
staging and transactional confirmation. No questions are reviewed or published
by importing.

## Choose a mandatory Import Type

- **Previous Year Questions:** select exactly one Exam and a mandatory Year;
  Stage is optional. Optionally select an existing unpublished paper matching
  Exam/Year/Stage. Otherwise a matching draft identity is reused or a new paper
  created, with default name **Previous Year Paper** unless supplied. Optional
  Part/Session distinguish identities. Every row receives QuestionExam and
  PaperQuestion associations. Form-selected Exam/Paper is authoritative;
  exam_categories/previous_year_tags are source metadata, not repeated required
  input. Paper display order follows file order after existing rows.
- **General Question Bank:** select at least one Exam. Year/Stage/Paper fields
  are not applicable and ignored. Choose **selected exams for every row**, or
  explicitly choose **row exam_categories**, with selected exams as fallback for
  blank categories. Row mappings resolve against all existing Exams by exact
  normalized name, code, `Authority name / Exam name`, or `Authority code / Exam
  code`. Separate multiple labels with `;` or `|`. Unknown or ambiguous labels
  block confirmation; correct them in preview. No paper or paper rows are created.
  question_number is a batch-local reference, not a global Question ID.

General mode needs active staff and the add permissions in
`imports/permissions.py` for imports/Question Bank/source creation. Previous Year
also requires add_previousyearpaper and add_paperquestion. Superusers qualify.
Permissions and ownership are checked again on confirmation.

## Required content and supported headers

Required: `question_number`, `question_text`, `option_a`, `option_b`, `option_c`,
`option_d`.

Optional: `correct_answer`, `explanation`, `subject`, `topic`, `language`,
`exam_categories`, `previous_year_tags`, `source_document`, `source_page`,
`difficulty_level`, `review_status`, `verification_notes`, `comments`,
`created_date`, `updated_date`, `updated_by`, plus the taxonomy code/name columns above.

Headers ignore case/surrounding whitespace. Duplicate/unknown named headers are
rejected; completely empty unnamed trailing columns are ignored. UTF-8 CSV and
XLSX also accept `review_flag` as a legacy alias for source `review_status` metadata;
its original header mapping is recorded in the batch audit. Include only one of
these headers. Neither header approves or publishes questions. UTF-8 CSV and
plain-value XLSX preserve Bengali Unicode and multiline content. Choose the exact
worksheet name when a workbook has multiple sheets. Formulas, errors, macros and
external-link workbooks are rejected. Store
question numbers as text if leading zeros matter.

## Wide bilingual PDF-extraction files

CSV/XLSX may instead provide `question_text_en`, `option_a_en` through
`option_d_en`, and the corresponding `_bn` columns. Optional `explanation_en`
and `explanation_bn` preserve language-specific solutions. Headers must include
`question_number` and either the five generic content headers or a complete
five-column language block. Only available languages are stored.

Each physical wide row represents one master question with its available
translations; `language=en,bn` is supported. Unlike separate long-format rows,
explicit language blocks need no additional pairing checkbox. Generic content,
when also supplied, must match an available version. Partial translation blocks
or conflicting generic content block confirmation; correct them in preview.
A wholly absent language is not synthesized. Long-format imports remain supported.

`handwritten_mark_unverified` and `needs_review` are supported source metadata,
shown as preview warnings and retained in original/corrected audit values.
They never supply an answer or change editorial state. **A verified A/B/C/D
correct_answer remains mandatory before import**, including when a handwritten
mark exists. Preview exposes language columns and these metadata fields for
correction; wider files use smaller pages to remain within form-field limits.

The supplied `wbp_si_2019_questions.csv` has 100 rows with English/Bengali blocks
and 100 blank answer keys. Supply verified answers in the file or preview, select
Previous Year mode with the existing Exam and Year 2019, and resolve remaining
validation errors before confirming. Import remains atomic and draft by default.
Source question numbers and file order become paper numbering and ordering;
similar text never causes an automatic identity merge.

## Resolution, preview and confirmation

1. Upload and choose mode-specific selections. Optional Subject, Topic, and
   Language defaults apply only to missing row values; row values take precedence.
   If neither the row nor batch specifies language, Unicode-script detection of
   question/options text infers `bn` when Bengali letters occur, otherwise `en`
   for Latin-script text (Greek mathematical letters are tolerated). Inference is
   shown as a preview warning; explicit row language, then batch language, take
   precedence. Numbers/symbols alone or unsupported scripts require correction.
   UTF-8 itself does not identify a language. Blank subjects use an explicit
   mapping, a code-inferred Subject or the batch default. An existing, uniquely
   named `UnIdentified` subject is supported as a legacy fallback, but the importer
   never creates it. If none resolves, select an existing Subject before import.
   Subject and Topic names match case-insensitively. Unknown/ambiguous names need
   explicit mapping; taxonomy codes and ancestry are validated as described above.
2. Review all preview pages (up to 25 rows/page; fewer for wide files), including resolved Subject/Topic,
   Language, Answer, Exams and Paper. Search/status filters cover the entire file;
   clear filters to edit. Map unknown or missing subject labels to existing
   records, or edit row names. Topics must belong to the resolved Subject.
3. **Save page & Revalidate** before paging or confirming. Language not resolved
   by an explicit value or inference must be corrected. Blank correct_answer is
   parseable but blocks confirmation: existing QuestionRevision requires A/B/C/D.
   Database integrity is retained; no incomplete Question Bank rows are inserted.

   Missing taxonomy can also be added directly in preview using **Add subject**
   or **Add topic**. Save row edits first. Subjects require name, unique code and
   slug; topics require an existing subject, name and a slug unique within that
   subject. These explicit POST actions create taxonomy immediately and refresh
   validation; they do not import questions. The corresponding Django Add subject
   or Add topic permission is required, in addition to import permissions.
   Duplicate names ignoring case are rejected. Use the exact source name for
   automatic resolution, or select the new record in the mapping controls.
4. Confirm only after all blocking errors are resolved. Entire-batch server
   revalidation and `transaction.atomic()` create Questions/initial revisions,
   exam associations, optional source references, mode-specific paper associations,
   and audit rows together. Any failure rolls back everything, including new papers.
5. Follow completion links to review then explicitly publish questions with the
   existing Question Bank actions. In Previous Year mode, preview and publish the
   paper last. General publication creates no student-facing paper/test engine.

Original and corrected values remain in row audit JSON alongside resolved IDs,
language, answer and associations. Source review_status/verification_notes never
approve content; source dates never replace system timestamps, and updated_by
is not a User FK. Unsupported feature values are metadata only. source_document
and source_page also create source references; source_name defaults to the
bounded document label. No source_question_id/global/source-scoped identity is
introduced. Question text/options/explanations remain unaltered; answer/language
case and surrounding whitespace are normalized.

## Duplicate scope and staging

- Numbers must be unique within every uploaded batch. Previous Year additionally
  rejects conflicts with existing PaperQuestion numbers. Existing imported paper
  rows require explicit append acknowledgment, which never overrides conflicts.
- Completed-file duplicate protection uses **file hash + canonical import
  context**: mode, sorted selected Exam IDs, explicit exam-mapping strategy and,
  for Previous Year, normalized paper identity (Exam/Stage/Year/Name/Part/Session).
  Context excludes corrections, aliases, uploader, and taxonomy/language defaults
  so changing them cannot evade the same-context guard. Different modes, exam
  contexts or papers may intentionally reuse a file. Similar text is warning-only;
  questions are never merged automatically. Staging UUID remains unique globally.
- Private JSON staging is outside static/media/sessions, uploader-owned, limited
  to two hours, and removed on cancel/completion. Expired data is cleaned during
  uploads and with `python manage.py cleanup_import_staging`; run the command
  periodically when there are no new uploads. Version digests/filesystem locks
  reject stale edits; ordered exam/paper locks and database uniqueness protect
  concurrent confirmation.
- Limits remain 5 MB upload, 2000 rows, 64 spreadsheet columns, 32,000 characters
  per cell, 128 KB each original/corrected row, 20 MB staging. XLSX archives are
  bounded to 1000 entries/30 MB expanded. Numeric source pages must be positive;
  printable Roman/range labels are supported within 50 characters.

## General Questions module and whole-batch publication

Open **General Questions** in the header or homepage to browse published General
import collections at `/general-questions/`. Guests can filter by Exam, Subject,
Topic, and Language, then read paginated approved questions and solutions. Draft
collections/questions and inactive-exam questions are hidden; filenames, uploaders
and source audit metadata are not public. New working drafts never replace the
approved live content automatically.

Staff can choose **Manage imports & batch publication** at
`/general-questions/manage/`. This requires View import batch and Change question
permissions. Each completed General import has an inspection page at
`/general-questions/manage/<batch_id>/` with two explicit actions:

1. Inspect the working revisions across all pages, then **Mark all questions
   reviewed**. This reviews the entire batch without selecting individual records.
2. **Publish all reviewed questions**. Every working revision must pass the
   existing publication service. A failure rolls back the whole batch action.

The existing CSV/XLSX importer is linked from this module, and its completion
page links directly to the batch controls. The dedicated `general_question` Django app owns this module; its batch proxy
reuses the existing import table. No duplicate importer or question storage is introduced. POST/CSRF, signed expiring revision snapshots,
permission checks and ordered row locks protect actions. Reload and inspect again
if the batch changes; no automatic review/publication occurs during import.

## Schema and compatibility (import audit)

`imports.0002_unified_import` makes ImportBatch.paper nullable, adds
context_sha256, backfills existing batches using their actual historical paper,
and replaces global file-hash uniqueness with (file_sha256, context_sha256).
Existing batches and paper links remain intact. Question/revision/paper models,
immutability, strict manual paper associations and publication rules are unchanged.
The narrow internal draft-paper association path is still used only by Previous
Year imports. No source-scoped identity redesign or new parser dependency.

The actual Questions.xlsx file has not been attached in this session; its data
and the complete browser flow remain for manual owner review.


### Dedicated Django Admin entry

Open **Admin > General Questions > General question batches**. All completed
General Question Bank uploads appear automatically, with reviewed and live-content
counts. Select batch checkboxes and use **Mark all questions in selected batches
as reviewed**, then **Publish all reviewed questions in selected batches**, clicking
Go after each action. Each batch transition is atomic; errors are displayed per
batch and no unreviewed revisions are published. Alternatively click a batch to
inspect it, then use **Mark all questions reviewed** and
**Publish all reviewed questions** as separate actions. Existing View import batch
and Change question permissions still authorize management; direct add/delete or
editing of audit batches is disabled. The proxy model's migration creates no new
question table. Students continue using `/general-questions/`.
