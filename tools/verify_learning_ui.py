"""Opt-in Edge checks for UI-2, using the existing disposable browser fixture.

Run the two UI-2 journeys explicitly (inherited checks remain available):
python manage.py test tools.verify_learning_ui.LearningUIBrowserTests.test_mock_and_paper_desktop_mobile tools.verify_learning_ui.LearningUIBrowserTests.test_revision_themes_and_answer_boundary tools.verify_learning_ui.LearningUIBrowserTests.test_mock_theme_and_mobile_chrome --noinput
Screenshots are temporary; no runtime data or committed captures are changed.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.urls import reverse

from mock_tests.services import start_attempt
from revision.services import set_saved
from revision.sessions import start_revision
from tools import verify_exam_ui


class LearningUIBrowserTests(verify_exam_ui.ExamReadingBrowserTests):
    def setUp(self):
        super().setUp()
        captures = TemporaryDirectory(prefix="learning-ui-")
        self.addCleanup(captures.cleanup)
        self.output = Path(captures.name)
        self.general_output = self.output / 'general-questions'
        self.account_output = self.output / 'account-shell'

    def reload_page(self):
        self.browser.evaluate("document.documentElement.dataset.uiReloadPending='true'")
        self.browser.call("Page.reload")
        self.browser.wait("!document.documentElement.dataset.uiReloadPending && document.readyState === 'complete'")

    def test_revision_themes_and_answer_boundary(self):
        for paper_row in self.paper.paper_questions.filter(display_order__lte=2):
            set_saved(self.user, paper_row.question_revision.question_id, saved=True)
        session = start_revision(self.user, {"token": uuid4()})
        row = session.questions.order_by("display_order").first()
        url = self.live_server_url + reverse("revision:session", args=[session.pk]) + f"?question={row.display_order}"
        b = self.browser
        b.navigate(url)
        b.wait("!!document.querySelector('[data-revision-answer]')")
        for theme in ("light", "dark", "sepia"):
            b.evaluate(f"document.querySelector('#reading-theme').value='{theme}'; document.querySelector('#reading-theme').dispatchEvent(new Event('change'))")
            self.assertEqual(b.evaluate("document.documentElement.dataset.theme"), theme)
            for width in (1440, 1024, 360):
                b.viewport(width, 800)
                self.assert_layout()
                self.assertEqual(b.evaluate("document.querySelectorAll('[data-revision-answer] input[type=radio]').length"), 4)
                self.assertFalse(b.evaluate("document.body.textContent.includes('Correct answer:')"))
                self.assertFalse(b.evaluate("!!document.querySelector('.solution')"))
                self.assertEqual(b.evaluate("getComputedStyle(document.querySelector('.exam-option')).backgroundColor"), b.evaluate("getComputedStyle(document.querySelector('.paper-question')).backgroundColor"))
                columns = b.evaluate("getComputedStyle(document.querySelector('.exam-stems')).gridTemplateColumns.split(' ').length")
                self.assertEqual(columns, 2 if width > 1024 else 1)
                b.key("Tab", "Tab", 9)
                b.evaluate("document.querySelector('.exam-option input').focus()")
                self.assertEqual(b.evaluate("getComputedStyle(document.activeElement.closest('.exam-option')).outlineStyle"), "solid")
        self.reload_page()
        b.wait("!!document.querySelector('[data-revision-answer]')")
        self.assertEqual(b.evaluate("document.documentElement.dataset.theme"), "sepia")
        b.evaluate("document.querySelector('[data-revision-answer] input[value=B]').focus()")
        b.key(" ", "Space", 32)
        b.wait("!!document.querySelector('.practice-reading-feedback.is-incorrect')")
        row.refresh_from_db()
        self.assertEqual(row.selected_answer, "B")
        self.assertEqual(b.evaluate("document.querySelectorAll('[data-revision-answer]').length"), 0)
        self.assertTrue(b.evaluate("document.querySelector('.solution').open"))
        self.assertTrue(b.evaluate("document.body.textContent.includes('Correct answer: A')"))
        self.assert_layout()
        self.reload_page()
        b.wait("!!document.querySelector('.practice-reading-feedback')")
        self.assertTrue(b.evaluate("document.querySelector('.practice-reading-feedback').textContent.includes('Your answer: B')"))
        b.navigate(self.live_server_url + reverse("revision:dashboard"))
        b.wait("!!document.querySelector('.revision-list')")
        self.assert_layout()
        b.evaluate("document.querySelector('.revision-list .button-primary').click()")
        b.wait("!!document.querySelector('.exam-stems')")
        self.assert_layout()

    def test_mock_theme_and_mobile_chrome(self):
        attempt = start_attempt(self.user, self.pattern)
        b = self.browser
        b.navigate(self.live_server_url + reverse("mock_tests:attempt_detail", args=[attempt.pk]))
        b.wait("!!document.querySelector('#mock-timer')")
        for theme in ("light", "dark", "sepia"):
            b.evaluate(f"localStorage.setItem('mock-exam-theme', '{theme}')")
            self.reload_page()
            b.wait("!!document.querySelector('.mock-question') && document.querySelector('#mock-timer').textContent !== 'Loading...'")
            for width in (1440, 1024, 360):
                b.viewport(width, 740)
                self.assert_layout()
                self.assertFalse(b.evaluate("document.body.textContent.includes('Correct answer:') || !!document.querySelector('.solution,.correct-option')"))
                b.evaluate("document.querySelector('.mock-question .exam-option:last-child').scrollIntoView({block:'center'})")
                bounds = b.evaluate("(() => { const r=document.querySelector('.mock-question .exam-option:last-child').getBoundingClientRect(); return {top:r.top,bottom:r.bottom,height:r.height,toolbar:document.querySelector('.mock-toolbar').getBoundingClientRect().bottom,actions:document.querySelector('.mock-action-bar').getBoundingClientRect().top}; })()")
                self.assertTrue(bounds['bottom'] <= bounds['actions'] and bounds['top'] >= bounds['toolbar'], f"Option obscured: {theme}, {width}px, {bounds}")
