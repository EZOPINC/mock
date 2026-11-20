# Historical General Questions screenshots

These captures document the original translation inspection layout. See the [current staff workspace](../../question-workspace.md) for navigation and review.

General collection and staff batch review reuse the Previous-Year reading style.
English stays in the left column and Bengali in the right at desktop widths.
Missing editions retain empty question, option and explanation slots. On phones,
the labeled slots stack in English/Bengali order, including the empty slot.
The revision's available languages are listed on each question card.

This is an opt-in shared-template mode: other readers keep their existing
single-language full-width behavior. Public collections retain published revisions,
filters and pagination. Staff review retains working revisions and signed actions.
No data, translation, publication, permissions or question links are modified.

Screenshots: [Desktop](collection-desktop.png), [360 px](collection-mobile.png).
The Edge check uses an isolated test database with English-only, Bengali-only and
bilingual records. It verifies the reserved columns, empty stems, no horizontal
overflow and solution disclosure. General Questions' 17 tests and the 12
previous-year mode tests passed; Tailwind build/check and diff checks passed.
