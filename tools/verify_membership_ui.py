"""Opt-in Edge checks: python manage.py test tools.verify_membership_ui --noinput.

Uses disposable test data and an isolated headless browser; no runtime records.
"""
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse

from tools.exam_browser import ExamBrowser


class MembershipBrowserTests(StaticLiveServerTestCase):
    def test_module_discovery_and_setup(self):
        from practice.tests import PracticeFixture
        from mock_tests.models import ExamPattern, ExamPatternSection
        from mock_tests.services import activate_pattern
        from mock_tests.testing import premium_user

        PracticeFixture.setUpTestData.__func__(type(self))
        PracticeFixture.question(self)
        premium_user(self.user)
        pattern = ExamPattern.objects.create(exam=self.exam, name="Demo test format",
            duration_minutes=30, total_questions=1, total_marks=1)
        ExamPatternSection.objects.create(pattern=pattern, name="Mathematics",
            language_mode="en", question_count=1, display_order=1)
        activate_pattern(pattern)
        self.client.force_login(self.user)
        browser = ExamBrowser()
        self.addCleanup(browser.close)
        browser.call("Network.setCookie", name=settings.SESSION_COOKIE_NAME,
            value=self.client.cookies[settings.SESSION_COOKIE_NAME].value, url=self.live_server_url)
        output = Path(settings.BASE_DIR) / "docs/screenshots/modules"
        output.mkdir(parents=True, exist_ok=True)
        pages = [("practice:index", []), ("mock_tests:index", []),
            ("practice:subjects", [self.authority.slug, self.exam.slug]),
            ("practice:configure", [self.authority.slug, self.exam.slug, self.subject.slug]),
            ("practice:difficulty", [self.authority.slug, self.exam.slug, self.subject.slug]),
            ("mock_tests:patterns", [self.authority.slug, self.exam.slug]),
            ("mock_tests:start", [pattern.pk]), ("previous_year:index", [])]
        for width in (1440, 390, 320):
            browser.viewport(width, 1000)
            for name, args in pages:
                browser.navigate(self.live_server_url + reverse(name, args=args))
                browser.wait("!document.querySelector('#reading-theme').disabled")
                self.assertTrue(browser.evaluate("!!document.querySelector('.mock-hub,.ui-discovery')"), name)
                for theme in ("light", "dark", "sepia"):
                    browser.evaluate("(() => {let s=document.querySelector('#reading-theme'); s.value='" + theme + "'; s.dispatchEvent(new Event('change'));})()")
                    self.assertTrue(browser.evaluate("document.documentElement.scrollWidth <= innerWidth"), (name, width, theme))
                browser.evaluate("document.querySelector('#reading-theme').value='light'; document.querySelector('#reading-theme').dispatchEvent(new Event('change')); scrollTo(0,0)")
                if width != 320:
                    browser.screenshot(output / (name.replace(":", "-") + "-" + str(width) + ".png"))

    def test_shell_forms_and_pricing(self):
        browser = ExamBrowser()
        self.addCleanup(browser.close)
        output = Path(settings.BASE_DIR) / "docs/screenshots/membership"
        output.mkdir(parents=True, exist_ok=True)
        for width in (1440, 390, 320):
            browser.viewport(width, 1000)
            for name in ("home", "accounts:register", "accounts:login", "billing:pricing",
                         "mock_tests:index", "practice:index", "previous_year:index"):
                browser.navigate(self.live_server_url + reverse(name))
                browser.wait("!document.querySelector('#reading-theme').disabled")
                if name == "home":
                    self.assertTrue(browser.evaluate("document.querySelector('#home-heading').getBoundingClientRect().height > 0"))
                for theme in ("light", "dark", "sepia"):
                    browser.evaluate("(() => {let s=document.querySelector('#reading-theme'); s.value='" + theme + "'; s.dispatchEvent(new Event('change'));})()")
                    self.assertTrue(browser.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, name, theme))
                if width < 1000:
                    browser.evaluate("document.querySelector('.menu-toggle').click()")
                    self.assertTrue(browser.evaluate("!document.querySelector('#primary-navigation').hidden"))
                    self.assertTrue(browser.evaluate("document.querySelector('.shell-plans-link').getBoundingClientRect().width > 0"))
                    browser.evaluate("document.querySelector('.menu-toggle').click()")
                if name == "accounts:register":
                    self.assertTrue(browser.evaluate("[...document.querySelectorAll('.auth-form-card input:not([type=hidden])')].every(e => e.value === '')"))
                browser.evaluate("document.querySelector('#reading-theme').value='light'; document.querySelector('#reading-theme').dispatchEvent(new Event('change'))")
                browser.evaluate("scrollTo(0,0); new Promise(resolve => setTimeout(resolve, 250))")
                if width != 320 and name in ("home", "accounts:register", "billing:pricing"):
                    browser.screenshot(output / (name.replace(":", "-") + "-" + str(width) + ".png"))
