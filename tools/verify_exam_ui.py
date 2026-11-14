"""Run explicitly: python manage.py test tools.verify_exam_ui --noinput.

Uses only a disposable Django test database and an isolated headless Edge profile.
Screenshots are written to docs/screenshots/exam-reading/.
"""
from pathlib import Path
import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from exams.models import ExamAuthority, Exam, Subject
from mock_tests.models import ExamPattern, ExamPatternSection, MockAttempt
from mock_tests.services import activate_pattern
from previous_year.models import PreviousYearPaper, PaperQuestion
from previous_year.services import publish_paper
from practice.models import PracticeSession
from questions.models import QuestionExam
from questions.services import create_question, add_translation, mark_reviewed, publish_question
from tools.exam_browser import ExamBrowser


@override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"], SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class ExamReadingBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        authority = ExamAuthority.objects.create(name="Public Service Commission", code="UI", slug="ui")
        self.exam = Exam.objects.create(authority=authority, name="Civil Services Preliminary", code="UI", slug="civil-services")
        subject = Subject.objects.create(name="History", code="UI", slug="history")
        self.user = get_user_model().objects.create_user(username="ui-review-student")
        questions = []
        for index in range(2):
            question = create_question(subject=subject, revision=dict(
                language="en", question_text="Consider the following statements about the Permanent Settlement introduced in Bengal in 1793. The land revenue payable by zamindars was fixed permanently, while cultivators continued to pay rent to the zamindars. Which of the following best explains its effect on agricultural investment and the relationship between the colonial state, zamindars and cultivators?" if index == 0 else "Which statement correctly explains the impact of the Permanent Settlement on cultivators and land revenue?",
                option_a="Revenue was fixed for zamindars, but cultivators did not automatically receive secure tenancy rights or protection from increases in rent.",
                option_b="Every cultivator became an independent landowner and paid a fixed tax directly to the colonial state, without an intermediary.",
                option_c="The colonial government reassessed the revenue demand every year and distributed the proceeds equally among cultivators.",
                option_d="Zamindars were required to invest all rental income in irrigation before they could pay revenue to the government.",
                correct_answer="A", explanation="The settlement fixed the state's revenue demand on zamindars. It did not guarantee secure rights or fixed rents for cultivators."))
            if index in (0, 1):
                add_translation(question, language="bn",
                    question_text="১৭৯৩ সালে বাংলায় প্রবর্তিত চিরস্থায়ী বন্দোবস্ত সম্পর্কে নিচের বক্তব্যগুলি বিবেচনা করুন। জমিদারদের প্রদেয় ভূমিরাজস্ব চিরকালের জন্য নির্দিষ্ট করা হয়েছিল, কিন্তু কৃষকেরা জমিদারদের খাজনা দিতে থাকেন। কৃষিতে বিনিয়োগ এবং ঔপনিবেশিক রাষ্ট্র, জমিদার ও কৃষকদের পারস্পরিক সম্পর্কের উপর এই ব্যবস্থার প্রভাব কোন বক্তব্যটি সবচেয়ে যথাযথভাবে ব্যাখ্যা করে?",
                    option_a="জমিদারদের প্রদেয় রাজস্ব নির্দিষ্ট ছিল, কিন্তু কৃষকেরা স্বয়ংক্রিয়ভাবে জমির নিরাপদ স্বত্ব বা খাজনা বৃদ্ধি থেকে সুরক্ষা পাননি।",
                    option_b="প্রত্যেক কৃষক স্বাধীন ভূমিমালিক হন এবং কোনো মধ্যস্বত্বভোগী ছাড়াই সরাসরি ঔপনিবেশিক রাষ্ট্রকে নির্দিষ্ট কর দিতে থাকেন।",
                    option_c="ঔপনিবেশিক সরকার প্রতি বছর রাজস্বের পরিমাণ পুনর্নির্ধারণ করত এবং আদায় করা অর্থ কৃষকদের মধ্যে সমানভাবে বণ্টন করত।",
                    option_d="সরকারকে রাজস্ব দেওয়ার আগে জমিদারদের খাজনা থেকে প্রাপ্ত সমস্ত অর্থ সেচব্যবস্থায় বিনিয়োগ করা বাধ্যতামূলক ছিল।",
                    explanation="চিরস্থায়ী বন্দোবস্তে জমিদারদের প্রদেয় সরকারি রাজস্ব নির্দিষ্ট হয়। কৃষকদের জমির নিরাপদ স্বত্ব বা নির্দিষ্ট খাজনার নিশ্চয়তা দেওয়া হয়নি।")
            question = publish_question(mark_reviewed(question))
            QuestionExam.objects.create(question=question, exam=self.exam)
            questions.append(question)
        # Monolingual records exercise full-width reading and practice filtering;
        # the mixed-language mock continues to draw only from the bilingual pair.
        for language, stem in (("en", "Which year marks the Permanent Settlement?"), ("bn", "চিরস্থায়ী বন্দোবস্ত কত সালে চালু হয়?")):
            question = create_question(subject=subject, revision=dict(language=language, question_text=stem,
                option_a="1793" if language == "en" else "১৭৯৩", option_b="1857" if language == "en" else "১৮৫৭",
                option_c="1905" if language == "en" else "১৯০৫", option_d="1947" if language == "en" else "১৯৪৭",
                correct_answer="A", explanation="The Permanent Settlement was introduced in 1793." if language == "en" else "১৭৯৩ সালে চিরস্থায়ী বন্দোবস্ত চালু হয়।"))
            question = publish_question(mark_reviewed(question))
            QuestionExam.objects.create(question=question, exam=self.exam)
            questions.append(question)
        self.pattern = ExamPattern.objects.create(exam=self.exam, name="History · Preliminary mock", duration_minutes=60, total_questions=2, total_marks=2)
        ExamPatternSection.objects.create(pattern=self.pattern, name="Indian History", language_mode="mixed", question_count=2, display_order=1)
        activate_pattern(self.pattern)
        self.paper = PreviousYearPaper.objects.create(exam=self.exam, year=2023, paper_name="History · Previous-year paper")
        for index, question in enumerate(questions, 1):
            PaperQuestion.objects.create(paper=self.paper, question_revision=question.published_revision, question_number=str(index), display_order=index)
        publish_paper(self.paper)
        self.client.force_login(self.user)
        self.browser = ExamBrowser()
        self.addCleanup(self.browser.close)
        self.browser.call("Network.setCookie", name=settings.SESSION_COOKIE_NAME,
                          value=self.client.cookies[settings.SESSION_COOKIE_NAME].value, url=self.live_server_url)
        self.output = Path(settings.BASE_DIR) / "docs/screenshots/exam-reading"
        self.output.mkdir(parents=True, exist_ok=True)

    def assert_layout(self):
        self.assertTrue(self.browser.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Horizontal page overflow")
        self.assertTrue(self.browser.evaluate("[...document.querySelectorAll('.exam-option')].every(e => e.scrollWidth <= e.clientWidth)"), "Clipped answer option")

    def test_general_question_translation_slots(self):
        from tempfile import TemporaryDirectory
        from imports.tests import csv_file, values
        from imports.parsing import parse_upload
        from imports.staging import create
        from imports.services import confirm_import
        from general_question.services import batch_questions, fingerprint, transition_batch
        self.user.is_staff = self.user.is_superuser = True
        self.user.save(update_fields=['is_staff', 'is_superuser'])
        rows = [values(subject='History', topic='', question_number='1', question_text='Which year marks the Permanent Settlement?'),
                values(subject='History', topic='', question_number='2', language='bn', question_text='চিরস্থায়ী বন্দোবস্ত কত সালে চালু হয়?'),
                values(subject='History', topic='', question_number='3', question_text='Which statement explains fixed land revenue under the Permanent Settlement?')]
        with TemporaryDirectory() as directory, override_settings(IMPORT_STAGING_ROOT=Path(directory)):
            data = create(self.user, {**parse_upload(csv_file(rows)), 'selection': {
                'import_type': 'general', 'exam_ids': [self.exam.pk], 'exam_mapping': 'selected'},
                'subject_map': {}, 'topic_map': {}})
            batch = confirm_import(data, self.user)
        question = batch_questions(batch).order_by('pk').last()
        add_translation(question, language='bn', question_text='চিরস্থায়ী বন্দোবস্তে নির্দিষ্ট রাজস্ব সম্পর্কে কোন বক্তব্যটি সঠিক?',
                        option_a='প্রথম বক্তব্য', option_b='দ্বিতীয় বক্তব্য', option_c='তৃতীয় বক্তব্য', option_d='চতুর্থ বক্তব্য', explanation='বাংলা ব্যাখ্যা')
        for action in ('review', 'publish'):
            transition_batch(batch.pk, self.user, action, fingerprint(list(batch_questions(batch))))
        b = self.browser
        output = Path(settings.BASE_DIR) / 'docs/screenshots/general-questions'
        output.mkdir(parents=True, exist_ok=True)
        b.navigate(self.live_server_url + reverse('general_questions:collection', args=[batch.pk]))
        b.wait("!!document.querySelector('.general-reader')")
        self.assertEqual(b.evaluate("document.querySelectorAll('[data-missing-edition]').length"), 2)
        self.assertTrue(b.evaluate("[...document.querySelectorAll('[data-missing-edition] .exam-stem')].every(e=>e.textContent.trim()==='')"))
        for width, label in ((1440, 'desktop'), (360, 'mobile')):
            b.viewport(width)
            b.evaluate("document.querySelector('.general-edition-reader').scrollIntoView()")
            self.assert_layout()
            if width == 1440:
                self.assertEqual(b.evaluate("getComputedStyle(document.querySelector('.general-edition-reader .exam-stems')).gridTemplateColumns.split(' ').length"), 2)
            b.screenshot(output / f'collection-{label}.png')
        self.assertTrue(b.evaluate("document.querySelector('.solution').open"))
        b.evaluate("document.querySelector('.solution summary').click()")
        self.assertFalse(b.evaluate("document.querySelector('.solution').open"))

    def test_shell_profile_desktop_mobile(self):
        b = self.browser
        output = Path(settings.BASE_DIR) / 'docs/screenshots/account-shell'
        output.mkdir(parents=True, exist_ok=True)
        b.viewport(1440)
        b.navigate(self.live_server_url + reverse('accounts:profile'))
        b.wait("!!document.querySelector('.account-profile')")
        b.evaluate("document.querySelector('.library-menu summary').click()")
        self.assertTrue(b.evaluate("document.querySelector('.library-menu').open"))
        b.evaluate("document.querySelector('.library-menu a').focus()")
        b.key('Escape', 'Escape', 27)
        self.assertFalse(b.evaluate("document.querySelector('.library-menu').open"))
        self.assertTrue(b.evaluate("document.activeElement.matches('.library-menu summary')"))
        for width, label in ((1440, 'desktop'), (360, 'mobile')):
            b.viewport(width)
            b.evaluate('scrollTo(0,0)')
            self.assert_layout()
            b.screenshot(output / f'profile-{label}.png')
            b.evaluate("document.querySelector('.calm-footer').scrollIntoView()")
            self.assert_layout()
            b.screenshot(output / f'footer-{label}.png')
        b.evaluate("document.querySelector('.menu-toggle').click()")
        self.assertFalse(b.evaluate("document.querySelector('#primary-navigation').hidden"))
        b.evaluate("document.querySelector('.library-menu summary').click()")
        b.evaluate("document.querySelector('.library-menu a').focus()")
        b.key('Escape', 'Escape', 27)
        self.assertFalse(b.evaluate("document.querySelector('.library-menu').open"))
        self.assertFalse(b.evaluate("document.querySelector('#primary-navigation').hidden"))
        b.key('Escape', 'Escape', 27)
        self.assertTrue(b.evaluate("document.querySelector('#primary-navigation').hidden"))
        # Guest shell and auth page keep their real login/register destinations.
        b.call('Network.clearBrowserCookies')
        b.navigate(self.live_server_url + reverse('accounts:login'))
        b.wait("!!document.querySelector('input[type=password]')")
        self.assert_layout()
        self.assertEqual(b.evaluate("document.querySelectorAll('.calm-footer a[href=\"#\"]').length"), 0)
        b.screenshot(output / 'login-mobile.png')

    def test_mock_and_paper_desktop_mobile(self):
        b = self.browser
        b.viewport(1440)
        b.navigate(self.live_server_url + reverse("mock_tests:index"))
        b.evaluate("document.querySelector('.mock-hub-categories a').click()")
        b.wait("location.pathname.endsWith('/ui/')")
        b.evaluate("document.querySelector('.mock-hub-categories a').click()")
        b.wait("location.pathname.includes('civil-services')")
        for width, label in ((1440, "desktop"), (360, "mobile")):
            b.viewport(width)
            self.assert_layout()
            b.screenshot(self.output / f"mock-selection-{label}.png")
        b.evaluate("document.querySelector('.mock-pattern-card .button').click()")
        b.wait("!!document.querySelector('.mock-start-buttons')")
        self.assertEqual(b.evaluate("document.querySelector('input[name=language]').value"), "both")
        b.evaluate("document.querySelector('.mock-start-buttons button[type=submit]').click()")
        b.wait("!!document.querySelector('.mock-execution') && document.querySelector('#mock-timer').textContent !== 'Loading...'")
        attempt = MockAttempt.objects.get(user=self.user)
        # Random selection order is retained; find the actual bilingual question.
        order = b.evaluate("[...document.querySelectorAll('.mock-question:has([lang=bn])')].sort((a,b)=>b.textContent.length-a.textContent.length)[0].dataset.order")
        b.evaluate(f"document.querySelector('.mock-palette [data-goto=\"{order}\"]').click()")
        b.wait("document.querySelector('#mock-save-status').textContent.toLowerCase().includes('saved')")
        self.assertEqual(b.evaluate(f"document.querySelector('[data-order=\"{order}\"] .exam-answers').querySelectorAll('input[type=radio]').length"), 4)
        b.evaluate(f"document.querySelector('[data-order=\"{order}\"] input[value=A]').focus()")
        b.key(" ", "Space", 32)
        b.wait("document.querySelector('#mock-save-status').textContent === 'All changes saved.'")
        b.key("ArrowDown", "ArrowDown", 40)
        b.wait(f"document.querySelector('[data-order=\"{order}\"] input[value=B]').checked && document.querySelector('#mock-save-status').textContent === 'All changes saved.'")
        b.key("ArrowUp", "ArrowUp", 38)
        b.wait(f"document.querySelector('[data-order=\"{order}\"] input[value=A]').checked && document.querySelector('#mock-save-status').textContent === 'All changes saved.'")
        self.assertEqual(b.evaluate("getComputedStyle(document.activeElement.closest('.exam-option')).outlineStyle"), "solid")
        b.key("Tab", "Tab", 9)
        self.assertTrue(b.evaluate("document.activeElement.matches('[data-clear]')"))
        b.evaluate("document.querySelector('[data-current-review]').click()")
        b.wait("document.querySelector('#mock-save-status').textContent === 'All changes saved.'")
        other = "2" if order == "1" else "1"
        b.evaluate(f"document.querySelector('.mock-palette [data-goto=\"{other}\"]').click()")
        b.wait("document.querySelector('#mock-save-status').textContent === 'All changes saved.'")
        b.evaluate(f"document.querySelector('.mock-palette [data-goto=\"{order}\"]').click()")
        b.wait("document.querySelector('#mock-save-status').textContent === 'All changes saved.'")
        b.call("Page.reload")
        b.wait("!!document.querySelector('.mock-execution') && document.readyState === 'complete'")
        b.wait("document.querySelector('#mock-timer').textContent !== 'Loading...'")
        self.assertTrue(b.evaluate(f"document.querySelector('[data-order=\"{order}\"] input[value=A]').checked"))
        self.assertTrue(b.evaluate(f"document.querySelector('[data-order=\"{order}\"] [data-review]').checked"))
        initial_timer = b.evaluate("document.querySelector('#mock-timer').textContent")
        time.sleep(1.2)
        self.assertNotEqual(initial_timer, b.evaluate("document.querySelector('#mock-timer').textContent"))
        for width, label in ((1440, "desktop"), (360, "mobile")):
            b.viewport(width)
            b.evaluate(f"document.querySelector('[data-order=\"{order}\"]').scrollIntoView()")
            self.assert_layout()
            b.screenshot(self.output / f"mock-{label}.png")
            b.screenshot(self.output / f"mock-{label}-question.png", f'[data-order="{order}"]')
            b.evaluate(f"document.querySelector('[data-order=\"{order}\"] .exam-option:last-child').scrollIntoView({{block:'center'}})")
            self.assertTrue(b.evaluate(f"(() => {{const r=document.querySelector('[data-order=\"{order}\"] .exam-option:last-child').getBoundingClientRect(); return r.bottom <= document.querySelector('.mock-action-bar').getBoundingClientRect().top && r.top >= document.querySelector('.mock-toolbar').getBoundingClientRect().bottom; }})()"), "Last option overlaps sticky controls")
            if width == 360:
                b.evaluate("document.querySelector('[data-palette-toggle]').click()")
                self.assertTrue(b.evaluate("document.querySelector('#mock-palette-panel').open"))
                b.evaluate(f"document.querySelector('.mock-palette [data-goto=\"{order}\"]').click()")
                self.assertFalse(b.evaluate("document.querySelector('#mock-palette-panel').open"))
        b.navigate(self.live_server_url + reverse("mock_tests:index"))
        b.wait("!!document.querySelector('.is-resumable .button')")
        self.assertIn("Continue mock test", b.evaluate("document.querySelector('.is-resumable').textContent"))
        b.evaluate("document.querySelector('.is-resumable .button').click()")
        b.wait("!!document.querySelector('#mock-finish')")
        b.evaluate("document.querySelector('#mock-finish').click()")
        b.wait("!!document.querySelector('input[name=version]')")
        b.evaluate("document.querySelector('input[name=version]').form.querySelector('button').click()")
        b.wait("location.pathname.includes('results')")
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "submitted")
        self.assertEqual(attempt.correct_count, 1)
        b.wait("!!document.querySelector('.mock-results')")
        for width, label in ((1440, "desktop"), (360, "mobile")):
            b.viewport(width)
            b.evaluate("scrollTo(0,0)")
            self.assert_layout()
            b.screenshot(self.output / f"mock-results-{label}.png")
        paper_url = self.live_server_url + reverse("previous_year:paper_detail", args=["ui", "civil-services", 2023, self.paper.pk])
        for width, label in ((1440, "desktop"), (360, "mobile")):
            b.viewport(width)
            b.navigate(paper_url + "?mode=practice")
            b.wait("!!document.querySelector('.paper-practice-form')")
            b.evaluate("document.querySelector('.paper-viewer').scrollIntoView()")
            self.assert_layout()
            b.screenshot(self.output / f"paper-{label}.png")
            b.screenshot(self.output / f"paper-{label}-question.png", '.paper-viewer')
            self.assertFalse(b.evaluate("document.body.textContent.includes('Correct answer:')"))
            b.evaluate("document.querySelector('.paper-practice-form .exam-option[data-option=A]').click()")
            b.wait("!!document.querySelector('.ui-answer-feedback')")
            self.assertTrue(b.evaluate("document.querySelector('.ui-answer-feedback').textContent.includes('Correct.')"))
            self.assertTrue(b.evaluate("document.querySelector('.exam-paper-solutions details').open"))
            b.screenshot(self.output / f"paper-{label}-solution.png", '.paper-viewer')
            b.evaluate("document.querySelector('.exam-paper-solutions summary').click()")
            self.assertFalse(b.evaluate("document.querySelector('.exam-paper-solutions details').open"))
            self.assertEqual(b.evaluate("document.querySelectorAll('.paper-viewer')[2].querySelectorAll('.exam-stems > section').length"), 1)
            self.assert_layout()
        b.navigate(paper_url + "?mode=direct")
        b.wait("!!document.querySelector('.correct-option')")
        self.assertEqual(b.evaluate("document.querySelectorAll('.paper-practice-form').length"), 0)
        # Enter practice through category, exam, subject, module fallback and
        # difficulty form, preserving the actual server token/selection workflow.
        b.navigate(self.live_server_url + reverse("practice:index"))
        b.evaluate("document.querySelector('.mock-hub-categories a').click()")
        b.wait("location.pathname.endsWith('/ui/')")
        b.evaluate("document.querySelector('.mock-hub-categories a').click()")
        b.wait("location.pathname.endsWith('/civil-services/')")
        b.evaluate("document.querySelector('.mock-hub-categories a').click()")
        b.wait("location.pathname.endsWith('/history/')")
        b.evaluate("document.querySelector('.mock-hub-empty .button').click()")
        b.wait("!!document.querySelector('.practice-difficulty-card')")
        b.evaluate("document.querySelector('input[name=difficulty]').click(); document.querySelector('.practice-difficulty-card button').click()")
        b.wait("!!document.querySelector('.ui-practice-session')")
        session = PracticeSession.objects.get(user=self.user)
        session_url = self.live_server_url + reverse("practice:session", args=[session.pk])
        bilingual = next(row for row in session.questions.select_related('question_revision')
                         if row.question_revision.translations.count() == 2 and any(
                             t.language == 'en' and len(t.question_text) > 200
                             for t in row.question_revision.translations.all()))
        b.navigate(session_url + f"?question={bilingual.display_order}")
        b.wait("!!document.querySelector('.practice-answer')")
        b.evaluate("document.querySelector('.practice-answer .exam-option[data-option=B]').click()")
        b.wait("!!document.querySelector('.practice-reading-feedback.is-incorrect')")
        for width, label in ((1440, "desktop"), (360, "mobile")):
            b.viewport(width)
            b.evaluate("document.querySelector('#practice-question').scrollIntoView()")
            self.assert_layout()
            b.screenshot(self.output / f"practice-feedback-{label}.png")
            b.screenshot(self.output / f"practice-feedback-{label}-question.png", '#practice-question')
            self.assertTrue(b.evaluate("document.querySelector('.exam-paper-solutions details').open"))
        # Next is in normal document flow, following the full explanation.
        self.assertEqual(b.evaluate("getComputedStyle(document.querySelector('.practice-step-nav')).position"), "static")
        if b.evaluate("!!document.querySelector('.practice-step-nav a[href*=question]')"):
            b.evaluate("document.querySelector('.practice-step-nav a[href*=question]').click()")
            b.wait("!!document.querySelector('#practice-question')")
        # Pause/resume must retain feedback and proceed to an unanswered row.
        b.navigate(self.live_server_url + reverse("practice:index"))
        b.wait("!!document.querySelector('#practice-open-heading')")
        b.evaluate("document.querySelector('#practice-open-heading').closest('section').querySelector('.button').click()")
        b.wait("!!document.querySelector('.practice-answer')")
        for row in session.questions.exclude(pk=bilingual.pk):
            b.navigate(session_url + f"?question={row.display_order}")
            b.wait("!!document.querySelector('.practice-answer')")
            b.evaluate("document.querySelector('.practice-answer input[value=A]').focus()")
            b.key(" ", "Space", 32)
            b.wait("!!document.querySelector('.practice-reading-feedback.is-correct')")
            self.assert_layout()
        session.refresh_from_db()
        self.assertEqual(session.status, "completed")
        self.assertEqual(session.questions.filter(is_correct=False).count(), 1)
        b.navigate(self.live_server_url + reverse("practice:summary", args=[session.pk]))
        b.wait("!!document.querySelector('.practice-review-list')")
        self.assertIn("Completed", b.evaluate("document.body.textContent"))
