# UI Phase 1.1 - compiled Tailwind foundation

## Build and static assets

Tailwind CSS 4.3.5 uses the official standalone CLI. There is no Node/npm,
Django plugin, CDN runtime, external font request or added Python dependency.
`tools/tailwind-lock.json` pins compiler assets and SHA-256 digests from the
[official release](https://github.com/tailwindlabs/tailwindcss/releases/tag/v4.3.5).
The build helper downloads the platform-specific compiler into ignored `.tools/`
on its first run and verifies its checksum before every invocation.

```text
python tools/build_css.py
python tools/build_css.py --watch
python tools/build_css.py --check
python manage.py collectstatic --noinput
```

The first build requires network access to GitHub; later builds use the verified
cache. Watch runs in the foreground. Check builds to a temporary file and fails
if the generated asset is stale. Input is `assets/tailwind.css`; minified output
is `static/css/tailwind.css`. Keep the generated asset with the project so Django
can serve and collect it without installing a compiler at runtime. Do not hand-edit
output; edit the source/shared templates and rebuild. No Django setting changes
are required: the existing static directory and STATIC_ROOT already support it.

See the official [CLI instructions](https://tailwindcss.com/docs/installation/tailwind-cli)
and [Preflight documentation](https://tailwindcss.com/docs/preflight).

## Design tokens

CSS-first `@theme` configuration defines these reusable tokens:

| Area | Foundation |
|---|---|
| Colors | brand-900 navy #142d45, brand-950 #0d2135, accent-600 teal #087f79, accent-700 #06665f, accent-50 #e8f5f1 |
| Surfaces/text | canvas #f7f9fb, surface white, ink #20364c, muted #5c6d7c, line #dce4e9, danger #a62636 |
| Typography | system sans, Segoe UI, Nirmala UI and Vrinda for English/Bengali; no font downloads |
| Spacing | 0.25rem scale, 1-1.5rem responsive horizontal gutters, 76rem content width |
| Components | rounded cards, subtle shadows, navy primary/white secondary buttons, accessible inputs and focus outlines |
| Breakpoints | sm 40rem, md 48rem, lg 64rem, nav 70.01rem, xl 80rem; default 2xl 96rem remains available |

## Migration boundaries

Only base.html and shared components opt into the new ui-* styles. Existing
semantic classes, IDs, URL names, CSRF fields, aria state, menu/profile hooks,
message tags and JavaScript remain. Tailwind utilities use the `tw:` prefix;
write complete literal classes (for example `tw:text-accent-700`) so the template
scanner can discover them. All templates are scanned; no app pages are redesigned.

The stylesheet order is legacy `site.css`, compiled `tailwind.css`, then the page's
existing extra_head assets. Legacy CSS is kept intact and remains the fallback if
the new stylesheet is unavailable. Preflight is deliberately omitted, avoiding a
global reset of question layouts, native forms or existing app pages.

Legacy CSS is unlayered, so layered utilities cannot reliably override it. Opt-in
ui-* component rules are intentionally unlayered and generated with Tailwind @apply;
they win by normal specificity/order while leaving unconverted selectors alone.
Avoid important/global overrides. Shared form rules exclude hidden inputs and
size checkboxes/radios separately. The hidden attribute remains controlled by
existing CSS/JavaScript, preserving the mobile menu and progressive navigation.

The nav breakpoint matches the existing navigation.js max-width 70rem behavior.
No business logic, models, migrations or backend settings changed. Further UI
phases are outside this implementation.

## Verification

Run `python manage.py test core.test_navigation accounts --noinput`, Django check,
build --check and collectstatic. Headless desktop/mobile checks verified compiled
styles, all module links, touch/keyboard menu behavior and no horizontal overflow.

## UI Phase 1.2 - homepage and navigation

The homepage now has a server-rendered hero and learning-path links, active exam
categories, four learning modules and a practice CTA. Category names and exam links
continue to come from core.home's existing filtered/prefetched data; no counts or
sample exam records are invented. General Questions remains beside Mock Tests,
Practice and Previous-Year Papers. The page retains one descriptive h1 and a
product-specific document title. All destinations remain existing Django URL names.

A shared inline SVG component supplies decorative book, clock, pencil, category,
arrow and menu icons without external requests. Visible text provides accessible
link/button names. Shared cards, header/footer, CTAs and breadcrumb styling use the
Phase 1.1 palette and scoped compiled Tailwind styles. Existing semantic selectors,
legacy CSS fallback and JavaScript hooks are preserved. Hover movement is subtle,
limited to hover-capable devices and disabled for reduced-motion preferences.

The primary-navigation ID, menu-toggle button, aria-expanded/controls, native account
disclosure and POST/CSRF logout remain. Navigation.js continues to control the 70rem
mobile breakpoint, outside-click/Escape closing and focus restoration. Without
JavaScript, navigation links remain visible. Expanded mobile navigation can scroll
within the viewport. No backend, model, URL, authentication or settings changes.

Responsive cards use four columns on wide homepages, two below the navigation
breakpoint and one below 40rem. The hero stacks below 48rem. Footer links wrap into
two columns and then one. Breadcrumbs wrap long exam/paper names and mark the
current location. Previous-year separators use the same decorative chevron icon.

Validation: scoped core/accounts PostgreSQL tests, compiled CSS --check, Django
check and collectstatic; headless desktop/mobile checks for guests and signed-in
staff navigation, layout overflow, icons, module links, Escape and outside-click.
Further UI phases are outside this implementation.

## UI Phase 1.3 - exam discovery and previous-year papers

Exam Category -> Exam -> Year -> Mode/Paper continues using the existing views,
querysets, publication filters and URLs. Discovery pages add responsive cards,
icon breadcrumbs, stage/session chips and styled paper/subject controls. The
new discovery_filter shared component and discovery-filter.js provide progressive
text matching over cards already rendered on the page. This makes no network
requests or query changes and never reorders records. Without JavaScript the
search control stays hidden and every server-rendered card/link remains available.
Existing stage/session/paper/subject links and forms still work normally.

Paper templates opt into ui-paper-reader styling: clear original question numbers,
compact summary and filter panels, a question palette, readable multiline options,
and larger explanation text. Scoped option layout avoids flex-splitting text at
line breaks; original content, math symbols, A-D order and numbering are untouched.
At desktop widths bilingual panels use equal columns; tablets/mobile stack them
in their existing English-first order. A single translation remains full width.
Native solution disclosures, Direct Answers highlights and Practice Paper POST
feedback retain their existing behavior and JavaScript hooks. This phase does
not add keys to unanswered practice questions or introduce saved paper attempts.

Assets are compiled through the same pinned standalone build and collectstatic.
No models, views, services, querysets, URL definitions, eligibility or publication
logic changed. Validation covers exams/previous_year/navigation PostgreSQL tests,
compiled CSS checks, Django checks, collectstatic, plus headless desktop/mobile
search/clear/empty filtering, bilingual/monolingual columns, numbering and feedback.

## UI Phase 1.4 - focused mock-test execution screen

The persisted all-question scrolling layout remains. The attempt template now uses
optional base.html body/header/footer blocks to replace the full site navigation
with an exam heading and Exit to Mock Tests link. Other pages retain the default
header/footer. Unsaved-change leave protection is unchanged.

A sticky status bar keeps the server-driven timer, active question counter, answer
progress, save/retry status and palette access visible while scrolling, including
on mobile. A ResizeObserver measures its height so question jumps and sticky sidebar
navigation stay below it. The desktop palette is grouped by frozen sections; on
compact screens a native details disclosure opens/closes the same palette. A native
section selector jumps through the existing position-saving navigation path.

Palette states combine accessible colors with check/review/unanswered symbols,
explicit aria-labels and aria-current. Progress counts current local choices;
the visible save status remains the authority for whether changes reached the
server. Answer and review controls retain their original input names and hooks.
The sticky action bar provides bounded Previous/Next and the existing Review and
submit link, which still waits for queued saves and opens server confirmation.

Question cards, selected options and legends use compiled Tailwind design tokens.
Bilingual translations remain side by side on desktop and stack on mobile; a
single translation uses full width. Original text and option ordering are unchanged.
The timer remains server-authoritative. No keys or explanations are added to active
attempt HTML. API URLs, JSON payloads, version/token retries, deadline behavior,
question selection, scoring and submission services are untouched.

Changed assets: mock_tests/attempt.html, optional shell blocks in base.html,
mock-test.js presentation controls, mock-test.css fallback, Tailwind source/output.
Validation: scoped mock-test and shared-navigation PostgreSQL tests, CSS --check,
Django check, collectstatic and desktop/mobile interaction checks for sticky timer,
progress, palette, section/step navigation, existing save/clear and submit placement.
No backend, settings, models, migrations or later UI phases are included.

## UI Phase 1.5 - practice configuration, sessions and summary

Practice templates opt into the compiled ui-practice theme, reusing foundation
cards, buttons, icons, progress meters and the mock screen's selected-option and
palette visual patterns. Native POST forms remain separate from mock autosave;
there is no new answer-saving endpoint or grading JavaScript.

Configuration groups topic/count inputs beside available-topic information and
plain workflow guidance. The hidden start token, field names, CSRF and server-side
validation are unchanged. Practice remains untimed. Session pages render exactly
one question and use existing question query parameters for Previous/Next, skipping
and palette links. Added fragments and practice-ui.js focus/scroll only affect
presentation. Compact palettes use a native collapsible disclosure; without
JavaScript all existing links and forms continue to work.

Progress displays total/answered/correct/incorrect/remaining, accuracy and a native
accessible progress meter using existing server-provided values. Palette colors
have explicit correct/incorrect symbols, labels and current-question semantics.
Selecting a radio changes only its visual treatment until Submit. Submitted
responses show a correct/incorrect banner, selected answer and lock notice. Correct
options and available explanations are revealed by the existing conditional shared
translation template only after submission. A wrong submitted option is styled
using the server's existing feedback flag, not a client-side answer-key comparison.

English/Bengali panels remain side by side on desktop and stack on mobile. Long
multiline options use block text with positioned letter markers for readability.
The summary reuses progress and adds subject/topic performance cards and review
links, including resume when still In Progress. Abandonment keeps its existing
POST confirmation and offers a clear return path. No question text is loaded for
other questions by the session template, and unanswered closed-session questions
still reveal no solutions.

No views, services, models, queries, scoring, answer locks, session ownership, URLs
or persistence contracts changed. Validation: scoped Practice PostgreSQL tests,
final view checks, desktop/mobile UI checks, Django check, reproducible compiled
CSS and collectstatic. Further UI/backend phases are outside this implementation.

## UI Phase 1.6 - student dashboard and authentication

The existing /accounts/profile/ route now serves a learning dashboard while retaining
read-only username, email and account-created details. Login defaults and navigation
continue to use the same Profile URL. No new account route or management action exists.

accounts/dashboard.py is a small read-only data adapter used by ProfileView context.
It scopes every query to request.user, reads existing MockAttempt, PracticeSession
and PracticeQuestion rows, and caps each recent list at five items. Aggregates show
stored finalized mock counts, completed/open practice counts, and accuracy derived
from saved practice correctness flags. Recent rows count master response records,
not language translations. Cards use frozen configuration labels, stored mock
scores and existing owned resume/results/summary links; mock and practice scores
are never combined. Dashboard reads do not finalize overdue attempts or mutate
learning records. Opening an attempt still uses the existing deadline services.

No-history states display honest zeros and no accuracy until a practice answer has
been submitted. Native progress bars have labels and captions; empty progress uses
a valid maximum without claiming completed activity. Private account values remain
inside the authenticated, no-store Profile view. Query-string user IDs are ignored.

Login and registration retain native Django forms, CSRF, field names, password
validation, safe next handling, session behavior and messages. Templates use the
existing Tailwind form/card/button/icon tokens and readable help/error sections.
The form precedes its supporting copy in DOM order and appears first on mobile.
Shared message styles distinguish success, error, warning and information with
icons plus text; field errors retain their IDs and add alert semantics. No Google
Sign-In, password reset/editing, third-party identity provider, remember-me control,
model/migration or new dependency is introduced.

Validation: authentication/navigation regression checks and dashboard tests for
owner isolation, bounded lists, SELECT-only reads, progress/resume/result links,
bilingual master counts and form errors. Desktop/mobile browser checks cover
populated/empty dashboards, native forms, validation states and overflow. Django
check, migration dry check, compiled CSS --check and collectstatic complete the phase.

## UI Phase 1.7 - custom administration and cleanup

Custom import and General Question review pages now share scoped Tailwind styling.
Existing staging, validation, approval and publication behavior is preserved.
See [UI migration summary](ui-migration-summary.md) for completed phases, CSS
cleanup scope, responsive checks and regression results.

