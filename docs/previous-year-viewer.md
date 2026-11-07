# Previous-year viewer (Milestone 2.3D)

## Milestone 3.2 public browsing finalization

The public browsing/viewing experience is finalized over these existing routes,
models and snapshot relationships. Breadcrumbs consistently follow Previous Year
Papers → Exam → Year → Paper, and viewer titles include exam, paper and year.
Public eligibility now also requires an available translation snapshot owned by
the selected revision/master and a valid approved answer; papers with missing
translation sets, unapproved revisions or mismatched configured subject are hidden
instead of exposing incomplete content. A missing optional language leaves the
available version in a single column; no translation is synthesized.

Verified-only solution rendering has an explicit unavailable state, and cannot
highlight answer options for unverified revisions. Public answers/explanations
remain initially collapsed; a missing explanation is labelled explicitly. Existing
English-first ordering, mobile stacking, original numbering/order, paper selection,
and pinned historical revisions are preserved. Import staging/confirmation and
question publication workflows are unchanged; no models, migrations, mock engine,
timers or scoring are added.

Navigation is **Previous Year Papers → Exam → Year → View Questions**.
The landing page lists only exams with eligible published papers. Exam pages list
available years newest first. A year with one paper redirects directly to its
existing viewer. Multiple papers show a selector and cards labelled by the
existing paper name, stage, part and shift/session. No parallel paper or shift
model is introduced.

Routes reuse the existing prefix:

- `/previous-year/`: exam discovery.
- `/previous-year/<authority>/<exam>/`: years.
- `/previous-year/<authority>/<exam>/<year>/`: single-paper redirect or selection.
- `/previous-year/<authority>/<exam>/<year>/<paper_id>/`: existing viewer URL.

The selector is scoped to the active exam/year and eligible published papers.
Invalid selections show a validation error; missing years/papers return 404.
Drafts and inactive taxonomy remain excluded by the existing publication query.

Question content comes from PaperQuestion.question_revision and its available
QuestionTranslation snapshots. Original paper question_number and display_order
are retained. English is prefetched first, Bengali second, other configured
languages afterwards. This is viewer-local ordering, not a model/migration change.
One language occupies one column; available bilingual versions display side by
side when space allows and stack below 48rem. Text, mathematical Unicode and
option ordering are rendered unchanged and escaped.

Verified published revision answers/explanations are available through a native,
initially closed **Show Answer/Explanation** disclosure. No answer-option highlight
is shown before opening it. Missing explanations have an explicit message. Staff
paper preview can inspect draft answers privately; public views require existing
publication approval. This is an untimed reading interface, not an attempt engine.

Models, migrations, import/pairing rules, revision immutability and publication
services are unchanged. Existing paper administration already supplies all
required associations/configuration; no additional Milestone 3.1 dependencies
were missing. Test coverage includes navigation, selector scoping, draft exclusion,
English-first order, monolingual markup, original numbering/order, disclosures and
historical revision stability. Manual browser layout/keyboard review remains useful.

## Direct Answers and Practice Paper (2026-11-07)

After choosing a year, guests choose Direct Answers or Practice Paper. The chosen
mode is carried through stage/session/paper selection; direct paper links default
to Direct Answers. The two viewers reuse the same published paper, original
PaperQuestion numbering/order, subject filter, and immutable pinned revisions.

- `?mode=direct`: all questions, correct options highlighted in each available
  translation, answers and explanations already open.
- `?mode=practice`: all questions stay visible, with radio choices and no answer
  keys/explanations in initial HTML. Selecting a choice submits that question by
  CSRF-protected POST; vanilla JavaScript replaces only its content with server-
  generated correct/incorrect feedback, highlighted answer and open explanation.
  Without JavaScript, Check answer returns the full paper with that one feedback.

The feedback route is the paper URL plus `questions/<paper_question_id>/answer/`.
It validates A-D, mode, paper/exam/year, subject scope and current publication;
foreign rows and inactive/draft papers return 404. Feedback always uses the paper's
pinned revision even if a newer revision is published. Responses are not cached.
English/Bengali layouts and explicit unavailable-explanation text remain shared.

This public paper practice is untimed and temporary: selections reset on reload,
mode/filter changes or navigation to another paper. It creates no PracticeSession,
mock attempt, score or duplicate question. Persistent authenticated Practice Mode
remains a separate module. Admin previews retain their existing disclosure view.
No model changes, migrations, imports or deployment work are involved.
