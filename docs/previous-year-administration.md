# Previous-year models and administration — Milestone 3.1 completion

The repository already has PreviousYearPaper, PaperQuestion, multilingual revision
snapshots, publication services and a public viewer. This milestone reuses those
structures and adds only missing administrative configuration. Existing public
navigation and mock preview are unchanged; no new public or mock functionality.

## Paper identity and associations

Exam → optional Stage → Year → Paper uses the existing normalized identity across
Exam/Stage/Year/Name/Part/Session. Stage must belong to Exam. PaperQuestion retains
the original string question_number, positive display_order, master Question and
exact immutable QuestionRevision. Numbers, order and master identity are unique
within a paper. The same master/revision may appear in multiple papers without
copying question or translation records. All existing protection and multilingual
review/publication rules remain in effect.

## Optional configuration

| Field | Meaning / validation |
|---|---|
| duration_minutes | Positive integer when specified; blank otherwise |
| total_marks | Decimal with two places, zero or greater; no scoring engine or per-question marks are inferred |
| instructions | Optional plain Unicode/multiline text, retained unchanged |
| subject | Optional protected Subject; blank allows mixed-subject papers, otherwise every linked Question must match |
| expected_question_count | Optional positive number of master questions, not language rows |

Actual count is derived from PaperQuestion rather than stored twice. Draft papers
may have fewer questions than expected while being assembled. They cannot exceed
the declared count, and publication requires an exact match when one is specified.
Without a declared count, the existing nonempty-paper rule remains. Remove excess
associations before lowering an expected count below the current total.

Paper and row saves retain their parent-row locking and validated write paths.
Publication locks the paper, validates the complete association set and declared
count, and only then changes status. Existing bulk-write guards and PROTECT
relationships remain. Optional subject is checked for manual and import-draft
associations; import preview also reports subject/capacity conflicts before writes.

## Django Admin

Open Previous Year → Previous year papers. The form groups paper identity,
optional configuration and publication status; questions are managed inline using
existing Question Bank revisions. Actual/expected count appears in the form and
list. Filters include Authority, Exam, Stage, Year, Subject and publication status.

Inspect the complete paper, then explicitly publish it. Published metadata and
associations stay read-only until unpublication. No language records are copied,
and adding a translation or publishing a new Question revision never replaces an
existing paper association automatically.

Migration `previous_year.0002_previousyearpaper_duration_minutes_and_more` adds
five optional fields and database checks for duration, marks and expected count.
Existing papers receive blank configuration without guessed metadata. Earlier
migrations, IDs, associations, publication flags and original numbering remain
unchanged. No additional models or parallel paper hierarchy are introduced.
