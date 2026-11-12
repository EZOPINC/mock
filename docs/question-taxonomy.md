# Shared Question Taxonomy - Current Reference

Use [flexible taxonomy](flexible-taxonomy.md) for exact parent/code rules and
[multi-topic questions](multi-topic-questions.md) for primary/secondary tag integrity.
This replaces the original mandatory-chain diagram, superseded by optional parents.

## Stored academic paths

| Node | Subject anchor | Permitted immediate parent |
|---|---|---|
| Subject | Itself | None |
| Part | Required | Subject |
| Module | Required/derived | Subject or Part |
| Chapter | Required/derived | Subject, Part or Module |
| Topic | Required/derived | Subject, Part, Module or Chapter |

Skipped levels follow real stored foreign keys; do not synthesize empty parent records.
Stable codes identify nodes; names/slugs are scoped to their actual parent. Existing
ancestry/code changes are guarded. A Topic may move within the same existing Subject
under the applicable model/database rules; this does not rewrite historical sessions.

## Question and exam membership

Question has one Subject, an intentional legacy primary Topic pointer, and zero or
more QuestionTopic tags. All tags share Subject; classified questions require one
primary matching the legacy pointer. Use questions.tagging.set_question_topics so
the pointer/tag set and deferred transaction checks remain coherent.

QuestionExam provides many-exam membership independently of the shared taxonomy.
Do not place Subjects/Parts/Modules under an Exam or duplicate masters per language,
exam or secondary tag. Descendant filters use any-tag matching and master deduplication.
The optional topic_id argument in the shared legacy eligibility service still means
primary Topic; do not silently change that interface when adding any-tag discovery.

## Discovery and compatibility

- PracticeTaxonomy builds eligible descendant pools; current UI chooses Module then difficulty.
- Mock detailed selection rules, Revision bank filters and exploration support skipped levels.
- Explore Topic routes can display stored paths/codes; per-question controls were removed.
- Import may propose/create missing named child nodes under an existing Subject at confirmation.
- Subject creation remains explicit administration; ambiguous names/codes are not guessed.
- Frozen paper/attempt/session revisions and classification labels remain historical.

Start with exams/models.py, questions/tagging.py and the relevant selector from MODULE_MAP.md.
Use exams.test_flexible_taxonomy and questions.test_topic_tags for targeted integrity work.
No application/data migration or tests were run for this documentation consolidation.
