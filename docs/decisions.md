# Architecture Decisions - Status and Historical Summary

Consolidated against current source on 2026-11-12. This is not a new feature approval.
Older entries are summarized below with their supersession status; source overrides prose.
For implementation detail use [architecture](architecture.md), [database design](database-design.md)
and [MODULE_MAP](MODULE_MAP.md), rather than reconstructing behavior from milestone order.

## Current interpretation of superseded decisions

| Earlier description | Current interpretation / reference |
|---|---|
| Foundation/eight apps only | Ten domain apps are implemented, including General collections and Revision |
| English/Bengali are independent Questions | D23: one master with revision-bound translations; no legacy identity merging |
| Mandatory Part -> Module -> Chapter chain | Optional immediate parents and stable codes; see flexible-taxonomy.md |
| One Topic per Question | Multiple same-Subject tags with one matching legacy primary pointer |
| Imports deferred / all file hashes globally unique | CSV/XLSX imports implemented; file uniqueness is contextual; source-ID merging remains undefined |
| Explicit-existing-taxonomy only | Missing named child nodes can be proposed/persisted under existing Subjects; ambiguity still blocks import |
| PracticeResponse target / subject-topic setup | PracticeQuestion is the response model; current setup is module then difficulty |
| Profile is the learning dashboard | Profile is account details; Learning Space is the activity dashboard |
| Revision sessions and topic exploration are future work | Both are implemented; Revision reuses Practice; topic-card controls were later removed |
| Mobile API sample payloads/routes | Proposals only; existing session-auth JSON endpoints are not a general mobile API |

## Numbered decisions retained for reference

These IDs identify the historical decision record. Status describes how to read each
entry now, not a claim that every original sentence remains current.

| ID | Historical choice and rationale retained | Current status / qualification |
|---|---|---|
| D01 | Modular Django/ORM/PostgreSQL monolith sharing a Question Bank | Architecture retained; original eight-app count superseded by ten apps |
| D02 | Django Templates/Admin, CSS and vanilla JS; avoid an unnecessary SPA/service stack | Retained; compiled Tailwind and scoped styles are implemented |
| D03 | Custom AbstractUser before initial migrations | Retained as accounts.User |
| D04 | Public Previous-Year browsing | Retained for valid published papers and approved revisions |
| D05 | Authenticated Mock/Practice ownership with CSRF/safe redirects | Retained; Revision also requires authentication |
| D06 | Mock section configuration chooses en/bn/mixed; no student mock-language selector | Retained; mixed selection does not promise fixed language proportions |
| D07 | Independent English/Bengali masters; no translation grouping | Superseded by D23; primary language compatibility fields remain immutable within a master lineage |
| D08 | Versioned exam patterns control totals, duration, sections and marking | Implemented with activation/availability checks; later detailed selection rules extend distribution |
| D09 | Published revision and used-pattern history must remain stable | Retained and strengthened: revision content is append-only even while draft |
| D10 | Persist fixed attempt question/revision/order/marks; score and enforce deadlines on server | Implemented by AttemptQuestion and execution services |
| D11 | Preserve historical completed attempts/results absent an approved retention policy | Retained through protected history/write services |
| D12 | Practice reuses published masters with persistence and immediate feedback | Implemented; current UI is module/difficulty and the engine also serves Revision |
| D13 | Imports create drafts, validate/revalidate and confirm atomically with audit | Implemented; source metadata never substitutes for editorial approval |
| D14 | Explicit mappings, duplicate prevention and preserved source metadata | Clarified by D20/D21 and later taxonomy creation: contextual hashes, no fuzzy identity merge |
| D15 | Foreign keys, unique/check constraints and transactional cross-row validation | Implemented with model guards plus PostgreSQL triggers; inspect actual migrations |
| D16 | Implement domain models incrementally by milestone | Historical sequencing only; not evidence that current apps are still skeletons |
| D17 | Separate working/published pointers and permanent publication marker | Implemented; new drafts do not replace live content until explicit review/publication |
| D18 | Normalize paper identity; derive master FK; retain historical approved revision associations | Implemented with protected publication/editing and paper/master/order/number constraints |
| D19 | Defer import and source-scoped identity merging at the early paper milestone | Import deferral superseded; no automatic source-ID merge key has since been introduced |
| D20 | Release staged draft CSV/XLSX ingestion with audit and controlled draft paper attachment | Implemented; its global file-hash rule is superseded by D21 contextual uniqueness |
| D21 | Unified Previous-Year/General modes, canonical context and row/default precedence | Implemented; later language inference, named-child creation and D23 extend normalization |
| D22 | Dedicated General Questions app reusing ImportBatch audit | Implemented by GeneralQuestionBatch proxy; no duplicate Question/collection storage |
| D23 | One multilingual master with immutable revision-bound language content | Implemented; pairing is explicit and source-local, not a cross-paper merge operation |
| D24 (paper administration) | Optional duration/marks/instructions/Subject/declared master count on existing paper models | Implemented; mixed papers leave Subject blank, publication checks declared counts |
| D24 (wide imports) | Ingest bilingual extraction columns and audit aliases/metadata | Implemented; no PDF/OCR/AI execution or handwritten-mark answer inference |
| D25 | Validate/activate versioned Mock patterns and effective section marking | Implemented; deactivate before permitted edits, version instead of mutating used configuration |
| D26 | Fixed persisted attempts and repeat-start safety | Implemented; starts/resumes preserve owner snapshots and question identity uniqueness |
| D27 | Server-authoritative timing/autosave/finalization/scoring | Implemented; version conflicts and latest-token retries retain their existing contracts |
| D28 | Untimed persistent Practice with locked immediate feedback | Implemented; PracticeQuestion replaces the proposed PracticeResponse; later Revision scope extends the same table |
| D29 | Public direct-answer and temporary Previous-Year practice modes | Implemented; reader practice is distinct from persistent Practice/Revision sessions |

The historical record used D24 twice. Both descriptive labels above preserve that
fact; references to D24 must state whether they mean paper administration or wide imports.
No decision IDs were silently reassigned.

## Later implementation refinements without numbered ADRs

- Flexible taxonomy: Subject anchors, optional immediate parents, stable codes and guarded
  same-Subject Topic moves. See [flexible taxonomy](flexible-taxonomy.md).
- Topic tags: QuestionTopic, explicit primary pointer compatibility and deferred integrity
  triggers. See [multi-topic questions](multi-topic-questions.md).
- Advanced Mock selection: exact-one-scope rules, difficulty quotas and manual selections;
  allocation deduplicates globally. See [selection rules](mock-selection-rules.md).
- Import hierarchy: preview stages named child nodes; confirmation creates them atomically.
  Subjects remain administrator-managed. See [import contract](import-contract.md).
- Practice setup: eligible module cards then published difficulty; legacy service-level
  filters/counts remain. See [Practice setup](practice-taxonomy.md).
- Account pages: Profile holds account details; Learning Space holds activity/statistics.
- Revision: personal notes/mastery, reusable Practice-kind snapshots, first-answer review
  counting and immutable session results. See [Revision Bank](saved-questions.md).
- Topic exploration: registered-user published discovery with open-mock scope protection;
  per-question controls were subsequently removed while routes remain available.
- Bookmark UI: checkbox-style Save for revision control, specific submit-button reset,
  and disabled success announcements. These are presentation changes, not scoring changes.

This section records observed implementation, not retroactive approval dates or new scope.

## Boundaries still unresolved or proposed

- source_question_id is optional/non-global; an automatic source-identity merge policy is
  not implemented. File/context duplicate protection does not define such a policy.
- The mobile route/payload/authentication examples in mobile-readiness.md are proposals.
- External scheduling for expiry/cleanup commands and actual deployment configuration
  are not established by these documents.
- AI/external educational content, subscription/payment flows and general mobile token
  APIs are not implied by existing extraction columns or published discovery services.

## Future decision recording

Record a new decision only when the task actually changes an architectural boundary,
interface, schema or policy. Include the source/task reference, rationale, compatibility
impact and exact superseded entry. Distinguish source-confirmed behavior, historical
rationale and proposals; do not manufacture an approval date or use old milestone text
as a blanket requirement to pause ordinary authorized work.
