from html.parser import HTMLParser

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.html import strip_tags
from exams.models import Exam, ExamAuthority


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.module_cards = []

    def handle_starttag(self, tag, attrs):
        if tag == "form":
            self.forms.append(dict(attrs))
        if tag == "article" and "module-card" in dict(attrs).get("class", "").split():
            self.module_cards.append(dict(attrs))


class NavigationTests(TestCase):
    def test_home_keeps_dynamic_categories_and_active_exam_links(self):
        authority = ExamAuthority.objects.create(name="WBPSC", code="PC", slug="public-commission")
        exam = Exam.objects.create(authority=authority, name="Clerkship", code="CL", slug="clerkship")
        Exam.objects.create(authority=authority, name="Hidden Exam", code="H", slug="hidden", is_active=False)
        ExamAuthority.objects.create(name="Hidden Authority", code="HA", slug="hidden-authority", is_active=False)
        response = self.client.get(reverse("home"))
        self.assertContains(response, authority.name)
        self.assertContains(response, exam.name)
        self.assertContains(response, reverse("exams:exam_detail", args=[authority.slug, exam.slug]))
        self.assertNotContains(response, "Hidden Exam")
        self.assertNotContains(response, "Hidden Authority")
        self.assertContains(response, '<h1 id="home-heading">')
        self.assertContains(response, 'aria-labelledby="home-heading"')

    def test_public_pages_and_guest_navigation(self):
        for route in ("home", "exams:authorities", "previous_year:index", "accounts:login", "accounts:register"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                visible_text = " ".join(strip_tags(response.content.decode()).split())
                for label in ("All Exams", "Previous-Years", "Previous Year Papers", "Mock Tests", "Practice Sets", "Login", "Register"):
                    self.assertIn(label, visible_text)
                self.assertNotContains(response, 'class="library-menu"')
                self.assertNotContains(response, '>Logout<')
                self.assertNotContains(response, '>Profile<')
                self.assertNotContains(response, 'href="#"')

    def test_protected_routes_preserve_next_with_query(self):
        for route in ("mock_tests:index", "practice:index", "accounts:profile"):
            with self.subTest(route=route):
                destination = reverse(route) + "?page=2"
                response = self.client.get(destination)
                self.assertRedirects(response, reverse("accounts:login") + "?next=" + reverse(route) + "%3Fpage%3D2")

    def test_authenticated_navigation_and_placeholders(self):
        user = get_user_model().objects.create_user(username="learner", email="hidden@example.test")
        self.client.force_login(user)
        for route in ("home", "exams:authorities", "previous_year:index", "mock_tests:index", "practice:index", "accounts:profile"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '>Profile<')
                self.assertContains(response, '>Logout<')
                self.assertNotContains(response, '>Login<')
                self.assertNotContains(response, '>Register<')
                if route != "accounts:profile":
                    self.assertNotContains(response, user.email)
                markup = FormParser()
                markup.feed(response.content.decode())
                self.assertTrue(any(form.get("action") == reverse("accounts:logout") and form.get("method", "get").lower() == "post" for form in markup.forms))
                self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_home_cards_and_accessible_navigation_markup(self):
        response = self.client.get(reverse("home"))
        markup = FormParser()
        markup.feed(response.content.decode())
        self.assertEqual(len(markup.module_cards), 3)
        self.assertNotContains(response, 'Explore General Questions')
        html = response.content.decode()
        self.assertLess(html.index('href="/static/css/site.css"'), html.index('href="/static/css/tailwind.css"'))
        self.assertContains(response, 'href="#main-content"')
        self.assertContains(response, 'aria-controls="primary-navigation"')
        self.assertContains(response, 'aria-label="Main navigation"')
        self.assertContains(response, 'src="/static/js/navigation.js" defer')

    def test_manage_menu_is_staff_only_and_all_exams_follows_practice(self):
        for username, staff in (("student-menu", False), ("admin-menu", True)):
            user = get_user_model().objects.create_user(username=username, is_staff=staff)
            self.client.force_login(user)
            html = self.client.get(reverse("home")).content.decode()
            header = html.split('<nav id="primary-navigation"', 1)[1].split('</nav>', 1)[0]
            self.assertLess(header.index('>Practice Sets</a>'), header.index('>All Exams</a>'))
            self.assertIn('>Previous-Years</a>', header)
            self.assertNotIn('Question Library', header)
            if staff:
                self.assertIn('>Manage ', header)
                self.assertIn(reverse("admin:index"), header)
            else:
                self.assertNotIn('class="library-menu"', header)

    def test_footer_uses_contact_and_legal_placeholders(self):
        html = self.client.get(reverse("home")).content.decode()
        footer = html.split('<footer', 1)[1].split('</footer>', 1)[0]
        for label in ("All Exams", "Contact us", "Social media links", "Legal &amp; privacy", "Terms &amp; Conditions", "Data Privacy Policy", "Cancellation &amp; Refund Policy"):
            self.assertIn(label, footer)
        self.assertEqual(footer.count('Coming soon'), 5)
        for removed in ('Go further', 'Your space', 'Plans &amp; pricing', 'Question Library', 'Exam Authorities'):
            self.assertNotIn(removed, footer)
        self.assertNotIn('href="#"', footer)
        catalogue = self.client.get(reverse("exams:authorities"))
        self.assertContains(catalogue, '<h1 class="tw:sr-only">All Exams</h1>')
        self.assertNotContains(catalogue, 'FIND YOUR FOCUS')
        self.assertContains(catalogue, 'Filter exam categories')
        self.assertNotContains(catalogue, 'Exam Authorities')

    def test_previous_year_browsing_does_not_offer_test_controls(self):
        response = self.client.get(reverse("previous_year:index"))
        self.assertContains(response, "No published papers are available yet.")
        # The shared appearance selector is unrelated to paper/test configuration.
        self.assertContains(response, '<select id="reading-theme"', count=1)
        self.assertNotContains(response, '<select name=')

    def test_theme_and_bilingual_homepage_contract(self):
        response = self.client.get(reverse("home"))
        html = response.content.decode()
        self.assertLess(html.index('src="/static/js/theme.js"'), html.index('href="/static/css/site.css"'))
        for theme in ("system", "light", "dark", "sepia"):
            self.assertContains(response, f'<option value="{theme}">')
        self.assertContains(response, 'lang="bn"')
        self.assertContains(response, "বাংলা")
        self.assertNotContains(response, "Continue learning")
        user = get_user_model().objects.create_user(username="resume-learner")
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("home")), reverse("accounts:learning_space"))
