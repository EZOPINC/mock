# Exam catalogue backup and restore

Owned by `exams`: ExamAuthority → Exam → ExamStage. This is separate from subject
taxonomy, and includes no questions, question/exam memberships, subjects, papers,
exam patterns, users, or attempt/session history. It is a catalogue seed/backup,
not a full database backup; deleting and restoring exams does not restore lost
question memberships or other dependent records. Existing database IDs are not
encoded or restored.

The current catalogue is backed up in `Data/Exams/exam_taxonomy.json`.

```console
python manage.py export_exam_taxonomy Data/Exams/exam_taxonomy.json
python manage.py import_exam_taxonomy Data/Exams/exam_taxonomy.json --dry-run
python manage.py import_exam_taxonomy Data/Exams/exam_taxonomy.json
```

Exports refuse to replace an existing file unless explicitly passed `--overwrite`.
Use a different filename to keep multiple backups. Export again before deleting
newly added/changed catalogue records.

Version 1 JSON has `schema_version: 1`, `kind: "exam_taxonomy"`, and an
`authorities` array. Each Authority has `code`, `name`, `slug`, `is_active`, and
nested `exams`. Each Exam has the same scalar fields and nested `stages`. Each
Stage has `code`, `name`, and `display_order`. Authority codes are globally
unique; Exam codes are scoped to Authority; Stage codes are scoped to Exam.
Parent nesting supplies all required FK references; no lookup by display name.

Import validates the full file before writing, then upserts in one transaction.
Dry runs perform zero writes and report create/update/unchanged counts. Repeated
imports are safe; existing scoped-code matches retain their IDs and FK links.
Display names, slugs, active status, and stage ordering can be updated. Omitted
records remain. Invalid rows, duplicate scoped codes and slug collisions fail;
database errors roll back the entire import. No migration is required.
