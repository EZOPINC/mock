from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

from exams.models import Chapter, Module, Submodule, Topic
from general_question.services import batch_questions, fingerprint, transition_batch
from imports.services import confirm_import
from .models import GeneralQuestionBatch
from imports.models import ImportBatch
from imports.tests import ImportFixture, values
from questions.models import Question
from questions.services import add_translation, create_revision, mark_reviewed, publish_question
from questions.tagging import set_question_topics


class GeneralModuleTests(ImportFixture):
    def test_dashboard_counts_module_and_chapter_matches_once_per_question(self):
        module = Module.objects.create(subject=self.subject, name="Grammar module", slug="grammar-module")
        submodule = Submodule.objects.create(module=module, name="Usage", slug="usage")
        chapter = Chapter.objects.create(submodule=submodule, name="Verbs", slug="verbs")
        direct_chapter = Chapter.objects.create(module=module, name="Articles", slug="articles")
        direct = Topic.objects.create(module=module, name="Direct topic", slug="direct-topic")
        nested = Topic.objects.create(chapter=chapter, name="Nested topic", slug="nested-topic")
        secondary = Topic.objects.create(chapter=chapter, name="Secondary topic", slug="secondary-topic")
        article = Topic.objects.create(chapter=direct_chapter, name="Article topic", slug="article-topic")
        first, second = batch_questions(self.batch)
        set_question_topics(first, [direct.pk, nested.pk, secondary.pk], primary_topic_id=direct.pk)
        set_question_topics(second, [article.pk], primary_topic_id=article.pk)
        self.client.force_login(self.user)
        dashboard = self.client.get(reverse("general_questions:dashboard"))
        self.assertEqual(dict(dashboard.context["modules"]), {module: 2})
        self.assertEqual(dict(dashboard.context["chapters"]), {chapter: 1, direct_chapter: 1})
        queue = reverse("general_questions:review_queue")
        for field, node, total in (("module", module, 2), ("chapter", chapter, 1)):
            self.assertContains(dashboard, f'{queue}?{field}={node.pk}')
            response = self.client.get(queue, {field: node.pk})
            self.assertEqual(response.context["page"].paginator.count, total)

    def test_fixed_edition_slots_for_single_language_and_bilingual_questions(self):
        self.client.force_login(self.user)
        self.publish()
        url = reverse("general_questions:collection", args=[self.batch.pk])
        response = self.client.get(url)
        self.assertContains(response, 'data-missing-edition="en"', count=1)
        self.assertContains(response, 'data-missing-edition="bn"', count=1)
        self.assertContains(response, 'class="exam-option"', count=8)
        self.assertContains(response, 'aria-label="English version"', count=2)
        self.assertContains(response, 'aria-label="Bengali version"', count=2)
        question = batch_questions(self.batch).order_by('pk').first()
        add_translation(question, language="bn", question_text="চিরস্থায়ী বন্দোবস্ত কত সালে চালু হয়?",
                        option_a="১৭৯৩", option_b="১৮৫৭", option_c="১৯০৫", option_d="১৯৪৭", explanation="বাংলা ব্যাখ্যা")
        publish_question(mark_reviewed(question))
        response = self.client.get(url)
        self.assertNotContains(response, 'data-missing-edition="bn"')
        self.assertContains(response, 'data-missing-edition="en"', count=1)
        self.assertContains(response, "বাংলা ব্যাখ্যা")
        filtered = self.client.get(url, {'language': 'en'})
        self.assertContains(filtered, "চিরস্থায়ী বন্দোবস্ত কত সালে চালু হয়?")
        self.assertNotContains(filtered, 'data-missing-edition=')

    def test_staff_review_keeps_empty_slots_for_missing_working_translations(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('general_questions:manage_batch', args=[self.batch.pk]))
        self.assertContains(response, 'data-missing-edition="en"', count=1)
        self.assertContains(response, 'data-missing-edition="bn"', count=1)
        self.assertContains(response, 'name="snapshot"')

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

    def test_collection_routes_require_staff_permissions(self):
        index = reverse("general_questions:index")
        collection = reverse("general_questions:collection", args=[self.batch.pk])
        self.assertEqual(self.client.get(index).status_code, 302)
        self.assertEqual(self.client.get(collection).status_code, 302)
        self.client.force_login(self.user)
        response = self.client.get(index)
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
        self.client.force_login(self.user)
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
        self.client.force_login(self.user)
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
        self.client.force_login(self.user)
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

    def test_dashboard_editor_and_session_selection(self):
        self.client.force_login(self.user)
        dashboard = self.client.get(reverse("general_questions:dashboard"))
        self.assertEqual(dashboard.context["counts"]["pending"], 2)
        self.assertEqual(list(dashboard.context["exams"])[0]["total"], 2)
        queue = reverse("general_questions:review_queue")
        self.assertEqual(self.client.get(queue, {"language": "bn"}).context["page"].paginator.count, 1)
        first, second = list(batch_questions(self.batch))
        self.publish()
        first.refresh_from_db()
        live = first.published_revision_id
        editor = reverse("general_questions:review_question", args=[first.pk])
        response = self.client.get(editor)
        data = response.context["edit"].initial | {
            "question_action": "save", "revision_snapshot": response.context["revision_snapshot"],
            "question_text_en": "Revised working content", "question_kind": "logical", "topic": self.topic.pk,
        }
        data = {key: value for key, value in data.items() if value is not None}
        self.assertEqual(self.client.post(editor, data).status_code, 302)
        first.refresh_from_db()
        self.assertEqual(first.current_revision.question_text, "Revised working content")
        self.assertEqual(first.published_revision_id, live)
        self.assertEqual(first.topic_id, self.topic.pk)
        self.assertContains(self.client.post(editor, data), "changed or expired")
        for question in (first, second):
            editor = reverse("general_questions:review_question", args=[question.pk])
            response = self.client.get(editor)
            self.assertEqual(self.client.post(editor, {
                "revision_snapshot": response.context["revision_snapshot"], "question_action": "select",
            }).status_code, 302)
        self.assertEqual(len(self.client.get(queue, {"selected": 1}).context["selected"]), 2)
        for action in ("review", "publish"):
            self.assertEqual(self.client.post(queue, {"selection_action": action}).status_code, 302)
        first.refresh_from_db()
        self.assertEqual(first.current_revision_id, first.published_revision_id)

    def test_edited_previous_year_import_can_publish_its_draft_paper(self):
        from previous_year.services import publish_paper

        batch = confirm_import(self.data([values(question_number="3")]), self.user)
        row = batch.paper.paper_questions.get()
        question = row.question
        original_id = row.question_revision_id
        self.client.force_login(self.user)
        editor = reverse("general_questions:review_question", args=[question.pk])
        queue = reverse("general_questions:review_queue")
        dashboard = self.client.get(reverse("general_questions:dashboard"))
        self.assertEqual(dashboard.context["counts"]["general"], 2)
        self.assertEqual(dashboard.context["counts"]["previous_year"], 1)
        self.assertEqual(list(dashboard.context["years"]), [{"paper__year": batch.paper.year, "total": 1}])
        for filters, count in (({"source": "general"}, 2), ({"source": "previous_year"}, 1), ({"year": batch.paper.year}, 1)):
            self.assertEqual(self.client.get(queue, filters).context["page"].paginator.count, count)
        response = self.client.get(editor)
        data = response.context["edit"].initial | {
            "question_action": "save", "revision_snapshot": response.context["revision_snapshot"],
            "question_text_en": "Corrected draft paper question",
        }
        data = {key: value for key, value in data.items() if value is not None}
        self.assertEqual(self.client.post(editor, data).status_code, 302)
        response = self.client.get(editor)
        self.assertEqual(self.client.post(editor, {
            "question_action": "select", "revision_snapshot": response.context["revision_snapshot"],
        }).status_code, 302)
        for action in ("review", "publish"):
            response = self.client.post(queue, {"selection_action": action}, follow=True)
            self.assertNotContains(response, "Select a reviewed, published revision")
        question.refresh_from_db()
        row.refresh_from_db()
        self.assertNotEqual(row.question_revision_id, original_id)
        self.assertEqual(row.question_revision_id, question.published_revision_id)
        self.assertTrue(publish_paper(batch.paper).is_published)

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
