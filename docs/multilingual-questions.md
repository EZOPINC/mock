# Multilingual Questions

| Record | Responsibility |
|---|---|
| `Question` | Stable identity, taxonomy, exam and private source links, working and published revision pointers |
| `QuestionRevision` | Numbered metadata including primary language, shared answer, difficulty and timestamps |
| `QuestionTranslation` | Immutable text, A-D options and explanation for one language in one revision |

The unique revision/language pair stores only editions with content. The primary language stays fixed across a question's revisions. Every edition uses the same answer letter, so equivalent options must occupy the same positions. Both creating a question and editing an edition go through `questions/services.py`.

A content edit creates a pending-review revision. Publication changes the live pointer after review. Papers, mock sets, attempts and Practice sessions keep their pinned revision IDs. The six legacy text columns were removed from `QuestionRevision` in migration `0009`. See [verification and rollback](question-translation-rollout.md).

English (`en`) and Bengali (`bn`) are configured. Future languages also need editor, reader, inference and delivery eligibility support where the code assumes English/Bengali. Adding a language code alone does not configure every workflow.

Use the [CSV contract](import-contract.md) for explicit language columns or long-row pairing. Use the [staff workspace](question-workspace.md) or Question Admin to edit and review an edition. Shared reading templates load translations for the selected revision.
