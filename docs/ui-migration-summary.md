# UI migration summary — Phases 1.1–1.7

Phase 1.8 adds a [mobile-readiness assessment and proposed API plan](mobile-readiness.md)
and reusable active exam selectors. It does not add mobile apps, APIs, token
authentication, schema changes or alter the completed Tailwind interface.

The Django server-rendered interface now uses the shared Tailwind design system.
Existing routes, permissions, publication rules, question ordering and learning
workflows remain in place. Django's built-in Admin retains its standard interface.

| Phase | Completed interface |
| --- | --- |
| 1.1 | Compiled Tailwind foundation, tokens and shared components |
| 1.2 | Homepage, header, mobile navigation, footer and calls to action |
| 1.3 | Exam discovery, previous-year paper navigation and bilingual viewer |
| 1.4 | Mock test cards, persistent timer, palette and progress presentation |
| 1.5 | Practice configuration, single-question feedback and summaries |
| 1.6 | Student dashboard and authentication forms |
| 1.7 | Custom import upload, editable preview, completion and General Question review |

## Assets and compatibility

`assets/tailwind.css` contains the design source; `static/css/tailwind.css` is
the compiled production asset. Run `python tools/build_css.py` after changing
templates or styles, and `python tools/build_css.py --check` to verify freshness.
The pinned standalone compiler needs no Node dependency or browser CDN runtime.
Both compiled and fallback styles work with Django `collectstatic`.

Legacy CSS remains during migration. Phase 1.7 removed 32 selectors (1,878 bytes)
from nine unused families after checking templates, JavaScript and Python widget
code: hero-visual, study-stack, step-number, benefit-section, benefit-grid,
profile-layout, profile-intro, profile-details and account-back. Dynamically
generated password controls and other live fallback selectors remain supported.

Custom staff styles are scoped to `.ui-admin`. Upload field hooks, catalogue data,
editable row names, staging versions, confirmation guards, CSRF tokens and signed
review snapshots remain unchanged. Review and publication remain separate actions.
No models, migrations, services, queries or approval behavior changed in Phase 1.7.

## Responsive and accessibility checks

Staff forms collapse to one column on small screens. Preview tables scroll inside
a labelled, keyboard-focusable region; visually hidden labels remain within their
cells to prevent document overflow. English/Bengali review columns stack on mobile.
Textareas use readable text size and line height. Validation states include text
labels alongside color, and existing focus indicators and semantic navigation remain.
Desktop and mobile browser checks exercised upload mode changes, taxonomy filtering,
preview dirty-state protection, error-disabled confirmation, bilingual review,
password visibility controls, homepage cards and document overflow.

## Phase 1.7 verification

- `python manage.py test imports general_question --noinput`: 83 passed.
- `python manage.py test accounts core exams.tests.TaxonomyPublicTests previous_year.test_viewer previous_year.test_modes practice.tests.PracticeViewTests mock_tests.test_execution.ExecutionViewTests --noinput`: 84 passed.
- Ten headless Edge desktop/mobile layout and JavaScript checks passed.
- `python manage.py check`: no issues.
- `python tools/build_css.py --check`: compiled CSS current.
- `python manage.py collectstatic --noinput`: successful.

Automated application checks used PostgreSQL. Browser checks used rendered local
fixtures; they do not replace assistive-technology or physical-device testing.
No unresolved implementation issue or architectural deviation was identified.
