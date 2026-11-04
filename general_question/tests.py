from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

from general_question.services import batch_questions, fingerprint, transition_batch
from imports.services import confirm_import
from .models import GeneralQuestionBatch
from imports.models import ImportBatch
from imports.tests import ImportFixture, values
from questions.models import Question
from questions.services import create_revision, mark_reviewed, publish_question


class GeneralModuleTests(ImportFixture):
    def setUp(self):
        super().setUp()
        data = self.data([values(question_number="1", question_text="Original live content", source_document="private-file.pdf"),
                          values(question_number="2", question_text="বাংলা প্রশ্ন", language="bn")])
        data["selection"] = {"import_type": "general", "exam_ids": [self.exam.pk], "exam_mapping": "selected"}
        self.batch = confirm_import(data, self.user)

    def state(self):
        return fingerprint(list(batch_questions(self.batch)))

    def review(self):
        return transition_batch(self.batch.pk, self.user, "review", self.state())

    def publish(self):
        self.review()
        return transition_batch(self.batch.pk, self.user, "publish", self.state())

    def test_draft_collection_hidden_from_guests(self):
        response = self.client.get(reverse("general_questions:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No published general questions")
        self.assertNotContains(response, "Original live content")
        self.assertEqual(self.client.get(reverse("general_questions:collection", args=[self.batch.pk])).status_code, 404)

    def test_batch_review_then_publish_reuses_existing_services(self):
        self.assertEqual(self.review(), 2)
        self.assertFalse(Question.objects.filter(publication_status="published").exists())
        self.assertEqual(transition_batch(self.batch.pk, self.user, "publish", self.state()), 2)
        self.assertEqual(Question.objects.filter(publication_status="published").count(), 2)

    def test_unreviewed_or_stale_batch_cannot_publish(self):
        with self.assertRaises(ValidationError):
            transition_batch(self.batch.pk, self.user, "publish", self.state())
        old = self.state()
        self.review()
        with self.assertRaises(ValidationError):
            transition_batch(self.batch.pk, self.user, "publish", old)

    def test_batch_publication_rolls_back_on_late_failure(self):
        self.review()
        original = publish_question
        count = 0
        def fail_second(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise ValidationError("Invalid second question")
            return original(*args, **kwargs)
        with patch("general_question.services.publish_question", side_effect=fail_second), self.assertRaises(ValidationError):
            transition_batch(self.batch.pk, self.user, "publish", self.state())
        self.assertFalse(Question.objects.filter(publication_status="published").exists())

    def test_public_solution_and_filtering_do_not_expose_private_metadata(self):
        self.publish()
        response = self.client.get(reverse("general_questions:collection", args=[self.batch.pk]))
        for text in ("Original live content", "বাংলা প্রশ্ন", "Correct answer: A", "One", "Four"):
            self.assertContains(response, text)
        for private in (self.batch.filename, "private-file.pdf", self.user.email):
            self.assertNotContains(response, private)
        filtered = self.client.get(reverse("general_questions:collection", args=[self.batch.pk]), {"language": "bn", "subject": self.subject.pk, "exam": self.exam.pk})
        self.assertContains(filtered, "বাংলা প্রশ্ন")
        self.assertNotContains(filtered, "Original live content")

    def test_working_draft_does_not_change_public_content(self):
        self.publish()
        question = batch_questions(self.batch).first()
        revision = question.current_revision
        content = {field: getattr(revision, field) for field in ("language", "question_text", "option_a", "option_b", "option_c", "option_d", "correct_answer", "explanation")}
        content["question_text"] = "Private working draft"
        create_revision(question, **content)
        response = self.client.get(reverse("general_questions:collection", args=[self.batch.pk]))
        self.assertContains(response, "Original live content")
        self.assertNotContains(response, "Private working draft")
        with self.assertRaises(ValidationError):
            transition_batch(self.batch.pk, self.user, "publish", self.state())

    def test_inactive_exam_questions_hidden_and_invalid_filters_safe(self):
        self.publish()
        self.exam.is_active = False
        self.exam.save()
        self.assertEqual(self.client.get(reverse("general_questions:collection", args=[self.batch.pk])).status_code, 404)
        response = self.client.get(reverse("general_questions:index"), {"exam": "invalid"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Original live content")

    def test_staff_permissions_and_csrf_protect_management(self):
        url = reverse("general_questions:manage_batch", args=[self.batch.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(url).status_code, 403)
        with self.assertRaises(PermissionDenied):
            transition_batch(self.batch.pk, staff, "review", self.state())
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(url, {"action": "review"}).status_code, 403)

    def test_staff_can_review_and_publish_all_via_signed_forms(self):
        self.client.force_login(self.user)
        url = reverse("general_questions:manage_batch", args=[self.batch.pk])
        for action in ("review", "publish"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            snapshot = response.context["snapshot"]
            response = self.client.post(url, {"action": action, "snapshot": snapshot}, follow=True)
            self.assertEqual(response.status_code, 200)
        self.assertEqual(Question.objects.filter(publication_status="published").count(), 2)
        self.assertEqual(self.client.get(reverse("general_questions:manage")).status_code, 200)

    def test_forged_snapshot_does_not_review_questions(self):
        self.client.force_login(self.user)
        self.client.post(reverse("general_questions:manage_batch", args=[self.batch.pk]), {"action": "review", "snapshot": "forged"})
        self.assertFalse(Question.objects.filter(review_status="reviewed").exists())

    def test_dedicated_admin_app_lists_general_uploads_only(self):
        previous_batch = confirm_import(self.data([values(question_number="P1")]), self.user)
        self.client.force_login(self.user)
        self.assertTrue(GeneralQuestionBatch._meta.proxy)
        self.assertIs(GeneralQuestionBatch._meta.concrete_model, ImportBatch)
        self.assertEqual(GeneralQuestionBatch.objects.count(), 1)
        response = self.client.get(reverse("admin:general_question_generalquestionbatch_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([obj.pk for obj in response.context["cl"].queryset], [self.batch.pk])
        self.assertContains(self.client.get(reverse("admin:index")), "General Questions")
        self.assertRedirects(self.client.get(reverse("admin:general_question_generalquestionbatch_change", args=[self.batch.pk])), reverse("general_questions:manage_batch", args=[self.batch.pk]))
        self.assertEqual(self.client.get(reverse("admin:general_question_generalquestionbatch_change", args=[previous_batch.pk])).status_code, 404)

    def test_existing_batch_manager_permissions_work_in_new_admin_app(self):
        staff = get_user_model().objects.create_user(username="manager", is_staff=True)
        staff.user_permissions.add(
            Permission.objects.get(content_type__app_label="imports", codename="view_importbatch"),
            Permission.objects.get(content_type__app_label="questions", codename="change_question"),
        )
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("admin:general_question_generalquestionbatch_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("general_questions:manage_batch", args=[self.batch.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:general_question_generalquestionbatch_add")).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:general_question_generalquestionbatch_delete", args=[self.batch.pk]), {"post": "yes"}).status_code, 403)

    def test_admin_list_actions_review_and_publish_entire_batch(self):
        self.client.force_login(self.user)
        url = reverse("admin:general_question_generalquestionbatch_changelist")
        response = self.client.get(url)
        self.assertContains(response, "review_selected_batches")
        self.assertContains(response, "publish_selected_batches")
        for action, label in (("review_selected_batches", "marked reviewed"), ("publish_selected_batches", "published")):
            response = self.client.post(url, {"action": action, "_selected_action": [self.batch.pk]}, follow=True)
            self.assertContains(response, f"2 questions {label}.")
        self.assertEqual(Question.objects.filter(review_status="reviewed", publication_status="published").count(), 2)

    def test_admin_list_publish_rejects_unreviewed_batch(self):
        self.client.force_login(self.user)
        url = reverse("admin:general_question_generalquestionbatch_changelist")
        response = self.client.post(url, {"action": "publish_selected_batches", "_selected_action": [self.batch.pk]}, follow=True)
        self.assertContains(response, "Review the current revision before publishing")
        self.assertFalse(Question.objects.filter(publication_status="published").exists())

    def test_admin_batch_actions_require_permissions_and_csrf(self):
        url = reverse("admin:general_question_generalquestionbatch_changelist")
        data = {"action": "review_selected_batches", "_selected_action": [self.batch.pk]}
        staff = get_user_model().objects.create_user(username="unauthorized", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.post(url, data).status_code, 403)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(url, data).status_code, 403)
        self.assertFalse(Question.objects.filter(review_status="reviewed").exists())
