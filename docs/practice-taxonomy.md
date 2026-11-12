# Practice Setup and Taxonomy Discovery

Current reference, 2026-11-12. This replaces the former Part/Module/Chapter/Topic
configuration-page description; legacy service helpers remain for compatibility.

## Current student flow

1. Choose an authority/category, Exam and eligible Subject.
2. Selecting a Subject opens the available Module cards.
3. Select a Module, then choose a published difficulty level and English, Bengali or Both.
4. Start all eligible questions at that level in the selected Module in randomized order.
   Subjects without eligible Modules can continue with the whole Subject instead.
5. English or Bengali selects only questions with a complete matching translation in
   their published revision. Both includes all eligible questions and shows their available
   translations. Difficulty counts are shown before language filtering.
6. The language is saved in the immutable Practice configuration and restored across
   logins/devices for questions and feedback. Historical sessions retain their question
   sets and legacy display behavior; no migration is required.

No Part/Chapter/Topic dropdown or question-size selector appears in the new setup.
The old configure POST only resumes matching historical tokens; new starts go through
the difficulty page. The whole-subject difficulty route also remains available for
compatibility. Empty pools show an explicit message and create no session.

## Files and selectors

| File | Current responsibility |
|---|---|
| practice/views.py | Module cards, combined difficulty/language setup and start orchestration |
| practice/forms.py | PracticeDifficultyForm; legacy PracticeStartForm remains implemented |
| practice/discovery.py | PracticeTaxonomy pools/ancestry; difficulty_pools; configuration_matches |
| templates/practice/configure.html | Available Module cards / whole-Subject fallback |
| templates/practice/difficulty.html | Difficulty/language choices and explicit Start practice POST |

PracticeTaxonomy reuses exam eligibility and distinct master IDs from primary/secondary
QuestionTopic tags. Stored parent FKs support every permitted skipped level. A selected
parent includes descendants; inconsistent branches and cross-Subject service filters fail.
No child filter at service level includes all eligible Subject questions, including
unclassified rows. Pool IDs are sets, so multiple matching tags cannot duplicate a master.

Difficulty comes from published_revision, normalized for grouping. Blank difficulty is
Unspecified difficulty. A working draft's changed difficulty does not change the pool.
The service-level count/hierarchy interfaces remain; static/js/practice-filters.js is a
legacy asset rather than the current configure-page dependency.

## Compatibility and performance

Creation/retry/feedback rules are in [Practice engine](practice-sessions.md). Sessions freeze
selected approved revisions, order and explicitly supplied taxonomy labels/IDs. Existing
sessions are never backfilled or retagged by browsing the new setup.

Question.topic remains intentional: shared optional topic_id eligibility still means the
legacy primary Topic; advanced taxonomy discovery separately uses any primary/secondary
tag. Performance summaries use frozen primary classification, not whichever tag matched.

Taxonomy rows and associations load in bounded query batches; pools are materialized in
memory, as is shared eligibility. This is not a claim of constant memory or load-tested
large-pool performance. Reuse existing selectors and evaluate scale before redesigning.

Targeted checks: practice.test_taxonomy, practice.test_difficulty and practice.tests.
Changing the shared engine also warrants revision.test_sessions. Commands/results in old
phase notes are historical, not checks rerun by this documentation update.
