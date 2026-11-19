# Administrative Question Import Guide

Current workflow reference, 2026-11-12. Field semantics, formats and limits are centralized
in [import-contract.md](import-contract.md); source remains authoritative.

## Before uploading

- Sign in as active staff with the import/Question Bank permissions required by the selected mode.
- Add missing Subjects and Exams through their existing administrative interfaces.
- Select Previous Year or General explicitly; General does not create a paper.
- Previous Year uses the selected exam, year, and paper details to match an existing draft or configure a new one.
- General selects one or more Exams; choose selected-exam or row exam_categories mapping.
- Choose the XLSX worksheet when necessary; use UTF-8 CSV otherwise.
- Replace formulas/errors/macros/external links with plain data; no PDF/OCR/AI processing runs here.

## Prepare the rows

Use imports/parsing.py for the exact supported headers/aliases. The original 22-column
layout is still accepted, but optional taxonomy, multilingual and extraction fields extend it.

| Input concern | Current rule |
|---|---|
| Number | Keep question_number as a local string; source_question_number can supply a missing number header |
| Content | Complete question text and A-D options for each included language; explanation is optional |
| Answer | A/B/C/D required for confirmation; handwritten marks never supply a verified answer |
| Difficulty | Stored in versioned shared content and used by existing filters/selection |
| Language | Explicit configured language or supported inference; unresolved values must be corrected |
| Subject | Must resolve an existing Subject by row/default/code/mapping |
| Hierarchy | Existing codes/names must agree; missing named children can be proposed beneath the existing Subject |
| Topics | Optional primary Topic plus same-Subject secondary codes; primary required for secondary tags |
| Exams | Form selection is authoritative unless row mapping is explicitly chosen |
| Paper/source metadata | previous_year_tags never changes the selected paper; source fields and editorial metadata remain auditable |

Long-form translations share a local number. Wide format uses complete _en/_bn content
blocks. See the contract for grouping/aliases; both formats produce the same master/revision
model. Do not duplicate bilingual masters merely to create separate language rows.

Sample files: [CSV](samples/questions-taxonomy.csv) and [XLSX](samples/questions-taxonomy.xlsx).
Use an existing Subject code; supply a name for each new child code. These are examples,
not a promise that their symbolic codes already exist in your database.

## Upload, correct and confirm

1. Upload through /admin/question-import/. Private staging belongs to that uploader and expires.
2. Inspect source values, resolved exam/taxonomy paths, errors, warnings and proposed translations.
3. Correct editable rows/mappings and Save page & Revalidate before paging or confirming.
4. Resolve ambiguous code/name/path conflicts. Preview resolution itself does not create taxonomy.
5. Approve each proposed long-form translation pairing after checking every language version.
   Duplicate language or conflicting shared attributes cannot be silently paired.
6. Confirm only after blocking errors are resolved. The server rechecks the complete batch,
   permissions, owner, taxonomy and selected paper under transaction/row locks.
7. New named child hierarchy nodes, draft questions, translations, associations and audit rows
   are saved together. Any failure rolls the transaction back, including new papers/nodes.
8. Review and publish Question Bank content explicitly. Publish Previous-Year papers afterward.

Inline Add subject/Add topic is a separate permissioned POST action. Save edits first.
Those controls write the explicitly submitted taxonomy immediately; they are not preview
resolution and do not import questions. Row-driven child creation still waits for confirmation.
Topic inline creation uses an existing Subject and valid name/slug; normal hierarchy rules apply.

## Numbers, duplicate scope and historical safety

- A local number identifies a candidate master/translation group, not a global Question ID.
- Previous Year also rejects conflicts with existing paper numbers and requires explicit
  append acknowledgment for existing rows; acknowledgment does not override conflicts.
- Completed-file protection uses file_sha256 plus canonical context_sha256, not a global file hash.
- Context includes mode, selected Exams/mapping strategy and normalized paper identity when applicable.
- Corrections, uploader and alias/default changes do not evade the same-context duplicate guard.
- Staging UUID remains unique. Possible text matches in the bank block confirmation until staff record a decision. Repeated text within the file still warns.
- In Previous-Year preview, inspect the approved editions and choose **Reuse question** when the subject, supplied language text, options and correct answer match. The new paper pins that approved revision. Existing tags, text, explanations and historical appearances remain intact. Staff can explicitly create a separate question instead.
- In General preview, open the matched Question ID in Admin, then choose **Create a separate question** or **Skip this question** and save the preview page. Skipping excludes all language rows for that question. Restore it before confirmation if you change your mind. The completed batch lists skipped source rows.
- Use **Message** to filter preview rows by an individual error or warning. Clear the filters to edit rows or save duplicate decisions.
- No automatic source-ID merge scope is defined. Imports preserve source metadata instead.
- New rows are draft/pending_review; review_status/verification_notes/needs_review/handwriting do
  not grant editorial approval. Draft imports never replace old published revisions or attempts.

## Audit, bounds and cleanup

ImportBatch stores selection/mapping/format metadata and optional paper. ImportedQuestion
records source row/master with original, corrected and resolved metadata. Preserve bounded
audit values rather than assigning source timestamps or updated_by to system identities.

Defaults: 5 MB upload, 2,000 data rows, 64 columns, 32,000 characters per cell, 128 KB each
original/corrected row and 20 MB staging. XLSX archives allow at most 1,000 entries/30 MB
expanded. Source pages are bounded printable labels; numeric pages must be positive.

Staging defaults to two hours and is removed after cancellation/completion. Expiry cleanup
runs during uploads; cleanup_import_staging is available for separate scheduled execution.
No external scheduler is configured by this document. Token locks/version digests reject
stale edits; contextual uniqueness and workflow locks protect concurrent confirmation.

## General collections and checks

Source codes are optional. To introduce a code, supply `source_document` on at least one matching row. Other rows can reuse the code and provide their own `source_page` and `source_question_number`. Supply `source_publisher` when known. Preview resolves the shared source, and confirmation saves it and the question locators in the same transaction. Staff can see the result in the review sidebar's **Sources** panel.

GeneralQuestionBatch is a proxy over completed General ImportBatch records; no separate
Question Bank is created. The General UI/Admin delegates inspected-batch review/publication
to existing Question services. Open **Manage / General Questions** to choose an import mode or review existing questions. In the preview grid, double-click a cell or press Enter to edit it in a larger panel. Expand the pinned row status to inspect errors, warnings, and mappings. Save and revalidate before confirming. After confirmation, use **Review imported questions** to open that batch in the staff queue. See [workflow and rollback notes](question-workspace.md).

Start targeted verification with imports.tests, imports.test_unified, imports.test_wide_format
or imports.test_taxonomy_import, depending on the change. Add General/paper tests for affected
publication behavior. Historical test counts and milestone claims are not current test results.
