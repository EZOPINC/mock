# General Questions and Solutions workspace

Open **Manage / General Questions** with active staff permissions to view import batches and change questions. The standalone workspace shares the [staff importer](import-guide.md).

## Review and publish

- **Review dashboard** counts imported questions by subject, exam, module, chapter and paper year. General Questions have no Previous-Year paper link. Counts link to the filtered review queue.
- **Review questions** filters by import batch, source, taxonomy, language, kind, working difficulty, status and text. Subject narrows module, chapter and topic. Module narrows chapters and topics. Chapter narrows topics. **Any** difficulty means unrated. **All difficulties** clears the rating filter.
- The editor shows the working language editions. The sidebar edits subject, primary and additional topic tags, exams, kind, difficulty and freshness dates. It also displays private sources. Module and chapter follow the selected topic path. Papers with fixed subject or exam requirements constrain edits.
- Save, inspect, then add a question to the session selection. **Mark selected reviewed** and **Publish selected** operate atomically on that selection, even across pages. Stale changes require reinspection. Editing a selected question removes it from the selection.
- A General batch can still be reviewed or published as a whole. Paper publication is separate. If an edited draft paper row still pins an unpublished import revision, selected publication advances it to the newly approved revision. Approved historical pins remain intact.

## Rollback reference

The workspace started at source baseline `096a294e3f32991233d9caad55c79f2a1e78e3a4`. The checkpoints below describe the original rollout and its source dependencies.

| Step | Changes and boundary | Rollback |
|---|---|---|
| M1. Desktop shell and import preview | Standalone `templates/imports/base.html`, grid markup in `templates/imports/preview.html`, the import-grid rules in `static/css/question-workspace.css`, and the cell editor in `static/js/import-preview.js`. Existing field names, save and validation endpoints, and staging behavior remain in use. | Restore the preview template and JS to the baseline to recover the original grid. The standalone shell can remain. |
| M2. Import entry points and dashboard | Entry points in `templates/general_question/manage.html`, `templates/components/header.html`, and `imports/views.py`. Dashboard, queue, routes, and staff gating are in `general_question/review_views.py`, `general_question/urls.py`, `general_question/views.py`, and the dashboard and queue templates. Completion links use the batch ID. | For a dashboard rollback, remove links from the shell, landing page and completion template before removing its routes. Keep staff gating if the workspace must stay private. |
| M3. Question editor | `general_question/review_forms.py`, `general_question/review_services.py`, the question endpoint and editor template. Uses Question and topic workflows. | Remove the editor route and switch queue and batch question links back to Django Admin. The dashboard and original whole-batch actions can remain. |
| M4. Selected review and publication | Session selection in `review_views.py`, `selection_actions.html`, and `transition_selection` in `review_services.py`. Draft Previous-Year paper repair is part of selected publication. | Disable the selection buttons and POST actions. The editor and existing signed whole-batch actions can remain. |
| Supporting import header fix | `imports/parsing.py` lists `subject` only once in the canonical CSV headers. | Can be reverted independently. The pre-existing duplicate breaks CSV files generated from the canonical header list. |

For a full rollback, restore the tracked files from the baseline and remove only the new workspace files. Do this in reverse milestone order if rolling back selectively. Source rollback leaves imported questions and editorial operations already saved to PostgreSQL in place.

Verify uploads on the normal Django server. The tool sandbox used for the earlier preview could not write to the private staging directory. The staging root and file-creation logic are outside this change.

## Original rollout verification

- M1 and M2 passed the import parsing, preview, confirmation and dashboard integration checks.
- M3 and M4 passed the saved-revision, stale-form, selected review and publication, and edited draft-paper integration checks.
- The initial workspace and import suites passed 72 tests against PostgreSQL. Django checks found no missing migrations.
- Five Previous-Year viewer and feedback assertions also failed on the unchanged baseline in an isolated checkout. The workspace update leaves those templates and behavior outside its scope.
- The original test run used disposable staging. Verify the configured staging directory through the normal Django server when deploying changes.
