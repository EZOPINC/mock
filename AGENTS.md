# Codex Development Guidelines — Mock Exam Platform

## Objective
Minimize token usage while maintaining code quality, modularity, security and backward compatibility.

## Mandatory Rules

1. Work on one clearly defined task at a time.
2. Identify the owning Django app before making changes.
3. Read only files directly relevant to the task and their immediate dependencies.
4. Do not scan the entire repository unless explicitly requested or necessary to resolve a dependency.
5. Consult docs/MODULE_MAP.md to locate relevant files when available.
6. Reuse existing models, services, utilities and UI components.
7. Prefer minimal changes over broad refactoring.
8. Do not rewrite unrelated files or modify unrelated apps.
9. Preserve existing functionality, database integrity and historical records.
10. Create migrations only when schema changes require them.
11. Run targeted tests first. Expand testing only when failures or cross-module risks justify it.
12. Do not print complete source files, large diffs or verbose test logs.
13. Do not generate lengthy explanations or documentation unless requested.
14. Do not introduce dependencies or architectural changes without justification.
15. If a task requires changes beyond the agreed scope, explain the dependency before proceeding.

## Response Format

Return only:
- Changed files
- Summary of changes (maximum 5 bullets)
- Tests executed and results
- Remaining issues, if any

## Implementation Principle
Make the smallest safe change that satisfies the requirement.

## Context Management
- Treat the repository as the source of truth.
- Do not assume previous implementation phases are complete without verifying relevant code.
- Read architecture documentation only when needed.
- Update module documentation only when interfaces or responsibilities change.