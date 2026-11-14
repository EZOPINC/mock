# Student journey redesign

Captured with headless Microsoft Edge against an isolated Django PostgreSQL test
database. Content is synthetic educational English/Bengali material about the
Permanent Settlement, with long bilingual stems/options plus English-only and
Bengali-only questions. No application accounts or content were changed.

| Screen | Desktop (1440 × 1000) | Phone (360 × 1000) |
| --- | --- | --- |
| Timed mock | [Desktop](mock-desktop.png) | [Mobile](mock-mobile.png) |
| Mock selection | [Desktop](mock-selection-desktop.png) | [Mobile](mock-selection-mobile.png) |
| Mock results | [Desktop](mock-results-desktop.png) | [Mobile](mock-results-mobile.png) |
| Practice feedback | [Desktop](practice-feedback-desktop.png) | [Mobile](practice-feedback-mobile.png) |
| Previous-year practice paper | [Desktop](paper-desktop.png) | [Mobile](paper-mobile.png) |

Extra `*-question.png` images show complete long questions; `paper-*-solution.png`
shows revealed feedback/solutions. Sticky chrome is hidden only while capturing
these extra whole-question images. The viewport images retain normal chrome.

Browser assertions cover:

- Category → exam → mock selection, then Start Test through the existing form and
  CSRF-protected route. Pattern section languages determine the student form's
  saved language (uniform English/Bengali or both for mixed section languages).
- Space/arrow-key answer selection, Tab navigation and a visible focus outline.
- Review flag, navigation away/back, reload restoration, ticking timer and final
  confirmation/submission with the expected score.
- Mobile Questions disclosure and automatic closure after navigation.
- No horizontal page scrolling or clipped answer rows at either viewport; the last
  mock answer option can scroll fully between the sticky timer and action bar.
- Whole-row paper selection, feedback, solution disclosure, single-language
  rendering and direct-answer mode.
- Continue mock test through the open-attempt card; saved answers and flags survive.
- Practice category → exam → subject → difficulty/language → session, incorrect
  feedback, Next navigation, pause/resume, correct feedback, completion and summary.
  Explanations stay in normal document flow without sticky Next controls.

Rerun on a Windows machine with Edge installed:

```console
python manage.py test tools.verify_exam_ui --noinput
```

Additional verification: 122 targeted Django tests passed across mock execution,
attempt language/selection, Practice, previous-year modes and Revision sessions.
The Tailwind build, generated-output check and diff whitespace check passed.
No schema, route or domain-service changes were needed. Revision sessions retain
their existing question markup. Existing attempt language snapshots and the
backend's compatible POST contract remain intact.

A broader navigation run found an existing failure in
`core.test_navigation.NavigationTests.test_home_keeps_dynamic_categories_and_active_exam_links`:
the homepage does not contain the expected dynamic authority name. This was also
reproduced with the original HEAD navigation template; homepage implementation
was left unchanged. Other navigation tests in that run passed.

The inspected mock/practice services do not implement a practice allowance or
upgrade entitlement counter. No new limits, upgrade actions or counting rules
were introduced. Existing active-catalogue, owner and publication checks remain.

This pass does not replace manual testing on physical phones, Safari/Firefox or
with a screen reader; those checks were not run.
