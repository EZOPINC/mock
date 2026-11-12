# UI Migration Summary - Historical Context

The phase labels below summarize earlier interface work, not the current route contract.
Use [UI foundation](ui-foundation.md), [architecture](architecture.md) and [MODULE_MAP](MODULE_MAP.md)
for source-backed current behavior. This summary does not record new approvals/test passes.

| Historical phase | Interface work retained | Later qualification |
|---|---|---|
| 1.1 | Compiled Tailwind, design tokens, shared templates | Standalone compiler remains pinned; scoped styles coexist |
| 1.2 | Home/header/mobile menu/footer | Homepage catalogue is curated; account dropdown includes Revision Bank |
| 1.3 | Exam and Previous-Year discovery/reader | Direct-answer and temporary paper-practice modes are implemented |
| 1.4 | Mock clock/progress/palette presentation | Small-screen palettes are now hidden; engine/deadline behavior is separate |
| 1.5 | Persistent Practice setup/questions/summary | Setup is now module then difficulty, replacing hierarchy dropdowns |
| 1.6 | Authentication and student dashboard styling | Profile and Learning Space are separate routes; dashboard is in Learning Space |
| 1.7 | Import and General collection review styling | Existing workflow permissions/approval remain authoritative |
| 1.8 | Mobile-readiness assessment | API/authentication contracts remain proposals, not registered routes |
| R1-R3 | Bookmarks, personal bank and revision sessions | Revision reuses Practice; card bookmarks are compact checkbox-style controls |
| R4 | Topic exploration services/pages | Per-question Explore Topic actions were later removed; routes remain |

## Shared compatibility anchors

- Keep semantic classes, endpoint names, CSRF fields, data hooks and owner checks stable.
- Shared question content stays revision-bound; style changes do not rewrite content or scores.
- static/css/tailwind.css is generated from assets/tailwind.css through tools/build_css.py.
- Feature styles and bookmarks.css have intentional load/specificity requirements.
- Bookmark save/unsave is independent of Mark for review and answer/autosave semantics.
- UI/model test counts from earlier milestones are historical, not a present verification claim.

Detailed old phase checklists are intentionally consolidated into the current UI guide
to avoid scanning repeated or contradictory routing/layout descriptions.
