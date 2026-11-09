from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from exams.models import Exam, ExamAuthority


class ModernHomepageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.psc = ExamAuthority.objects.create(name="WBPSC", code="wbpsc", slug="wbpsc")
        cls.police = ExamAuthority.objects.create(name="WBP/KP", code="wbp-kp", slug="wbpkp")
        cls.ssc = ExamAuthority.objects.create(name="SSC", code="ssc", slug="ssc")
        for authority, names in (
            (cls.psc, ["Panchayat", "School SI", "ICDS", "IDO", "Clerkship", "Miscellaneous", "WBCS"]),
            (cls.police, ["Lady Constable", "KP Constable", "KPSI", "WBP Constable", "WBPSI"]),
            (cls.ssc, ["SLST", "Upper Primary TET", "Primary TET"]),
        ):
            for index, name in enumerate(names):
                Exam.objects.create(authority=authority, name=name, code=str(index), slug=f"exam-{index}")
        cls.unlisted = Exam.objects.create(authority=cls.psc, name="Other exam", code="other", slug="other")

    def test_homepage_order_dynamic_urls_and_hero_actions(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, '<h1 id="home-heading">', count=1)
        authorities = response.context["authorities"]
        self.assertEqual([item.pk for item in authorities], [self.psc.pk, self.police.pk, self.ssc.pk])
        expected = [
            ["WBCS", "Miscellaneous", "Clerkship", "IDO", "ICDS", "School SI", "Panchayat"],
            ["WB SI", "WB Constable", "KP SI", "KP Constable", "Lady Constable"],
            ["Primary TET", "Upper Primary TET", "SLST"],
        ]
        for authority, labels in zip(authorities, expected):
            self.assertEqual([exam.homepage_label for exam in authority.available_exams], labels)
            for exam in authority.available_exams:
                self.assertContains(response, reverse("exams:exam_detail", args=[authority.slug, exam.slug]))
        for name in ("mock_tests:index", "practice:index", "previous_year:index"):
            self.assertContains(response, reverse(name))
        self.assertNotContains(response, "Other exam")

    def test_unavailable_exams_and_empty_category(self):
        self.ssc.exams.update(is_active=False)
        self.psc.exams.filter(name="WBCS").update(is_active=False)
        response = self.client.get(reverse("home"))
        self.assertEqual(len(response.context["authorities"]), 3)
        self.assertNotContains(response, ">WBCS ")
        self.assertContains(response, "No exams are available for this authority yet.")

    def test_homepage_presentation_does_not_change_other_discovery(self):
        self.client.get(reverse("home"))
        response = self.client.get(reverse("exams:exam_list", args=[self.psc.slug]))
        self.assertContains(response, self.unlisted.name)
        self.assertEqual(self.police.exams.get(name="WBPSI").name, "WBPSI")

    def test_empty_homepage_and_authenticated_navigation(self):
        ExamAuthority.objects.update(is_active=False)
        self.assertContains(self.client.get(reverse("home")), "No exam authorities are available yet.")
        user = get_user_model().objects.create_user(username="homepage-student")
        self.client.force_login(user)
        response = self.client.get(reverse("home"))
        self.assertContains(response, reverse("accounts:learning_space"))
        self.assertContains(response, reverse("accounts:profile"))
