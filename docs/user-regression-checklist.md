# User regression checklist

Scope: recent Import, Mock Test, Practice, Revision Bank and admin changes.
This is a manual acceptance checklist; unchecked items have not been verified by this document.

Tester: __________  Date: __________  Environment / version: __________
Browser / device: __________  Result: Pass / Fail / Blocked

## Before testing

- Use a local or test environment with disposable test accounts and data.
- Have an administrator account and two separate student accounts.
- Prepare published English-only, Bengali-only and bilingual questions with clearly
  distinguishable text and explanations. Include at least two difficulty levels and
  modules, plus an unpublished translation for an exclusion check.
- Prepare a bilingual Mock Test with enough fully translated questions for every
  section. Keep a separate incomplete draft pattern for validation checks.
- Use a fresh Mock Test attempt for each language check: returning to an open attempt
  resumes its original language and questions.

## 1. Mock Tests

- [ ] Follow **Mock Tests → Category → Exam → Available tests**. Only available tests
  appear; opening the list or test overview does not start the timer or an attempt.
- [ ] **All categories** and **Back to exams** arrows point backward. Each test card
  shows **Go to test**, which opens its overview.
- [ ] The overview shows sections, instructions and English / Bengali / Both choices.
  Language choices are centered, with **Start Test** and **Back to available tests** below.
- [ ] Start a fresh bilingual test in **English**. Questions and options appear only in English.
- [ ] Start a fresh bilingual test in **Bengali**. Questions and options appear only in Bengali.
- [ ] Start a fresh bilingual test with **Both**. Each question shows both versions;
  translations share one question number and answer selection.
- [ ] Answer a question, mark another for review, wait for the saved confirmation,
  then reload. Answers and review marks remain; the timer continues rather than restarting.
- [ ] Log out and sign back in, or use another browser with the same account. Resume
  the attempt: its language, questions and saved answers remain unchanged.
- [ ] Open **Go to test** again during an attempt. It resumes the existing attempt,
  rather than creating another or changing its language.
- [ ] Submit an attempt and inspect results. Results use the selected language;
  scores and question totals remain correct for the known test answers.
- [ ] For a short-duration test, let the deadline pass. The attempt finalizes and
  saved answers are scored; answers cannot be changed afterward.

## 2. Practice Sets

- [ ] Follow **Practice Sets → Category → Exam → Subject → Module**. Module cards
  open the combined difficulty and language page.
- [ ] Difficulty and language appear side by side on desktop and stack on a narrow
  screen. **Back to modules** is a centered primary button.
- [ ] Choose a module, difficulty and **English**. Only matching questions with a
  published English version are included, and only their English versions appear.
- [ ] Repeat with **Bengali**. Only matching questions with a published Bengali
  version are included, and only their Bengali versions appear.
- [ ] Choose **Both**. All eligible matching questions are included, showing their
  available translations. Unlike bilingual Mock sections, every Practice question
  does not have to contain both languages.
- [ ] Submit an answer. Feedback and explanations use the saved language; the answer
  locks after submission. Moving to another question preserves the language.
- [ ] Log out and sign back in, then reopen the session. The selected language,
  questions and previous answers remain unchanged.
- [ ] Choose a language with no published questions at the chosen difficulty/module.
  A clear validation message appears and no empty session starts. An unpublished
  translation must not make a question eligible for that language.
- [ ] Check difficulty counts against the explanatory text: they are before language
  filtering, so the started session may contain fewer questions.
- [ ] For a subject without eligible modules, use **Continue with this subject**.
  Difficulty/language selection works and **Back to subjects** returns correctly.

## 3. My Revision Bank

- [ ] Open **My Revision Bank**. Only **Exam** and **Subject** filter controls are
  visible; the other filter controls remain hidden.
- [ ] Apply Exam, Subject and both together. Matching saved questions appear;
  **Reset filters** returns to the unfiltered bank.
- [ ] Open a saved question, update its private note, and return to the bank.
  The note and saved state persist. A second student cannot view the first student's bank or notes.

## 4. Import completion

- [ ] Complete a small valid import. **Import another file** is a primary button
  matching **Review Question Bank**, and opens the upload page.
- [ ] **Imported questions** opens as a table of source rows and linked Question IDs.
  Row links open the correct Question admin page.
- [ ] Imported questions remain pending explicit review/publication. An imported
  paper remains hidden from students until its publication requirements are satisfied.

## 5. Administrator checks

- [ ] Open a Question admin page. Read-only translations appear with their revisions,
  newest revision first, without the inline foreign-key error.
- [ ] Open a QuestionRevision admin page. Its translation inline shows only that
  revision's translations. Historical translation content cannot be edited inline.
- [ ] Open **Add Exam Pattern** and submit a blank name or invalid required value.
  Validation messages appear without the `error_list` exception or saving an invalid pattern.
- [ ] Try activating an incomplete pattern or one with insufficient eligible questions.
  Activation is rejected with a validation message.
- [ ] For an **English/Bengali** Mock section, verify that English-only, Bengali-only
  and unpublished translations cannot satisfy the bilingual quota. Enough complete,
  published bilingual questions allow activation. Check detailed/manual rules too if used.

## 6. Compatibility and access

- [ ] Open an older Mock attempt and Practice session. Existing question sets,
  answers and results remain intact. Historical sessions without a stored language
  keep their legacy display behavior.
- [ ] Using the second student's account, try the first student's attempt/session URL.
  Access is denied without revealing question content or answers.
- [ ] Check the changed pages on desktop and mobile: controls remain readable,
  selectable and reachable; navigation links return to the expected page.

## Record any failure

Checklist item: __________  Account role: __________

Steps and selected exam / subject / module / language:

____________________________________________________________

Expected result: ____________________________________________

Actual result / error: ______________________________________

Screenshot or issue reference: ______________________________

Do not include passwords, session tokens or private student records in reports.
