# Milestone 2.3C: multilingual questions

## Wide extraction format extension (2026-11-04)

The current importer also accepts explicit `question_text_en`, `option_a_en`
through `option_d_en`, their `_bn` equivalents and optional per-language
`explanation_en` / `explanation_bn`. A wide source row maps to one master with
only available translations; `language=en,bn` is allowed. Generic content must
agree with an available version; incomplete/conflicting blocks require correction.
Separate long rows retain explicit pairing approval and shared-attribute checks.
`handwritten_mark_unverified` and `needs_review` are audit metadata and preview
warnings only. Verified A/B/C/D answers remain mandatory before confirmation;
no mark becomes an answer automatically. No schema or publication policy changes.
See [import guide](import-guide.md) for header requirements and the reviewed
100-row WBP SI 2019 extraction example.


This user-approved design supersedes the Phase 0 rule that English and Bengali
must always be independent Question identities. Published-history protection,
draft-by-default imports and explicit review/publication are unchanged.

## Identity and immutable snapshots

- Question is the master: Subject, Topic, exam/source associations, current shared
  correct_answer and difficulty_level, and working/live revision pointers.
- QuestionRevision remains the version snapshot used by PaperQuestion and future
  attempts. Shared answer/difficulty are snapshotted once per revision so changing
  a working answer cannot change a historical paper's answer. They are not stored
  independently per translation. Services synchronize the master working values.
- QuestionTranslation belongs to Question and a specific QuestionRevision, with
  language, text, four options and optional explanation. Unique (revision, language)
  allows only available versions, with no empty placeholder translation. FK links
  use PROTECT. Existing revision/language indexes cover the main access paths.
- Translation rows are append-only. Add/update through Question Admin's
  **Add/update language translation**, which creates a complete new revision and
  resets review. Existing live translations stay unchanged until explicit review
  and publication. Published paper rows keep their original revision pointers.
- The existing QuestionRevision language/content fields remain as the primary
  language compatibility snapshot for old callers. The matching translation is
  created automatically and must match it exactly. This transitional content
  copy avoids breaking existing imports/templates/callers; no classification,
  exam membership or per-language answer is duplicated in translation rows.

`QUESTION_LANGUAGES` in settings currently enables English (en) and Bengali (bn).
Language fields accept bounded language-code syntax for future configured locales;
add supported language labels there and restart the application. Automatic script
inference remains en/bn only; other languages require an explicit configured code.

## Importing English-only, Bengali-only and bilingual content

Use the existing long-row CSV/XLSX contract and both import modes. Each row holds
one available language. For bilingual content, repeat question_number in the same
selected paper/import context with a different language. Keep the same correct
answer letter (and option order), Subject, Topic, difficulty and exam associations.

The preview proposes translation groups and shows every version. Check **I verified
that these are translations of the same question**, then **Save & Revalidate**.
Approval is bound to the exact values and resolved mappings; edits invalidate it.
Same-language duplicates and mismatched shared attributes remain blocking errors,
even if the checkbox is selected. Renumber genuinely different questions or split
them into their actual source-paper contexts. Never merge by similar text.

Confirmation creates one master/revision and its language rows, one exam association
per resolved exam, and one PaperQuestion per master for Previous Year mode. General
mode creates no papers. Audit retains every original/corrected source row, resolved
language, master ID and pairing signature; source-row counts can exceed master
question counts. Difficulty is optional bounded shared text, not a new difficulty
selection/scoring feature. No answer, translation or classification is invented.

Pairing is limited to the current uploaded source context. Imports do not silently
merge legacy masters, match by number across unrelated papers, or modify existing
paper rows. For a translation arriving later in a separate file, explicitly add it
to the verified master in Question Admin, review/publish the new revision, and
explicitly select that revision in an unpublished paper if desired. Existing
source metadata, exam/year associations and old Question IDs remain intact.

## Migration and display

Questions migration 0002 adds translation storage, shared working attributes and
future-compatible language-code constraints. Migration 0003 copies every existing
revision's available language text/options/explanation into a translation and fills
master working answers from current revisions. No master/revision/paper IDs or
publication pointers are changed; old difficulty source metadata remains in audit
without guessing a new classification. Existing independent-language masters are
preserved rather than automatically merged. Original migrations are unchanged.

Previous Year and General solutions use a shared, escaped, responsive translation
component: side-by-side when space allows, stacked on mobile. Queries prefetch
revision translations; General language filters match any approved translation.
Question Admin can inspect immutable translations under a revision.

As explicitly requested, `/mock-tests/preview/` and
`/mock-tests/preview/<question_id>/` offer authenticated previews of published
questions and available translations. They show no answer keys or solutions and
create no attempt, timer, scoring or saved responses. The mock engine remains a
future module; the same translation component can be reused by it.
