# Mock selection rules — Phase D4

## Configuration

`ExamPatternSection` may have ordered `SectionSelectionRule` records. Each rule
has exactly one Subject, Part, Module, Chapter or Topic filter, a positive question
quota, optional difficulty and random/manual selection mode. Rule quotas must sum
to the section's question count. Without rules, existing section filters continue
to apply unchanged.

Detailed rules replace section Subject/Topic filters; section language eligibility
and marking rules still apply. Subject includes its unclassified questions. Other
nodes include descendant topics through every supported optional parent path.
Both primary and secondary topic tags match; translations count as one master
question.

Difficulty uses the **published revision**, compared case-insensitively after
trimming whitespace. Blank configuration means any difficulty. `unspecified`
matches blank or literal `unspecified`; unknown historical values match only
the unrestricted setting. No question or revision values are rewritten.

## Administration

1. Create or edit an unused Draft/Inactive pattern and its sections.
2. Open a section using its change link and add ordered rules inline.
3. For a manual rule, open its change page and select exactly its quota of
   questions, with explicit order. The question lookup uses existing Question
   Admin search/filter tools; submitted IDs are checked against rule eligibility.
4. Review eligible counts, section messages and overall pattern validation.
   Activate explicitly using the existing pattern action.

Active or previously used patterns cannot change rules or manual selections.
Deactivate an unused pattern to edit; create a new pattern version after use.
Taxonomy fields use autocomplete; manual selection uses a lookup rather than
rendering the whole Question Bank. Candidate queries are scoped by exam and rule.

## Allocation and integrity

Existing publication, verified-answer, complete-option and language checks remain
authoritative. Manual selections must be distinct across the entire pattern and
are reserved before random allocation. The existing maximum-flow allocator checks
and fills overlapping random pools globally, including legacy sections. Activation
and attempt creation reject unsatisfiable quotas rather than repeating questions.

Attempt creation remains transactional and rechecks eligibility under locks. New
attempt configuration snapshots include rule filters, quotas, modes and selected
master IDs. Existing frozen revision/content, question order and marking snapshots
remain authoritative for execution and scoring. Later retagging, taxonomy changes
or publication changes cannot alter an existing attempt.

## Migration and compatibility

`mock_tests.0006` adds `SectionSelectionRule` and `ManualRuleQuestion` tables,
foreign keys and constraints. It does not backfill rules or modify existing
patterns, questions, taxonomy, papers, practice sessions or attempts. Database
constraints enforce one taxonomy filter, valid choices, positive counts/orders,
unique rule order, and unique manual question/order within a rule. Cross-rule
eligibility and global availability are validated by transactional services.

Rolling back to `mock_tests.0005` removes the new configuration tables; export
new rules/manual selections first if they need to be retained. Existing attempt
snapshots remain self-contained JSON and their question rows are unchanged.
No endpoints, timers, scoring behavior or student templates change in this phase.
