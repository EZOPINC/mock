# Question translation storage rollout

Source baseline before release 1: `3c77ef1`. This change preserves Question and QuestionRevision identities, the working and published pointers, and pinned references on mock sets, attempts, Practice and Previous-Year papers. The shared answer key remains on the revision, so equivalent answers must occupy the same option letter in each edition. No CSV headers change.

## Release 1: translation readers and compatible writes

| Checkpoint | Implementation |
|---|---|
| Audit and repair | `questions/migrations/0008_verify_translation_snapshots.py` checks every revision, including historical and draft revisions. It copies legacy primary text only when the primary translation is missing. Conflicts, incomplete legacy rows, blank required translation fields and inconsistent question IDs stop the migration. Existing translation rows are preserved. |
| Read editions | `questions/eligibility.py` reads published edition text and still requires a valid primary row. General Questions queue summaries, question revision Admin, Previous-Year Admin search and import duplicate-text checks use translation rows. Public readers already load editions from the revision's translations. |
| Create a revision | `questions/services.py` assembles the metadata and editions together in one transaction before moving the working pointer. Imports, the staff editor and translation edits use the metadata-plus-editions input. Older callers that supply primary text fields still work, and each new revision mirrors the primary edition into the compatibility columns. |

The configured local database was audited read-only on 2026-11-18. It contained 802 revisions and 1,293 translation rows. Missing primary editions, conflicting primary editions, incomplete legacy editions requiring repair, and invalid translation rows were all zero. Repeat the audit in the actual deployment database because this snapshot only describes the local database at verification time.

Release 1 passed 194 targeted PostgreSQL tests covering Questions, imports, the General Questions workspace, mock attempts, Practice services and Previous-Year papers. The migration ran only on the test database.

Apply `questions.0008_verify_translation_snapshots` before serving release 1 traffic. Its reverse operation leaves repaired translation rows in place. Release 1 can roll back to the previous application code because it keeps the older columns populated and preserves the revision and question IDs.

## Release 2: remove the compatibility columns

Migration `questions.0009_translation_text_only` rechecks the translation audit and removes the six legacy text columns and their revision-level content constraint. Questions, revisions and translation identities stay in place. The revision retains its primary language code, shared answer, difficulty and version timestamps. The text, options and explanation are stored only in `QuestionTranslation`. Legacy instance-level text access reads the primary edition, and the revision service still accepts the older input shape.

Before applying to the deployment database, verify release 1 on that database, take a schema and data backup, and stop application processes using the old model. After migration, smoke-test monolingual and bilingual imports, staff review and publication, and historical Mock, Practice and Previous-Year rendering. The ERD reflects the migrated test schema.

For rollback, reverse `0009` to `questions.0008_verify_translation_snapshots` before restarting the older application. The reverse migration recreates the columns, copies primary text from translations, and restores the old constraints. Missing primary editions prevent an incomplete rollback.

The broader Release 2 verification passed 193 targeted PostgreSQL tests. A separate 17-test Questions run verified the final migration round trip, missing-edition repair and conflict handling. The migrations ran only against disposable test databases. The configured application database was left unchanged.
