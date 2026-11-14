# Shared shell and profile review

| Screen | Desktop | Mobile |
| --- | --- | --- |
| Profile/header | [Desktop](profile-desktop.png) | [360 px](profile-mobile.png) |
| Footer | [Desktop](footer-desktop.png) | [360 px](footer-mobile.png) |
| Guest login | — | [360 px](login-mobile.png) |

The shared base now uses slate/white surfaces and indigo accents. Header navigation
prioritizes the three study activities; native Question Library and account
disclosures retain secondary routes, staff-only Admin, focus return and Escape
dismissal. Footer placeholders were removed in favor of functional Study/Account
links. Profile uses existing account data and links to existing study/resume pages;
it adds no account editing or dashboard queries.

Verification: 24 account/authentication/navigation tests passed, plus two Edge
browser tests covering the shell and the full mock/practice/previous-year journey.
Tailwind build/freshness and diff whitespace checks passed. Screenshots use only
synthetic data in an isolated Django test database, at 1440 and 360 px widths.
No application records or schema were changed.

The previously documented homepage dynamic-category test failure remains outside
this change. Physical phones, additional browsers and screen readers were not tested.

Reproduce browser checks with `python manage.py test tools.verify_exam_ui --noinput`.
