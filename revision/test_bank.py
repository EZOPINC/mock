from datetime import timedelta
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from exams.models import Part, Module, Chapter, Topic
from mock_tests.test_execution import ExecutionFixture
from practice.tests import PracticeFixture
from questions.models import QuestionExam
from questions.services import add_translation, create_revision, mark_reviewed, publish_question
from questions.tagging import set_question_topics
from .models import SavedQuestion
from .selectors import visible_questions


class RevisionBankTests(PracticeFixture):
    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("revision:dashboard")

    def save_question(self, **kwargs):
        return SavedQuestion.objects.create(user=self.user, question=self.question(**kwargs))

    def detail_url(self, saved):
        return reverse("revision:detail", args=[saved.pk])

    def update(self, saved, action, **kwargs):
        return self.client.post(reverse("revision:manage", args=[saved.pk]), {"action": action, **kwargs})

    def set_difficulty(self, question, difficulty):
        create_revision(question, language="en", question_text="Published " + difficulty, option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="A", difficulty_level=difficulty)
        return publish_question(mark_reviewed(question))

    def test_default_fields_preserve_bookmark_and_empty_state(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Your Revision Bank is empty")
        saved = self.save_question()
        self.assertEqual(saved.personal_note, "")
        self.assertIsNone(saved.reviewed_at)
        self.assertEqual(saved.review_count, 0)
        self.assertFalse(saved.is_mastered)
        response = self.client.get(self.url)
        self.assertEqual(response.context["counts"], {"total": 1, "reviewed": 0, "mastered": 0})
        self.assertContains(response, saved.question.published_revision.question_text)
        self.assertContains(response, "My Revision Bank")

    def test_ownership_authentication_methods_and_csrf(self):
        saved = self.save_question()
        urls = [self.url, self.detail_url(saved), reverse("revision:remove", args=[saved.pk])]
        self.client.logout()
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(self.detail_url(saved)).status_code, 404)
        self.assertEqual(self.update(saved, "mastered").status_code, 404)
        self.assertEqual(self.client.post(reverse("revision:remove", args=[saved.pk]), {"confirm": "yes"}).status_code, 404)
        self.assertEqual(self.client.get(self.url).context["counts"]["total"], 0)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("revision:manage", args=[saved.pk])).status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(reverse("revision:manage", args=[saved.pk]), {"action": "mastered"}).status_code, 403)
        self.assertEqual(strict.post(reverse("revision:remove", args=[saved.pk]), {"confirm": "yes"}).status_code, 403)
        strict.get(self.detail_url(saved))
        self.assertEqual(strict.post(reverse("revision:manage", args=[saved.pk]), {"action": "mastered"}, HTTP_X_CSRFTOKEN=strict.cookies["csrftoken"].value).status_code, 302)

    def test_notes_mastery_explicit_review_and_deletion(self):
        saved = self.save_question()
        self.client.get(self.detail_url(saved))
        saved.refresh_from_db()
        self.assertEqual(saved.review_count, 0)
        note = '<script>alert("private")</script>'
        self.assertEqual(self.update(saved, "note", personal_note=note, user_id=self.other_user.pk).status_code, 302)
        self.assertContains(self.client.get(self.detail_url(saved)), "&lt;script&gt;")
        self.assertNotContains(self.client.get(self.detail_url(saved)), note)
        self.assertEqual(self.update(saved, "note", personal_note="x" * 10001).status_code, 400)
        saved.refresh_from_db()
        self.assertEqual(saved.personal_note, note)
        self.update(saved, "reviewed")
        self.update(saved, "reviewed")
        self.update(saved, "mastered")
        saved.refresh_from_db()
        self.assertEqual(saved.review_count, 2)
        self.assertIsNotNone(saved.reviewed_at)
        self.assertTrue(saved.is_mastered)
        self.assertEqual(self.client.get(self.url).context["counts"], {"total": 1, "reviewed": 1, "mastered": 1})
        self.update(saved, "needs_revision")
        self.update(saved, "note", personal_note="")
        saved.refresh_from_db()
        self.assertFalse(saved.is_mastered)
        self.assertEqual(saved.personal_note, "")
        self.assertEqual(self.update(saved, "invalid").status_code, 400)

    def test_removal_confirmation_and_r1_compatibility(self):
        saved = self.save_question()
        url = reverse("revision:remove", args=[saved.pk])
        self.assertContains(self.client.get(url), "Remove this bookmark?")
        self.assertTrue(SavedQuestion.objects.filter(pk=saved.pk).exists())
        self.assertEqual(self.client.post(url, {}).status_code, 400)
        self.update(saved, "note", personal_note="Keep on repeated save")
        self.update(saved, "mastered")
        self.client.post(reverse("revision:save", args=[saved.question_id]), HTTP_ACCEPT="application/json")
        saved.refresh_from_db()
        self.assertEqual(saved.personal_note, "Keep on repeated save")
        self.assertTrue(saved.is_mastered)
        self.assertRedirects(self.client.post(url, {"confirm": "yes"}), self.url)
        self.assertFalse(SavedQuestion.objects.exists())
        self.assertEqual(self.client.post(reverse("revision:unsave", args=[saved.question_id]), HTTP_ACCEPT="application/json").status_code, 200)

    def test_all_hierarchy_filters_include_secondary_tags_without_duplicates(self):
        part = Part.objects.create(subject=self.subject, name="Part", slug="part")
        module = Module.objects.create(part=part, name="Module", slug="module")
        chapter = Chapter.objects.create(module=module, name="Chapter", slug="chapter")
        secondary = Topic.objects.create(subject=self.subject, chapter=chapter, name="Secondary", slug="secondary")
        another = Topic.objects.create(subject=self.subject, module=module, name="Another", slug="another")
        saved = self.save_question()
        set_question_topics(saved.question, [self.topic.pk, secondary.pk, another.pk], primary_topic_id=self.topic.pk)
        QuestionExam.objects.create(question=saved.question, exam=self.other_exam)
        unrelated = self.save_question()
        for kind, node in (("exam", self.other_exam), ("part", part), ("module", module), ("chapter", chapter), ("topic", secondary)):
            response = self.client.get(self.url, {kind: node.pk})
            self.assertEqual([item.pk for item in response.context["page"]], [saved.pk], kind)
        response = self.client.get(self.url, {"subject": self.subject.pk})
        self.assertEqual(response.context["page"].paginator.count, 2)
        response = self.client.get(self.url, {"exam": self.exam.pk, "module": module.pk, "chapter": chapter.pk})
        self.assertEqual(response.context["page"].paginator.count, 1)
        self.assertContains(self.client.get(self.detail_url(saved)), "Explore Topic")
        self.assertContains(self.client.get(self.detail_url(saved)), reverse("revision:explore", args=["topic", secondary.pk]) + f"?from_question={saved.question_id}")
        invalid = self.client.get(self.url, {"module": "999999"})
        self.assertEqual(invalid.context["page"].paginator.count, 0)
        self.assertTrue(invalid.context["form"].errors)

    def test_sorting_counts_and_mastery_filter(self):
        easy, hard, medium = [self.save_question() for _ in range(3)]
        for saved, value in ((easy, "Easy"), (hard, "Hard"), (medium, "Medium")):
            self.set_difficulty(saved.question, value)
        SavedQuestion.objects.filter(pk=easy.pk).update(saved_at=timezone.now() - timedelta(days=2))
        self.update(hard, "mastered")
        self.update(medium, "reviewed")
        for sort, expected in (("difficulty_asc", [easy.pk, medium.pk, hard.pk]), ("difficulty_desc", [hard.pk, medium.pk, easy.pk]), ("saved_oldest", [easy.pk, hard.pk, medium.pk]), ("saved_newest", [medium.pk, hard.pk, easy.pk])):
            response = self.client.get(self.url, {"sort": sort})
            self.assertEqual([item.pk for item in response.context["page"]], expected)
        response = self.client.get(self.url, {"mastery": "mastered"})
        self.assertEqual([item.pk for item in response.context["page"]], [hard.pk])
        self.assertEqual(response.context["counts"], {"total": 3, "reviewed": 1, "mastered": 1})
        self.assertEqual(self.client.get(self.url, {"mastery": "needs_revision"}).context["page"].paginator.count, 2)

    def test_pagination_preserves_filters_and_has_no_duplicates(self):
        for _ in range(21):
            self.save_question()
        response = self.client.get(self.url, {"mastery": "needs_revision", "sort": "saved_oldest"})
        self.assertEqual(len(response.context["page"]), 20)
        self.assertContains(response, "mastery=needs_revision&amp;sort=saved_oldest&amp;page=2")
        last = self.client.get(self.url, {"mastery": "needs_revision", "sort": "saved_oldest", "page": 2})
        self.assertEqual(len(last.context["page"]), 1)
        self.assertNotIn(last.context["page"][0].pk, [item.pk for item in response.context["page"]])

    def test_bilingual_published_revision_only_and_no_get_review(self):
        saved = self.save_question()
        add_translation(saved.question, language="bn", question_text="\u09ac\u09be\u0982\u09b2\u09be", option_a="A", option_b="B", option_c="C", option_d="D", explanation="Bengali explanation")
        publish_question(mark_reviewed(saved.question))
        create_revision(saved.question, language="en", question_text="SECRET DRAFT", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="D")
        for url in (self.url, self.detail_url(saved)):
            response = self.client.get(url)
            self.assertContains(response, "\u09ac\u09be\u0982\u09b2\u09be")
            self.assertNotContains(response, "SECRET DRAFT")
        self.assertContains(self.client.get(self.detail_url(saved)), "Bengali explanation")
        saved.refresh_from_db()
        self.assertEqual(saved.review_count, 0)

    def test_unpublished_inactive_and_invalid_language_are_content_free(self):
        saved = self.save_question()
        for assignment in ("publication_status = 'draft', published_revision_id = NULL",):
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE questions_question SET {assignment} WHERE id = %s", [saved.question_id])
        for url in (self.url, self.detail_url(saved)):
            response = self.client.get(url)
            self.assertContains(response, "Question currently unavailable")
            self.assertNotContains(response, saved.question.published_revision.question_text)
            self.assertNotContains(response, "VERIFIED SOLUTION")
            self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(self.update(saved, "reviewed").status_code, 404)
        self.assertEqual(self.update(saved, "note", personal_note="Retained note").status_code, 302)
        unsupported = self.save_question()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE questions_questiontranslation SET language='xx' WHERE revision_id=%s", [unsupported.question.published_revision_id])
        self.assertFalse(visible_questions(self.user).filter(pk=unsupported.question_id).exists())
        inactive = self.save_question()
        self.exam.is_active = False
        self.exam.save()
        self.assertNotContains(self.client.get(self.detail_url(inactive)), "VERIFIED SOLUTION")

    def test_sql_visibility_matches_existing_language_eligibility(self):
        good = self.save_question()
        incomplete = self.save_question()
        unsupported = self.save_question()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE questions_questiontranslation SET option_b='   ' WHERE revision_id=%s", [incomplete.question.published_revision_id])
            cursor.execute("UPDATE questions_questiontranslation SET language='xx' WHERE revision_id=%s", [unsupported.question.published_revision_id])
        from questions.eligibility import eligible_question_ids
        expected = eligible_question_ids(self.exam.pk, subject_id=self.subject.pk)
        self.assertEqual(expected, {good.question_id})
        self.assertEqual(set(visible_questions(self.user).values_list("pk", flat=True)), expected)

    def test_query_count_is_bounded_when_page_grows(self):
        self.save_question()
        with CaptureQueriesContext(connection) as first:
            self.client.get(self.url)
        for _ in range(4):
            self.save_question()
        with CaptureQueriesContext(connection) as expanded:
            self.client.get(self.url)
        self.assertEqual(len(first), len(expanded))
        self.assertLess(len(expanded), 30)


class OpenMockBankTests(ExecutionFixture):
    def test_bank_cannot_reveal_open_mock_question_and_does_not_mutate_attempt(self):
        attempt = self.ready_attempt()
        row = attempt.questions.get()
        saved = SavedQuestion.objects.create(user=self.user, question=row.question)
        self.client.force_login(self.user)
        before = type(attempt).objects.filter(pk=attempt.pk).values().get()
        for url in (reverse("revision:dashboard"), reverse("revision:detail", args=[saved.pk])):
            response = self.client.get(url)
            self.assertContains(response, "Question currently unavailable")
            self.assertNotContains(response, row.question_revision.question_text)
            self.assertNotContains(response, "Correct answer:")
        self.assertEqual(before, type(attempt).objects.filter(pk=attempt.pk).values().get())
        from mock_tests.execution import submit_attempt
        submit_attempt(self.user, attempt.pk, expected_version=attempt.save_version)
        self.assertContains(self.client.get(reverse("revision:detail", args=[saved.pk])), row.question_revision.question_text)


from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class BookmarkMigrationTests(TransactionTestCase):
    def test_r1_bookmark_survives_r2_with_defaults_and_unique_constraint(self):
        executor = MigrationExecutor(connection)
        old = [("revision", "0001_initial")]
        latest = [("revision", "0002_savedquestion_is_mastered_and_more")]
        executor.migrate(old)
        try:
            apps = executor.loader.project_state(old).apps
            from django.conf import settings
            app, model = settings.AUTH_USER_MODEL.split(".")
            user = apps.get_model(app, model).objects.create(username="migration-user", password="!")
            subject = apps.get_model("exams", "Subject").objects.create(name="Migration subject", slug="migration", code="MIG")
            question = apps.get_model("questions", "Question").objects.create(subject_id=subject.pk)
            saved = apps.get_model("revision", "SavedQuestion").objects.create(user_id=user.pk, question_id=question.pk)
            original_time = saved.saved_at
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            restored = SavedQuestion.objects.get(pk=saved.pk)
            self.assertEqual(restored.saved_at, original_time)
            self.assertEqual(restored.personal_note, "")
            self.assertIsNone(restored.reviewed_at)
            self.assertEqual(restored.review_count, 0)
            self.assertFalse(restored.is_mastered)
            from django.db import IntegrityError, transaction
            with self.assertRaises(IntegrityError), transaction.atomic():
                SavedQuestion.objects.create(user_id=user.pk, question_id=question.pk)
        finally:
            restore = MigrationExecutor(connection)
            restore.migrate(restore.loader.graph.leaf_nodes())
