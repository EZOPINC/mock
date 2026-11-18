# General Questions and Solutions workspace

Workspace baseline before implementation is `096a294e3f32991233d9caad55c79f2a1e78e3a4`. These checkpoints describe source changes. The workspace adds no database migrations.

## Staff workflow

1. Open **Manage / General Questions**. Choose **Import previous-year questions** or **Import general questions**. General imports use the existing default subject, selected exams, and row exam mapping.
2. Inspect the import grid. Scroll to the language and source columns. Open a row status for its errors, warnings and resolved mappings. Double-click a cell or press Enter for a larger editor. Use **Save page & Revalidate** before confirming. Filtered preview pages are read-only. Clear the filters to edit.
3. Open **Review questions** to go straight to the queue, or open **Review dashboard** for counts by subject, exam, module, chapter and previous-year paper year. Each module or chapter counts a question once, including matches through additional topic tags. General Questions counts imported questions with no previous-year paper link. Click a count to open its filtered queue. After confirming an import, select **Review imported questions** to open that batch. The queue also filters by import batch, taxonomy, language, kind, review status, publication status and text.
4. In the question editor, read the working revision in its available languages. Edit the subject, primary and additional topics, exam associations, question kind and freshness dates. A topic carries its module and chapter through its taxonomy path. Choosing a different subject clears incompatible topic choices. Papers with fixed subject or exam requirements constrain these edits.
5. Save an individual question and add the inspected version to the selection. The selection is stored in the staff browser session and persists across queues and pages. From the queue use **Mark selected reviewed** and then **Publish selected**. Actions are atomic and stale selections are rejected. Use **Selected only** to inspect the selection. Saving another edit removes that question from the selection until it is inspected again.
6. The General batch page still supports whole-batch review and publication. Actions there include every question in that batch. Previous-year paper publication remains a separate operation. If an edited question is published while its draft paper still points to an unpublished import revision, the draft row advances to the newly approved revision. Published paper rows and existing approved pins keep their revisions.

## Milestones and rollback boundaries

| Step | Changes and boundary | Rollback |
|---|---|---|
| M1. Desktop shell and import preview | Standalone `templates/imports/base.html`, grid markup in `templates/imports/preview.html`, the import-grid rules in `static/css/question-workspace.css`, and the cell editor in `static/js/import-preview.js`. Existing field names, save and validation endpoints, and staging behavior remain in use. | Restore the preview template and JS to the baseline to recover the original grid. The standalone shell can remain. |
| M2. Import entry points and dashboard | Entry points in `templates/general_question/manage.html`, `templates/components/header.html`, and `imports/views.py`. Dashboard, queue, routes, and staff gating are in `general_question/review_views.py`, `general_question/urls.py`, `general_question/views.py`, and the dashboard and queue templates. Completion links use the batch ID. | For a dashboard rollback, remove links from the shell, landing page and completion template before removing its routes. Keep staff gating if the workspace must stay private. |
| M3. Question editor | `general_question/review_forms.py`, `general_question/review_services.py`, the question endpoint and editor template. Uses Question and topic workflows. | Remove the editor route and switch queue and batch question links back to Django Admin. The dashboard and original whole-batch actions can remain. |
| M4. Selected review and publication | Session selection in `review_views.py`, `selection_actions.html`, and `transition_selection` in `review_services.py`. Draft Previous-Year paper repair is part of selected publication. | Disable the selection buttons and POST actions. The editor and existing signed whole-batch actions can remain. |
| Supporting import header fix | `imports/parsing.py` lists `subject` only once in the canonical CSV headers. | Can be reverted independently. The pre-existing duplicate breaks CSV files generated from the canonical header list. |

For a full rollback, restore the tracked files from the baseline and remove only the new workspace files. Do this in reverse milestone order if rolling back selectively. Source rollback leaves imported questions and editorial operations already saved to PostgreSQL in place.

Verify uploads on the normal Django server. The tool sandbox used for the earlier preview could not write to the private staging directory. The staging root and file-creation logic are outside this change.

## Verification record

- M1 and M2 passed the import parsing, preview, confirmation and dashboard integration checks.
- M3 and M4 passed the saved-revision, stale-form, selected review and publication, and edited draft-paper integration checks.
- The final workspace and import suites passed all 72 tests against PostgreSQL. Django checks found no missing migrations.
- Five Previous-Year viewer and feedback assertions also failed on the unchanged baseline in an isolated checkout. The workspace update leaves those templates and behavior outside its scope.
- An upload into the actual staging directory on the normal server remains a manual rollout check.
