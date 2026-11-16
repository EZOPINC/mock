# Subject taxonomy imports

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
`submodule_code` as their immediate parent reference; omit `module_code` there.
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
Existing parent paths remain immutable: changing an established Chapter to a
Submodule is rejected rather than silently moving its question classification.
Submodule codes are globally unique within their record type, just like Module
codes. Model checks and PostgreSQL guards reject cross-subject and multi-parent
assignments. Admin provides Sub-module management and ancestor-aware filters.

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
