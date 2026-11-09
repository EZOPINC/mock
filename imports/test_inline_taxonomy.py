from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from exams.models import Subject, Topic
from . import staging
from .permissions import REQUIRED_PERMISSIONS
from .tests import ImportFixture, values
from .validation import validate


class InlineTaxonomyTests(ImportFixture):
    def setUp(self):
        super().setUp()
        self.data_file = self.data([values(subject="History", topic="Ancient")])
        self.url = reverse("imports:preview", args=[self.data_file["token"]])
        self.client.force_login(self.user)

    def post(self, action="add_subject", **changes):
        return self.client.post(self.url, {"action": action, "version": staging.digest(self.data_file),
            "new_subject-name": "History", "new_subject-code": "HIST", "new_subject-slug": "history", **changes})

    def test_inline_creation_resolves_subject_then_topic_without_import(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Add subject and revalidate")
        self.assertContains(response, "Add topic and revalidate")
        self.assertRedirects(self.post(), self.url)
        subject = Subject.objects.get(code="HIST")
        response = self.post("add_topic", **{"new_topic-subject": subject.pk, "new_topic-name": "Ancient", "new_topic-slug": "ancient"})
        self.assertRedirects(response, self.url)
        result = validate(staging.load(self.data_file["token"], self.user))
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["rows"][0]["topic"], Topic.objects.get(subject=subject))
        self.assertEqual(self.paper.paper_questions.count(), 0)

    def test_invalid_fields_and_duplicate_names_stay_on_preview(self):
        response = self.post(**{"new_subject-code": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.assertFalse(Subject.objects.filter(name="History").exists())
        response = self.post(**{"new_subject-name": "ENGLISH"})
        self.assertContains(response, "already exists")
        self.assertFalse(Subject.objects.filter(code="HIST").exists())

    def test_wrong_subject_duplicate_slug_and_invalid_subject_are_rejected(self):
        for changes in ({"new_topic-subject": 999999}, {"new_topic-slug": "grammar"}, {"new_topic-name": "GRAMMAR"}):
            fields = {"new_topic-subject": self.subject.pk, "new_topic-name": "New topic", "new_topic-slug": "new-topic"} | changes
            response = self.post("add_topic", **fields)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["topic_form"].errors)
        self.assertEqual(Topic.objects.count(), 1)

    def test_missing_permission_hides_forms_and_blocks_forged_post(self):
        staff = get_user_model().objects.create_user(username="import-only", is_staff=True)
        names = set(REQUIRED_PERMISSIONS) | {"previous_year.add_previousyearpaper", "previous_year.add_paperquestion"}
        for name in names:
            app, codename = name.split(".")
            staff.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))
        self.data_file["owner"] = staff.pk
        staging.save(self.data_file)
        self.client.force_login(staff)
        self.assertNotContains(self.client.get(self.url), "Add subject and revalidate")
        self.assertEqual(self.post().status_code, 403)
        self.assertFalse(Subject.objects.filter(code="HIST").exists())

    def test_ownership_version_and_csrf_checks_prevent_creation(self):
        self.post(version="stale")
        self.assertFalse(Subject.objects.filter(code="HIST").exists())
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(self.url, {"action": "add_subject"}).status_code, 403)
        other = get_user_model().objects.create_superuser(username="other-admin")
        self.client.force_login(other)
        self.assertEqual(self.post().status_code, 404)
        self.assertFalse(Subject.objects.filter(code="HIST").exists())
