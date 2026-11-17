# Design system — UI-1 through UI-3

The shared shell and homepage belong to `core`; shared includes live in
`templates/components/`. Learning interfaces are owned by Mock Tests, Practice,
Previous-Year and Revision; their domain workflows remain unchanged.

## Tokens and build

`assets/shell.css` adds the membership shell: navy navigation/footer, cobalt actions,
responsive home/account layouts and plan/checkout cards. Its `--app-*` tokens
support light, dark and sepia independently of the existing learning `--ui-*`
tokens. Question, answer and timer components retain their existing presentation.
The shared header/footer expose Plans and pricing; purchase forms use the existing
server-side checkout route and remain unavailable when checkout is disabled.
Registration uses explicit labels, empty fields and new-password autocomplete;
password validation remains Django-owned.

Mock/Practice discovery and setup plus Previous-Year catalogue surfaces reuse the
shell palette through scoped `.mock-hub` / `.ui-discovery` tokens. The shared
`components/module_access_note.html` renders access guidance and the pricing link;
Practice supplies `free_session_size`. Assessment readers retain learning tokens.
The module browser check in `tools/verify_membership_ui.py` captures populated
discovery/setup pages under `docs/screenshots/modules/` at desktop/mobile widths.

Run `python manage.py test core.test_membership_ui --noinput` for presentation
contracts. On Windows with Edge, run `python manage.py test tools.verify_membership_ui
--noinput` for desktop/mobile layout, navigation and theme checks against disposable
test data. Captures go to `docs/screenshots/membership/`.

`assets/design-system.css` defines semantic `--ui-*` tokens and is imported by
`assets/tailwind.css`. Run `python tools/build_css.py`; commit generated
`static/css/tailwind.css`. The existing prefixed Tailwind utilities remain available.

Use canvas for warm off-white / charcoal / sepia page backgrounds, surface for
cards, soft for structure, ink/muted for text, line for borders, accent/hover/tint
for deep teal actions, and on-accent for button labels. Keep most surfaces neutral;
reserve green/red for correctness feedback. Avoid gradients and heavy shadows.
Spacing uses 4, 8, 12, 16, 24, 32 and 48px tokens; controls use .65rem radii,
cards 1rem, and keyboard focus a 3px ring with 4px offset.

## Appearance and typography

`static/js/theme.js` applies light/dark system preference before styles paint.
The header offers System, Light, Dark and Sepia; explicit preferences persist in
localStorage (`mock-exam-theme`). Storage failures fall back to in-memory selection;
system changes and cross-tab updates are supported. Header and Profile selectors
stay synchronized; storage failure announces that the selection applies only to
the current page. Without JavaScript, selectors are disabled, CSS follows the
system and navigation remains visible. No account preference model is needed.

Use system fonts with local Noto Sans Bengali, Nirmala UI and Vrinda fallbacks.
The document is English; Bengali passages must use `lang="bn"`. Bengali line
height is 1.9 with normal letter spacing. No fonts or assets load from a CDN.

## Components

- Actions: `.button.button-primary` or `.button.button-secondary`; use real links
  for navigation, buttons for actions. Keep labels explicit and targets >=44px.
- Forms: reuse `components/form_fields.html` and `.ui-form-field`; retain visible
  labels, help text and server errors. Never remove CSRF or form validation.
- Cards: `.ui-card`, `authority_cards.html`, `module_cards.html`; exam links continue
  through category → exam → Mock / Practice / Previous Year.
- Navigation: `header.html` uses native disclosures and existing mobile toggle;
  `navigation.js` preserves keyboard Escape and focus return. Breadcrumbs use
  `nav.breadcrumbs`, `aria-label="Breadcrumb"` and `aria-current="page"`.
- Badges: `.badge`, `.badge-live`, `.badge-outline`; availability is neutral/teal,
  always with text. Do not communicate status by color alone.
- Alerts: reuse `messages.html` for Django messages; `.ui-alert` for contextual
  information. Confirmation helper `confirmation_dialog.html` takes dialog_id,
  title, description, action and confirm_label prefixed with `dialog_` (the label
  is `dialog_confirm_label`). A feature-owned trigger calls `showModal()`; native
  dialog provides focus containment and Escape. It is not wired into exam flows.
- Empty/loading: `empty_state.html` and `loading.html` (`loading_label`). Put
  `aria-busy` on the updating region when integrating asynchronous content.

Motion respects `prefers-reduced-motion`. Resume access on the homepage goes to
the existing authenticated Learning Space; no new session queries or data exposure.
Feature fallback styles remain in place; UI-2 applies the semantic learning layer
described below over them.

## Learning and examination — UI-2

`assets/learning.css` is compiled through the same Tailwind entry point. The base
template applies `.learning-ui` only to Mock Tests, Practice, Previous-Year and
Revision and General Questions routes. This layer covers discovery, setup, sessions, results and review
without replacing feature interaction scripts or server workflows.

Use `questions/reading_question.html` for paired stems and options; each answer
choice has one native radio, shared by both translations. Columns stack at tablet
widths (1024px and below). Keep language attributes, 56px option targets and visible
selected labels. Practice and Revision both render `practice/reading_panel.html`;
Revision retains its AJAX form hook and native POST fallback. Saved-question detail
and topic exploration use the shared reader and the existing guarded
`previous_year/reading_solutions.html` include (a presentation dependency only).

Correct/incorrect tokens are `--ui-correct`, `--ui-incorrect` and their `-bg`
surfaces. They apply only to feedback/review markup rendered after the existing
reveal boundary. Selection/answered states use teal; review marks use muted amber
plus `!`, checked answers use a tick, and current questions retain an outline.
Never put answer keys, solution text or correctness attributes into an active mock.

The mock timer/status toolbar and action bar retain their sticky behavior and
existing JS hooks. “Save & Next” uses the existing automatic save queue and
navigation path; it does not imply offline persistence or a new save algorithm.
Students can inspect the save status, retry, and review before final submission.
Accuracy on mock results uses correct / attempted counts, distinct from marks %.
Revision bookmarks announce successful changes through their existing live region.

Targeted module tests cover confidentiality, selection persistence, answer locking
and historical snapshots. `tools/verify_learning_ui.py` adds opt-in Edge journeys
for the shared reader, theme surfaces and bilingual Revision answer boundary; its
module docstring gives the three explicit test names. Screenshots from those journeys
are temporary and leave the existing committed captures unchanged.

## Account, accessibility and performance — UI-3

`assets/student.css` completes tokens on account, public catalogue, error and form
surfaces. `--ui-control-line` distinguishes interactive control boundaries from
decorative card borders. Use semantic headings, visible labels and text/icon
status alongside color. Focus rings use the theme's focus token; forced-colors
mode uses the system highlight. Reduced motion disables component transitions.

Profile exposes the existing browser-local display preference. There is no
account-level language model: the language guidance links to existing Practice
setup and explains that mock languages follow the pattern. Do not add a setting
that appears to save unsupported account preferences.

Learning Space uses existing owner-scoped aggregates, five recent records per
module, two unfinished records per module, and `revision.selectors.bank_counts`.
The data helper performs eight fixed read queries (formerly five); normal rendered
requests use ten including session/authentication. Added reads provide resume
records independently of recent completed activity and saved-question counts;
rendering cards adds no per-record queries. Revision sessions remain excluded
from ordinary Practice totals. No recommendation, streak or ranking is inferred.

The initial script marks enhanced pages before styles paint. Mobile navigation
reserves its collapsed layout until initialized; no-JS navigation stays visible.
Appearance selectors reserve their space while disabled. Short/zoomed examination
viewports put the status toolbar into normal flow and retain a compact fixed timer
with sticky bottom actions. Timer, save and scoring code are unchanged.

Shared fallback CSS remains necessary for existing feature pages. Safe cleanup
removed unreferenced historical hero rules, the unused mock-language script and
duplicate account-menu listeners. Shared question/password JS now loads only on
routes using it; bookmark CSS loads only on learning routes. The exam page omits
the unused global navigation script. Tailwind still scans explicit templates and
uses the pinned minifying standalone compiler; generated CSS is never hand-edited.

Generic 403/404/500 templates preserve HTTP status and omit exception details;
their recovery links do not promise that unsaved work has persisted.

`tools/verify_student_ui.py` checks account/catalogue themes, labels, sampled text
contrast ≥4.5:1, control boundaries ≥3:1, focus, reduced motion, storage failure,
200%-equivalent reflow, CLS and local asset budgets using disposable data.
This is targeted accessibility evidence, not a WCAG certification or production
performance benchmark. Complete [the manual regression checklist](UI_REGRESSION_CHECKLIST.md)
for real screen readers, browser zoom and additional browser engines.

Local asset measurements (gzip estimates, not verified production transfer sizes):

| Check | UI-2 baseline | UI-3 |
|---|---:|---:|
| Minified Tailwind bytes | 175,662 | 175,151 |
| Tailwind gzip bytes | 23,082 | 22,938 |
| Homepage shared CSS/JS requests | 6 | 4 |
| Homepage shared assets, gzip bytes | 30,787 | 29,013 |

The initial browser audit found CLS 0.128; after reserving navigation/preference
space, repeated 45-case theme/viewport audits observed maximum CLS 0.000–0.059.
Local resource durations stayed within the test budget; production latency,
compression/cache policy and field Web Vitals remain deployment measurements.
