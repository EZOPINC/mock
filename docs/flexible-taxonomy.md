# Phase D2 — flexible academic taxonomy

This supersedes the mandatory intermediate chain in `question-taxonomy.md`.
The taxonomy stays independent of Exam and ExamAuthority. Models and IDs are
reused; Question.topic and all revision, translation, paper and attempt links stay.

## Parent rules

| Node | Immediate parent | Subject compatibility anchor |
| --- | --- | --- |
| Subject | Root | Itself |
| Part | Subject | Required Subject FK |
| Module | Part, otherwise Subject | Required Subject FK, derived from Part when omitted by ORM callers |
| Chapter | Module or Part, otherwise Subject | Required Subject FK, derived from the chosen parent |
| Topic | Chapter, Module or Part, otherwise Subject | Existing required Subject FK, derived when omitted with a deeper parent |

The Subject FK is ancestry metadata when a deeper parent is set, **not a second
immediate parent**. Chapter/Topic database checks allow at most one deeper parent;
required Subject makes the zero-deeper-parent case a direct Subject attachment.
Cross-subject ancestry is rejected by model validation and PostgreSQL triggers.
No placeholder Parts/Modules/Chapters or guessed academic classification is created.

Existing Part/Module/Chapter parent paths remain immutable. Topic may be classified
or reassigned within the same Subject, as before; Subject ancestry cannot change.
All parent FKs use PROTECT. Direct-parent names (case-insensitive and trimmed) and
slugs are unique within that immediate parent. Identical Topic names/slugs in
different branches are allowed. Name-based import ambiguity requires explicit
existing-topic mapping; imports do not infer a branch or consume new code columns.

## Stable codes

Subject.code is retained verbatim. Part/Module/Chapter/Topic gain unique codes,
including case-insensitive trimmed uniqueness and nonblank checks. Uniqueness is
per model, so future code lookups must also specify the taxonomy level.

Existing records receive `PART-<id>`, `MODULE-<id>`, `CHAPTER-<id>` or `TOPIC-<id>`.
New records default to a type prefix plus UUID, generated once. Rename/reorder does
not regenerate codes. The four hierarchy triggers prohibit changing existing
node codes, and Admin makes them read-only after creation. Subject retains its
existing code semantics; the migration does not recode subjects.

## Migration 0004 and safety

`0004_flexible_academic_taxonomy` is an atomic PostgreSQL migration. It temporarily
removes the four old hierarchy triggers, adds nullable fields for backfill, copies
Subject ancestry through existing parents, assigns deterministic codes, makes the
anchors/codes non-null, installs scoped constraints, then reinstalls all four
triggers using the revised `exams_guard_taxonomy()` function. Existing field names,
IDs and parent paths are retained. Constraint/trigger replacement does not remove
academic records. Topic also gains display_order with default zero.

No Question, QuestionRevision, QuestionTranslation, QuestionExam, paper, import
audit, MockAttempt or Practice record is updated. Missing question topics remain
missing. Difficulty values and frozen revisions remain untouched.

Before applying elsewhere, run the read-only taxonomy audit and review duplicate
codes or normalized names within proposed parent scopes. Duplicate data causes an
atomic migration failure; no records are silently merged, renamed or deleted.
After migration run `python manage.py audit_taxonomy` and
`python manage.py makemigrations --check --dry-run`.

## Rollback

Rollback to exams 0003 is permitted only for legacy-shaped data: every Module has
Part, every Chapter has Module, Topics have no direct Module/Part parent, old
subject-wide Topic slug uniqueness still holds, and new codes equal their
deterministic backfill values. The migration checks this **before** reversing
anything. If new optional paths, branch-local slugs or new/custom codes would be
lost, rollback is refused atomically and the D2 schema/data remain intact.

Do not force nulls into old mandatory parents or drop code columns to bypass the
guard. Retain D2, export classification/code mappings, and prepare a separately
reviewed conversion/rollback migration if newer data must be retained. A safe
legacy-shaped reverse/reapply restores the same IDs and deterministic codes.

## Compatibility and boundaries

Admin supports direct Subject and optional deeper parent fields. Legacy calls
such as `Module(part=...)` and `Chapter(module=...)` derive Subject automatically.
The read-only audit follows the new Subject anchors rather than assuming a
mandatory Module→Part path. Mock/Practice selection logic is unchanged.
QuestionTopic, difficulty normalization and import schema expansion remain later
phases; this phase does not start D3.

## D2 verification

243 distinct targeted PostgreSQL tests passed across taxonomy, migration,
Question Bank, imports, Mock attempt services, Practice services and Previous-Year
model/viewer suites. Migration tests cover deterministic backfill, safe reverse
and reapply, blocked optional-path rollback and blocked code loss. No full-project
regression was run. Django check and migration dry check passed.

Local migration preserved row counts and complete-row fingerprints across 13
unchanged tables, plus the original Topic fields. The 136 Topics received codes;
230 questions still have no topic. The expanded integrity audit found zero
mismatches. No difficulty or historical content was rewritten.
