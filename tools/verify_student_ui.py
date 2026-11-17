"""UI-3 browser audit on disposable data; run StudentUIBrowserTests' three new tests.

python manage.py test tools.verify_student_ui.StudentUIBrowserTests.test_accounts_catalogue_and_preferences tools.verify_student_ui.StudentUIBrowserTests.test_zoomed_exam_and_asset_budget tools.verify_student_ui.StudentUIBrowserTests.test_navigation_asset_failure_falls_back_to_links --noinput
Uses existing headless Edge tooling, with no downloaded browser or JS libraries.
"""
import gzip
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.urls import reverse

from mock_tests.execution import submit_attempt
from mock_tests.services import start_attempt
from practice.services import start_session, submit_answer
from revision.services import set_saved
from tools import verify_learning_ui


class StudentUIBrowserTests(verify_learning_ui.LearningUIBrowserTests):
    def test_navigation_asset_failure_falls_back_to_links(self):
        b = self.browser
        b.viewport(360, 740)
        b.call("Network.enable")
        b.call("Network.setBlockedURLs", urls=["*navigation.js"])
        b.navigate(self.live_server_url + reverse("home"))
        b.wait("document.readyState === 'complete' && !!document.querySelector('#primary-navigation')")
        self.assertFalse(b.evaluate("document.querySelector('#primary-navigation').hidden"))
        self.assertNotEqual(b.evaluate("getComputedStyle(document.querySelector('#primary-navigation')).display"), "none")
        self.assertTrue(b.evaluate("[...document.querySelectorAll('#primary-navigation a')].some(a=>a.pathname === '/practice/')"))
        self.assert_layout()

    def assert_readable_contrast(self):
        failures = self.browser.evaluate("""(() => {
          const rgb = color => color.match(/[\\d.]+/g).slice(0,3).map(Number);
          const luminance = values => values.map(v => {v/=255; return v<=.04045 ? v/12.92 : ((v+.055)/1.055)**2.4;}).reduce((sum,v,i) => sum+v*[.2126,.7152,.0722][i],0);
          const contrast = (a,b) => (Math.max(luminance(a),luminance(b))+.05)/(Math.min(luminance(a),luminance(b))+.05);
          const background = node => {while(node) {const value=getComputedStyle(node).backgroundColor; if(value!=='rgba(0, 0, 0, 0)' && value!=='transparent') return rgb(value); node=node.parentElement;} return [255,255,255];};
          const text = [...document.querySelectorAll('.ui-main h1,.profile-details,.profile-study,.dashboard-stat-card,.dashboard-resume,.ui-main label,.ui-main .button,.ui-main select,.ui-main .muted,.form-errors')].filter(e=>e.getBoundingClientRect().height && contrast(rgb(getComputedStyle(e).color),background(e))<4.5).map(e=>e.className || e.tagName);
          const borders = [...document.querySelectorAll('select,textarea,input:not([type=hidden]):not([type=checkbox]):not([type=radio])')].filter(e=>e.getBoundingClientRect().height && contrast(rgb(getComputedStyle(e).borderTopColor),background(e))<3).map(e=>'border: '+(e.id || e.tagName));
          return [...text,...borders];
        })()""")
        self.assertEqual(failures, [], f"Text contrast below 4.5:1: {failures}")

    def populate_dashboard(self):
        question = self.paper.paper_questions.first().question_revision.question
        set_saved(self.user, question.pk, saved=True)
        finished = start_session(self.user, exam=self.exam, subject=question.subject, token=uuid4())
        for row in finished.questions.all():
            submit_answer(self.user, finished.pk, row.pk, "A")
        start_session(self.user, exam=self.exam, subject=question.subject, token=uuid4())
        submit_attempt(self.user, start_attempt(self.user, self.pattern).pk)
        start_attempt(self.user, self.pattern)

    def test_accounts_catalogue_and_preferences(self):
        self.populate_dashboard()
        b = self.browser
        b.call("Page.addScriptToEvaluateOnNewDocument", source="window.uiCLS=0; new PerformanceObserver(list => list.getEntries().forEach(e => {if(!e.hadRecentInput) window.uiCLS+=e.value;})).observe({type:'layout-shift',buffered:true});")
        pages = ("accounts:profile", "accounts:learning_space", "exams:authorities", "general_questions:index", "previous_year:index")
        measurements = []
        for theme in ("light", "dark", "sepia"):
            b.navigate(self.live_server_url + reverse("accounts:profile"))
            b.wait("!!document.querySelector('#profile-theme')")
            b.evaluate(f"document.querySelector('#profile-theme').value='{theme}'; document.querySelector('#profile-theme').dispatchEvent(new Event('change'))")
            self.assertEqual(b.evaluate("document.querySelector('#reading-theme').value"), theme)
            self.assertTrue(b.evaluate("document.querySelector('[data-theme-status]').textContent.includes('selected')"))
            for width, height in ((1440, 900), (360, 740), (640, 400)):
                b.viewport(width, height)
                for page in pages:
                    b.navigate(self.live_server_url + reverse(page))
                    b.wait("!!document.querySelector('main h1') && document.readyState === 'complete'")
                    self.assert_layout()
                    self.assert_readable_contrast()
                    self.assertEqual(b.evaluate("document.documentElement.dataset.theme"), theme)
                    self.assertEqual(b.evaluate("document.querySelectorAll('h1').length"), 1)
                    self.assertTrue(b.evaluate("[...document.querySelectorAll('select,input:not([type=hidden])')].every(e => e.labels.length > 0)"))
                    self.assertTrue(b.evaluate("[...document.querySelectorAll('link[rel=stylesheet],script[src]')].every(e => new URL(e.href || e.src).origin === location.origin)"))
                    measurements.append(b.evaluate("window.uiCLS"))
        self.assertLess(max(measurements), .1)
        b.viewport(360, 740)
        b.navigate(self.live_server_url + reverse("accounts:profile"))
        b.wait("!!document.querySelector('#profile-theme')")
        b.evaluate("document.querySelector('.menu-toggle').click()")
        self.assertFalse(b.evaluate("document.querySelector('#primary-navigation').hidden"))
        b.key("Escape", "Escape", 27)
        # The disclosure closes when Escape is sent from its focusable toggle.
        b.evaluate("document.querySelector('.menu-toggle').focus()")
        b.key("Escape", "Escape", 27)
        self.assertTrue(b.evaluate("document.querySelector('#primary-navigation').hidden"))
        b.key("Tab", "Tab", 9)
        b.evaluate("document.querySelector('#profile-theme').focus()")
        self.assertEqual(b.evaluate("getComputedStyle(document.activeElement).outlineStyle"), "solid")
        b.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
        b.evaluate("document.querySelector('#profile-theme').value='system'; document.querySelector('#profile-theme').dispatchEvent(new Event('change'))")
        self.assertEqual(b.evaluate("document.documentElement.dataset.theme"), "dark")
        b.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
        b.wait("document.documentElement.dataset.theme === 'light'")
        b.evaluate("Storage.prototype.setItem=()=>{throw new Error('Storage unavailable in UI test')}; document.querySelector('#profile-theme').value='sepia'; document.querySelector('#profile-theme').dispatchEvent(new Event('change'))")
        self.assertEqual(b.evaluate("document.documentElement.dataset.theme"), "sepia")
        self.assertTrue(b.evaluate("document.querySelector('[data-theme-status]').textContent.includes('storage unavailable')"))
        b.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
        self.assertEqual(b.evaluate("getComputedStyle(document.querySelector('.profile-study .button')).transitionDuration"), "0s")
        b.call("Network.clearBrowserCookies")
        b.navigate(self.live_server_url + reverse("accounts:login"))
        b.wait("!!document.querySelector('input[type=password]')")
        b.evaluate("document.querySelector('.password-toggle').click()")
        self.assertEqual(b.evaluate("document.querySelector('input[name=password]').type"), "text")
        b.evaluate("document.querySelector('.password-toggle').click(); document.querySelector('[name=username]').value='unknown-ui-user'; document.querySelector('[name=password]').value='invalid-ui-test-password'; document.querySelector('button[type=submit].button-primary').click()")
        b.wait("!!document.querySelector('.form-errors')")
        self.assert_layout()
        self.assert_readable_contrast()
        print(f"UI-3: max CLS {max(measurements):.4f}; {len(measurements)} themed viewport/page checks.")

    def test_zoomed_exam_and_asset_budget(self):
        attempt = start_attempt(self.user, self.pattern)
        b = self.browser
        b.navigate(self.live_server_url + reverse("mock_tests:attempt_detail", args=[attempt.pk]))
        b.wait("!!document.querySelector('#mock-timer')")
        # 1280x800 at 200% zoom has a 640x400 CSS-pixel layout viewport.
        b.viewport(640, 400)
        self.assert_layout()
        b.evaluate("document.querySelector('.mock-question .exam-option:last-child').scrollIntoView({block:'center'})")
        self.assertEqual(b.evaluate("getComputedStyle(document.querySelector('.mock-time-block')).position"), "fixed")
        self.assertLess(b.evaluate("document.querySelector('.mock-time-block').getBoundingClientRect().bottom"), 100)
        self.assertFalse(b.evaluate("document.body.textContent.includes('Correct answer:')"))
        b.key("Tab", "Tab", 9)
        b.evaluate("document.querySelector('.mock-question input[value=A]').focus()")
        b.key(" ", "Space", 32)
        b.wait("document.querySelector('#mock-save-status').textContent === 'All changes saved.'")
        self.reload_page()
        b.wait("!!document.querySelector('.mock-question input[value=A]:checked')")
        b.navigate(self.live_server_url + reverse("home"))
        b.wait("!!document.querySelector('#home-heading')")
        sources = b.evaluate("[...document.querySelectorAll('link[rel=stylesheet],script[src]')].map(e => new URL(e.href || e.src).pathname)")
        self.assertEqual(len(sources), 4)
        self.assertFalse(any('student.js' in source or 'bookmarks.css' in source for source in sources))
        css = (Path(settings.BASE_DIR) / 'static/css/tailwind.css').read_bytes()
        self.assertLessEqual(len(gzip.compress(css, mtime=0)), 23082)  # UI-2 measured baseline.
        self.assertTrue(b.evaluate("performance.getEntriesByType('resource').filter(e => ['script','link'].includes(e.initiatorType)).every(e => e.duration < 2000)"))
