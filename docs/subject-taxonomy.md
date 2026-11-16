# Subject taxonomy imports

## Explicit Module-to-Part correction

Normal imports/admin edits still protect established Module parents. For a
reviewed classification correction within the same Subject, use
`reassign_module_part`. It requires exact Subject, Module, expected source Part,
and destination Part codes. Default is a zero-write preview; apply requires
`--apply`. Explicit creation also requires `--create-part --part-name` and may
supply `--part-order`. The Module and all descendants retain IDs/codes/links.

```console
python manage.py migrate
python manage.py reassign_module_part --subject geography --module geo-west-bengal-mod01 --from-part geo-india --to-part geo-west-bengal --create-part --part-name "West Bengal" --part-order 2
python manage.py reassign_module_part --subject geography --module geo-west-bengal-mod01 --from-part geo-india --to-part geo-west-bengal --create-part --part-name "West Bengal" --part-order 2 --apply
```

Migration `0010_explicit_module_part_reassignment` adds a transaction-local guard
exception for exactly one Module ID/source Part ID/destination Part ID tuple.
Subject/code changes, cross-subject moves and ordinary unapproved parent updates
remain blocked. The command locks the selected Subject/Module, validates normal
model constraints, creates the destination only when requested, and saves through
the model in one transaction. Authorization is cleared after the operation.
Reruns targeting the Module's current destination report unchanged; a different
unexpected source aborts. Existing Part codes are never renamed.

Update the original JSON too: declare the new Part in `parts` and change only the
Module's `part_code`. Its Submodules keep their existing `module_code`; their
Part ancestry follows the Module automatically. The West Bengal file now declares
Part `geo-west-bengal` (West Bengal), preserving the shared `geo-india` (India)
Part used by Indian Geography. Historic snapshots are untouched; future Part
filters follow the corrected classification.

## Import every subject file in a directory

```console
python manage.py import_subject_taxonomies --create-subjects --dry-run
python manage.py import_subject_taxonomies --create-subjects
```

The default folder is `Data/Subjects` under the project root. To override it,
supply the directory as a positional argument. Files with a `.json` extension
are processed in case-insensitive filename order, without recursion. Every file
uses the existing single-file importer planner and persistence workflow.
`--create-subjects` is optional when all Subject codes already exist.

Each file has its own transaction. Failure rolls back that file and is logged;
the next file is still processed. Successful files remain committed even if a
later file fails. The command exits nonzero if any file failed. There is no
implicit reparenting or automatic inference/repair of missing relationships.
The explicit `--attach-unassigned-chapters` repair option is also supported.

Files marked `kind: "subject_taxonomy_backup"` are skipped by default, preventing
an older combined backup from overwriting the newer subject-wise imports. Use
`--include-backups` only when that behavior is intended. A dry run makes zero
database writes: each file is checked independently against the current database,
so dependencies created only by an earlier file in the same dry run are not
available. Keep each subject file self-contained, or import its parent definitions
first. Summary totals count per-file actions, not distinct nodes across files.

A new UTF-8 JSON Lines log is created at
`logs/taxonomy-import/bulk-<UTC timestamp>-<unique suffix>.jsonl`. Use
`--log-file path/to/new-results.jsonl` to choose a different new file; existing
logs are never overwritten. Each line is one JSON object: run settings, per-file
status/counts/warnings/errors, or the final summary. The log is flushed after
each file. A log failure stops further work; previously committed files remain.

Missing/unknown parents, cross-subject links, missing required parent codes,
duplicate codes, malformed JSON and forbidden parent changes are logged as errors
by the authoritative importer. File-local relationship warnings identify valid
direct-Subject Chapters and declared nodes with no children referencing them in
that file. Such warnings are informational: links can exist in another file or
the database, and skipped intermediate levels are valid. Validation reports the
first blocking error in each file; correct it and rerun to reveal further issues.

## Back up and restore all subjects together

```console
python manage.py export_subject_taxonomy Data/Subjects/subject_taxonomy_backup.json
python manage.py import_subject_taxonomy Data/Subjects/subject_taxonomy_backup.json --create-subjects --dry-run
python manage.py import_subject_taxonomy Data/Subjects/subject_taxonomy_backup.json --create-subjects
```

Export includes every Subject, Part, Module, Submodule, Chapter and Topic in one
file. No per-subject runs are needed. To refresh an existing backup, add
`--overwrite` to export; without it an existing file is protected. `--create-subjects`
is needed on restore only if Subject codes are absent from the destination.

Backups use schema version 1 plus `kind: "subject_taxonomy_backup"`. They preserve
codes, names, slugs, ordering, notes, subject anchors and actual immediate parents,
including skipped levels and legacy Topics directly under Subject, Part or Module.
The backup marker explicitly enables restoring those existing legacy shapes;
normal taxonomy imports continue to require a Topic's chapter. Optional `slug`
values are accepted by the importer; omitted slugs retain existing behavior.

Repeated restore preserves existing IDs/links for matching codes, rejects
reparenting, and retains omitted records. This is a taxonomy backup only: it
does not include questions/tags, papers, exam membership, users, or history, and
does not restore original numeric IDs after records have been deleted. Use a
database backup for those relationships and records. No migration is needed.

## Purging unused old taxonomy records

`purge_subject_taxonomy` preserves Subject rows and defaults to a zero-write
preview. The taxonomy JSON importer does not persist per-node import ownership.
Question import audit metadata proves usage, not ownership, so this command
requires an explicit old-code manifest instead of guessing from names, prefixes,
dates, or the current taxonomy files. Obtain this list from the actual old import
files and review it; there is no automatic descendant expansion.

Example `old-taxonomy-codes.json` (replace all example codes with actual old codes):

```json
{
  "version": 1,
  "parts": ["OLD-PART"],
  "modules": ["OLD-MODULE"],
  "submodules": ["OLD-SUBMODULE"],
  "chapters": ["OLD-CHAPTER"],
  "topics": ["OLD-TOPIC"]
}
```

Empty/omitted record-type arrays select nothing. Unknown/duplicate codes, unknown
subjects and any code outside the selected subjects fail closed. Subject codes
are supplied separately, explicitly; repeat `--subject` to select multiple subjects.

The original version 1 taxonomy import JSON may also be passed to `--old-codes`.
`schema_version`, `subject`/`subjects`, and descriptive `scope` are accepted. For
each taxonomy array, only explicitly listed `code` values are selected; labels and
parent references do not select additional records. Declared subject codes must
be within the command's explicit `--subject` selection, and every code is still
checked against its actual subject in the database. Subject records in the file
are never deleted. Use the actual old import file, not a replacement taxonomy
whose codes you intend to keep.

```console
python manage.py purge_subject_taxonomy --subject history --old-codes old-taxonomy-codes.json
python manage.py purge_subject_taxonomy --subject history --old-codes old-taxonomy-codes.json --apply
```

Preview reports counts by type/subject, affected internal/external FK links,
M2M membership, deletion policies, cascade restrictions and preserved domain
counts. An external reference blocks preview/apply with a nonzero exit status;
it is never detached, nulled or cascaded away. For example, selecting a Chapter
without its still-linked Topics is blocked. Include only independently reviewed
old codes; do not expand the list to referenced questions/history to force deletion.

Inbound relationship inspection covers the entire installed model registry,
including explicit and automatic M2M through tables. Current taxonomy references:

| Target | Inbound references |
|---|---|
| Subject (always preserved) | Part, Module, Submodule, Chapter, Topic, Question, PreviousYearPaper, ExamPatternSection, SectionSelectionRule, PracticeSession |
| Part | Module, Chapter, Topic, SectionSelectionRule |
| Module | Submodule, Chapter, Topic, SectionSelectionRule |
| Submodule | Chapter |
| Chapter | Topic, SectionSelectionRule |
| Topic | Question.topic, QuestionTopic.topic (Question.topics M2M), ExamPatternSection, SectionSelectionRule, PracticeSession |

All current inbound FKs above use PROTECT. Papers and attempts also link
indirectly through questions/revisions/patterns; those records are never selected.
Historical JSON snapshots and audit data remain untouched. They are not FKs or
proof of taxonomy ownership.

Apply uses one transaction, locks only selected Subjects/nodes, rechecks live
references, and deletes child-to-parent through normal Django deletion. Unexpected
cascades/deletion counts or any change in Subject, Exam, question/revision/tag,
paper/association, pattern/section/rule, mock attempt/answer, Practice/revision or
import-audit counts abort and roll back the operation. No migration is required.

Taxonomy belongs to `exams`; existing Subject, Module, Chapter and Topic IDs,
QuestionTopic links, exam associations and legacy unparented topics are retained.
No question content or historical snapshots are modified. Migration
`exams.0005_subject_display_order_topic_notes` adds defaulted Subject.display_order
and Topic.notes fields. Existing name, code and display_order fields supply labels,
stable lookup codes and ordering. Existing database constraints enforce globally
unique codes per record type (including case/outer-whitespace normalization),
scoped names/slugs and consistent ancestry. Legacy Part paths remain supported.

## Version 1 format

Optional Sub-modules are supported between Module and Chapter. A Submodule has
one required Module and a same-subject anchor. A Chapter keeps exactly one
immediate parent: Submodule, Module, Part, or Subject. Existing chapters need no
change and retain their IDs and links; adding this level does not move records.

Version 1 accepts a `submodules` array. Each record uses `code`, `module_code`,
`subject_code`, `name`/`title`, and optional `sort_order`. In the single-subject
format, `subject_code` is inherited. Chapters under this level supply only
`submodule_code` as their immediate parent reference. An optional `module_code`
or `part_code` on that chapter is validated as ancestor context and must match
the Submodule's ancestry; only the Submodule FK is stored.
Chapters that skip the level continue to use `module_code` or no parent code.

```json
{
  "version": 1,
  "subject": {"code": "history"},
  "modules": [{"code": "H-M", "name": "Example module"}],
  "submodules": [{"code": "H-SM", "module_code": "H-M", "name": "Example sub-module"}],
  "chapters": [
    {"code": "H-C1", "submodule_code": "H-SM", "name": "Nested chapter"},
    {"code": "H-C2", "module_code": "H-M", "name": "Direct module chapter"}
  ],
  "topics": [{"code": "H-T", "chapter_code": "H-C1", "name": "Example topic"}]
}
```

Run `python manage.py migrate` before using these fields. The existing
`import_subject_taxonomy <file.json> --dry-run` / apply commands are unchanged.
Existing parent paths remain protected. An explicit first same-Module Submodule
assignment is supported as described below; moves to another Module or between
established Submodules are rejected.
Submodule codes are globally unique within their record type, just like Module
codes. Model checks and PostgreSQL guards reject cross-subject and multi-parent
assignments. Admin provides Sub-module management and ancestor-aware filters.

Both `submodules` / `submodule_code` and `sub_modules` / `sub_module_code` spellings
are accepted. The exporter writes the canonical spelling without the extra
underscore. Supplying both arrays or conflicting parent aliases fails validation.
Unknown top-level or taxonomy record fields now fail explicitly instead of being
silently ignored. Bulk relationship diagnostics use the same normalization.

If a previous import ignored Sub-module fields and placed chapters directly
under their Module, migration `0009_chapter_initial_submodule_assignment` supports
a narrow repair. Use `--attach-submodules` on either import command. It permits
only a chapter with no Submodule/Part and an existing Module to receive its first
Submodule belonging to that exact Module. IDs, codes, Topic links and effective
Module ancestry remain fixed. Removing or changing an assigned Submodule, moving
between Modules, and changing the Subject remain blocked by model/PostgreSQL
guards. New Submodules can be declared in the same file.

```console
python manage.py migrate
python manage.py import_subject_taxonomies --attach-submodules --dry-run
python manage.py import_subject_taxonomies --attach-submodules
```

Ordinary repeat imports then work without the repair flag. Existing normal
Module-parent chapters can still skip Submodules. The planner preloads the
catalogue in six queries and reuses its objects for ancestor resolution rather
than querying each parent separately for every file.

```json
{
  "version": 1,
  "subjects": [{"code": "HI", "name": "History", "sort_order": 0}],
  "modules": [{"code": "HI-ANC", "subject_code": "HI", "name": "Ancient India"}],
  "chapters": [{"code": "HI-STONE", "subject_code": "HI", "module_code": "HI-ANC", "name": "Stone Age", "sort_order": 1}],
  "topics": [{"code": "HI-SOURCES", "subject_code": "HI", "chapter_code": "HI-STONE", "name": "Sources and periodisation", "notes": "Optional notes", "sort_order": 1}]
}
```

All arrays are optional. References can resolve to records already in the database
or declared in the file. Omit module_code to place a chapter directly under its
subject. Topics require chapter_code. Existing legacy topics remain valid and are
never automatically assigned to chapters. Codes are unique within each record
type across all subjects, so question spreadsheets can resolve topic_code alone.
Display-name updates preserve codes, slugs, IDs and links. Missing fields on
existing records preserve name, order and notes; omission of a parent reference
means a direct subject path. Changed established parent paths are rejected.

Optional `parts` records use `code`, `subject_code`, `name`/`title` and
`sort_order`, just like modules. A module may supply `part_code` referencing an
existing Part or a Part declared in the same file. `schema_version: 1` is also
accepted as the version field. `scope` remains descriptive and never creates a Part.
Use the actual existing Part code when a named Part already exists; a new code
does not rename or replace that record.

Migration `0006_module_initial_part_assignment` permits one narrow correction:
a module directly under a Subject may receive its first Part in that same Subject.
An explicit `part_code` imports this as an update, and Admin also permits it.
Subject, code and IDs remain fixed; existing chapter/topic links and historical
snapshots are untouched. Once assigned, the Part cannot be removed or changed.
Cross-subject assignments remain blocked by model validation and PostgreSQL.

Migration `0007_chapter_initial_module_assignment` similarly allows a chapter
directly under its Subject (no Part or Module) to receive its first same-subject
Module. For existing chapters, the importer requires the explicit
`--attach-unassigned-chapters` option as well as `module_code` on each chapter.
Without the option, existing-parent changes are still rejected. Chapters already
under a Part or Module cannot move. IDs, topic links and codes are preserved.

The supplied `Data/Questions/ancient_india_taxonomy.json` now explicitly sets
`"module_code": "hist-anc"` on its 16 chapters. To repair an earlier direct-subject
import, run:

```console
python manage.py migrate
python manage.py import_subject_taxonomy Data/Questions/ancient_india_taxonomy.json --attach-unassigned-chapters --dry-run
python manage.py import_subject_taxonomy Data/Questions/ancient_india_taxonomy.json --attach-unassigned-chapters
```

Once attached, ordinary repeat imports work without the repair option.

The original single-subject format is also accepted: omit version (defaults to 1),
use `"subject": {"code": "HI", "name": "History"}` (or a subject code string),
and use `title` instead of `name`. Children inherit this subject_code. `scope`
is descriptive metadata only; it never creates a module. The Ancient India
chapters therefore import directly under History when module_code is absent.
Use the actual existing History subject code; names never resolve subjects.

```console
python manage.py migrate
python manage.py import_subject_taxonomy ancient_india_taxonomy.json --dry-run
python manage.py import_subject_taxonomy ancient_india_taxonomy.json
```

Unknown subjects fail clearly. Explicitly add `--create-subjects` to create named
subjects declared in the file. Dry runs report per-type create/update/unchanged
counts without writes or sequence allocation. Full imports validate first and
save in parent order within one transaction, using foreign keys. A concurrent
uniqueness conflict rolls back the entire import. Repeated imports are safe;
omitted records are preserved and implicit reparenting is rejected.

CSV/XLSX imports already accept optional topic_code, show its full ancestor path
in preview and attach tags to the shared question through the tagging service.
A supplied row subject or form subject conflicting with topic_code is rejected.
Blank topic_code preserves existing behavior. Practice discovery already walks
both direct-subject chapters and module chapters and includes legacy topic tags.
Admin module filters include topics through chapters; chapter choices narrow by
the selected subject and module.

Large taxonomy admin forms omit inline lists that would exceed Django's request
field budget, exposing filtered "Manage" links instead. Small lists retain inline
editing. This applies to Subject, Part, Module and Chapter screens and leaves the
global `DATA_UPLOAD_MAX_NUMBER_FIELDS` limit unchanged.

The supplied workspace `ancient_india_taxonomy.json` is an incomplete JSON fragment
(starts inside a topic and ends inside a topic). It must be replaced with the
complete source before its intended 16 chapters and 196 topics can be verified.
