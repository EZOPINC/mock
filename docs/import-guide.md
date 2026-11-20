# Staff Question Import Guide

Open **Manage / General Questions** and choose **Import previous-year questions** or **Import general questions**. The [CSV contract](import-contract.md) owns header names, file limits, and validation details. The [workspace guide](question-workspace.md) owns post-import review and publication.

## Upload and preview

1. Choose the import mode and exam context. Previous Year uses the exam, year and paper details to find or prepare a draft paper. General accepts selected exams and optional row-based exam mapping. Choose a worksheet for multi-sheet XLSX files.
2. Supply question text, four options and a verified A-D answer. Use a subject code/name or a valid taxonomy path. Add a topic code and optional secondary codes when available. Use complete `_en` / `_bn` blocks for bilingual rows, or explicitly approve paired long rows.
3. In preview, expand a row's status to inspect its resolved values and issues. **Show** filters by severity. **Message** filters by an individual issue. Clear filters to edit. Double-click a cell or press Enter to edit longer text.
4. Resolve row errors, translation pairings and duplicate decisions. Use **Save page & Revalidate** before switching pages or confirming. To correct the file itself, choose **Replace uploaded file**. The upload form restores the current import settings and the new file starts a fresh preview with its own row edits and decisions.
5. Confirm when the batch has no blocking errors. The server rechecks the complete batch and saves valid rows atomically. Use **Review imported questions** when the batch is complete. Paper publication is separate from publishing its questions.

## Confirmation performance

Confirmation uses `questions/creation.py` inside the existing all-or-nothing import transaction. It reuses the locked Subject/Topic catalogue and newly inserted Question/Revision objects, avoids redundant foreign-key existence queries, and omits nested creation savepoints. Field, model, uniqueness and database-constraint validation remain enabled. An error must escape the creation scope and roll back the whole import; individual rows are not recovered inside it. Existing-question edits retain their lock and immutability checks. This is an internal optimization, with no schema or import-format change.

## Duplicate decisions

- **Previous Year** can reuse an approved match from the bank when the subject and supplied editions' text, options and correct answer match. The new paper occurrence pins that revision. Reviewers can also explicitly create a separate question.
- **General** shows matched Question IDs as Admin links. Choose **Create a separate question** or **Skip this question**. A skip excludes the incoming question's language rows, source links and taxonomy changes. Restore it before confirmation if needed.
- A repeated file in the same import context is blocked. Previous-Year imports also check existing question numbers and require acknowledgment before appending to previously imported papers.

## Private sources

Use `previous_year_tags` for appearances reported by the source. Separate entries with semicolons and end each entry with a four-digit year. The optional `Authority / Exam YYYY` format records the authority separately. The preview flags entries it cannot parse and preserves their text for staff. Open the question in the review workspace to verify each appearance before it is shown in Practice.

Supply optional `source_code` and `source_document` to register a source. Include the document on at least one row for a new code. Reuse the code with `source_page` and `source_question_number` for additional questions. `source_publisher` is optional. Staff can see the result in the question editor's **Sources** panel.

Samples are available in [CSV](samples/questions-taxonomy.csv) and [XLSX](samples/questions-taxonomy.xlsx). Use the codes in your own catalogue.
