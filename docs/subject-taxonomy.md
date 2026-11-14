# Subject taxonomy imports

Taxonomy belongs to `exams`; existing Subject, Module, Chapter and Topic IDs,
QuestionTopic links, exam associations and legacy unparented topics are retained.
No question content or historical snapshots are modified. Migration
`exams.0005_subject_display_order_topic_notes` adds defaulted Subject.display_order
and Topic.notes fields. Existing name, code and display_order fields supply labels,
stable lookup codes and ordering. Existing database constraints enforce globally
unique codes per record type (including case/outer-whitespace normalization),
scoped names/slugs and consistent ancestry. Legacy Part paths remain supported.

## Version 1 format

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
means a direct subject path, and a changed parent path is rejected.

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

The supplied workspace `ancient_india_taxonomy.json` is an incomplete JSON fragment
(starts inside a topic and ends inside a topic). It must be replaced with the
complete source before its intended 16 chapters and 196 topics can be verified.
