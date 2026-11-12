# UI Foundation - Current Reference

Source-verified on 2026-11-12. This replaces duplicate phase-by-phase current-state claims.
[UI migration summary](ui-migration-summary.md) retains brief historical context; code and
[MODULE_MAP](MODULE_MAP.md) identify the current interface owners.

## Stack and build

The UI uses server-rendered Django Templates, compiled Tailwind, scoped CSS and vanilla JS.
Django Admin remains server-rendered with custom ModelAdmin/forms and feature screens.
There is no frontend framework or runtime Tailwind CDN dependency.

| File | Role |
|---|---|
| assets/tailwind.css | Editable design tokens and semantic component styles |
| tools/tailwind-lock.json | Pinned standalone compiler version/checksums |
| tools/build_css.py | Build/watch/check; downloads the compiler only when absent |
| static/css/tailwind.css | Generated minified output; never hand-edit |
| static/css/site.css | Shared fallback/base styles |
| static/css/imports.css, mock-test.css, practice.css, revision.css, paper-modes.css | Scoped feature presentation |
| static/css/bookmarks.css | Shared compact bookmark control and submit-selector overrides |

Use python tools/build_css.py after relevant source/template changes; --watch is available,
and --check compares against a temporary build. A missing compiler may require network access.
No build/install command was run as part of this documentation cleanup.

## Shared shell and current navigation

- templates/base.html loads site.css, compiled Tailwind, feature extra_head assets, then bookmarks.css.
- Header/footer/icons/messages/cards are reusable templates/components partials.
- Profile at /accounts/profile/ shows account details.
- Learning Space at /accounts/learning-space/ shows existing learning activity/statistics.
- My Revision Bank is under the My account dropdown and account-section navigation.
- Mobile menu/profile interaction uses existing ARIA/menu hooks; native links remain usable.
- No interface should silently finalize/grant access beyond its owning workflow's established rules.

## Current learning screens

| Interface | Presentation and owning files |
|---|---|
| Home/catalogue | core/views.py supplies the curated active catalogue; templates/core/home.html |
| Previous-Year reader | templates/previous_year/; direct answers or temporary practice mode, original question numbers |
| Active Mock Test | templates/mock_tests/attempt.html and static/js/mock-test.js; clock, progress, save status, review/answer controls |
| Mock results | Finalized frozen scores and bilingual review; no active-test answer-key rendering |
| Practice setup | configure.html lists Modules; difficulty.html selects a published level; no hierarchy dropdown panel |
| Practice session | Shared one-question panel, immediate locked feedback and existing summary/navigation |
| Revision Bank | Owner-scoped filters, notes/mastery, saved-state management and Start Revision/history |
| Revision session | Shared Practice markup/engine; AJAX feedback and native form fallback |
| Topic discovery | Existing protected routes/templates remain; per-question Explore Topic controls were removed |
| Staff ingestion/review | Custom import and General collection screens reuse established form/workflow permissions |

Question content/options/explanations render through templates/questions/translations.html.
Avoid language-specific duplicate master controls. Responsive layouts must retain readable
English/Bengali text, option order, progress, focus indicators and navigation.

## Bookmark and form boundaries

The shared templates/revision/bookmark.html control is a submit button styled like a
checkbox and label, matching Mark for review. It stays top-right on question cards.
The checked appearance and aria-pressed reflect bookmark state; saved/unsaved mutation
uses the R1 service, not a native mock review checkbox or attempt-save request.

Shared site styles target button[type=submit], which can outrank a bare class selector.
The specific bookmark selectors remove the outer button background/border, including hover.
Do not reintroduce pill/button styling through generic classes or a weaker reset.

static/js/bookmarks.js updates the icon/label/state independently. Its success-announcement
line is commented out for optional restoration; errors/sign-in recovery remain active.
Bookmark forms must remain outside answer forms; never nest forms or attach data-review
or answer-field names to the bookmark UI.

## JavaScript and confidentiality contracts

- Mock autosave JSON is version/token based; it must not receive bookmark events.
- Do not rename existing data-* hooks, CSRF fields, option names or endpoint URL names casually.
- Active Mock content hides answer keys/explanations; exploration guards also protect direct scopes.
- Practice uses server-authoritative feedback, enhanced by static/js/practice-ui.js.
- Revision uses static/js/revision-session.js to replace the feedback fragment after POST.
- Previous-Year paper-practice feedback is temporary; it is not a persisted Practice session.
- Small-screen CSS hides question palettes while keeping Previous/Next, summary and session actions.
- Focus, aria-live/pressed states, safe next destinations and no-JS fallback are part of compatibility.

## Verification references

Select owning view/service tests from DEVELOPMENT_RULES.md. A UI-only change does not
justify running every backend suite or changing schema. For shared Tailwind edits verify
build freshness; for behavior changes test POST/CSRF, ownership, feedback and confidentiality.
Browser/mobile visual checks are distinct from template/backend tests. Historical phase
checklists and pass counts are not current browser/runtime verification.
