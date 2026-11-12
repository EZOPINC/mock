from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.urls import reverse

from exams.models import Exam, ExamAuthority, ExamStage, Subject, Topic
from questions.models import QuestionExam
from questions.services import add_translation, create_question, create_revision, mark_reviewed, publish_question
from .models import ExamPattern, ExamPatternSection
from .services import activate_pattern, deactivate_pattern, eligible_question_ids, validate_configuration


class PatternTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        authority = ExamAuthority.objects.create(name="Authority", code="A", slug="authority")
        cls.exam = Exam.objects.create(authority=authority, name="Exam", code="E", slug="exam")
        cls.other_exam = Exam.objects.create(authority=authority, name="Other", code="O", slug="other")
        cls.subject = Subject.objects.create(name="Subject", code="S", slug="subject")
        cls.other_subject = Subject.objects.create(name="Other", code="O", slug="other")
        cls.topic = Topic.objects.create(subject=cls.subject, name="Topic", slug="topic")

    def setUp(self):
        self.pattern = ExamPattern.objects.create(exam=self.exam, name="Pattern", duration_minutes=60, total_questions=1, total_marks=1)
        self.section = ExamPatternSection.objects.create(language_mode="en", pattern=self.pattern, name="Section", question_count=1, display_order=1)

    def question(self, *, published=True, exam=None):
        question = create_question(subject=self.subject, topic=self.topic, revision=dict(language="en", question_text="Question?", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="A", explanation=""))
        QuestionExam.objects.create(question=question, exam=exam or self.exam)
        return publish_question(mark_reviewed(question)) if published else question

    def test_configuration_and_activation_deactivation(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.question()
        validate_configuration(self.pattern)
        active = activate_pattern(self.pattern)
        self.assertTrue(active.is_active)
        self.assertEqual(deactivate_pattern(active).status, "inactive")

    def test_drafts_and_other_exams_are_not_eligible(self):
        self.question(published=False)
        self.question(exam=self.other_exam)
        self.assertEqual(eligible_question_ids(self.section), set())
        with self.assertRaises(ValidationError):
            activate_pattern(self.pattern)

    def test_missing_sections_counts_and_marks_block_activation(self):
        self.question()
        for field, value in (("total_questions", 2), ("total_marks", Decimal("2"))):
            pattern = ExamPattern.objects.get(pk=self.pattern.pk)
            setattr(pattern, field, value)
            pattern.save()
            with self.assertRaises(ValidationError):
                activate_pattern(pattern)
        self.section.delete()
        with self.assertRaises(ValidationError):
            activate_pattern(self.pattern)

    def test_invalid_stage_topic_and_marking(self):
        stage = ExamStage.objects.create(exam=self.other_exam, name="Stage", code="S")
        self.pattern.stage = stage
        with self.assertRaises(ValidationError):
            self.pattern.save()
        self.section.subject = self.other_subject
        self.section.topic = self.topic
        with self.assertRaises(ValidationError):
            self.section.save()
        self.section.subject = self.subject
        for field, value in (("positive_marks", 0), ("negative_marks", -1), ("question_count", 0), ("display_order", 0), ("language_mode", "xx")):
            section = ExamPatternSection.objects.get(pk=self.section.pk)
            setattr(section, field, value)
            with self.assertRaises(ValidationError):
                section.save()

    def test_defaults_and_section_overrides(self):
        self.question()
        self.pattern.total_marks = Decimal("2.50")
        self.pattern.default_negative_marks = Decimal("0.25")
        self.pattern.save()
        self.section.positive_marks = Decimal("2.50")
        self.section.negative_marks = Decimal("0.50")
        self.section.save()
        self.assertTrue(activate_pattern(self.pattern).is_active)

    def test_bilingual_counts_as_one_and_language_filters(self):
        self.section.language_mode = "mixed"
        self.section.save()
        question = self.question()
        self.assertEqual(eligible_question_ids(self.section), set())
        with self.assertRaises(ValidationError):
            activate_pattern(self.pattern)
        add_translation(question, language="bn", question_text="Translation", option_a="A", option_b="B", option_c="C", option_d="D")
        question = publish_question(mark_reviewed(question))
        for language in ("en", "bn", "mixed"):
            self.section.language_mode = language
            self.assertEqual(eligible_question_ids(self.section), {question.pk})
        self.section.question_count = 2
        self.section.save()
        self.pattern.total_questions = 2
        self.pattern.total_marks = 2
        self.pattern.save()
        with self.assertRaises(ValidationError):
            activate_pattern(self.pattern)

    def test_working_draft_does_not_replace_approved_revision(self):
        question = self.question()
        published_id = question.published_revision_id
        create_revision(question, language="en", question_text="New draft", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="B", explanation="")
        self.assertEqual(eligible_question_ids(self.section), {question.pk})
        question.refresh_from_db()
        self.assertEqual(question.published_revision_id, published_id)

    def test_topic_and_subject_filters(self):
        question = self.question()
        self.section.subject = self.other_subject
        self.assertEqual(eligible_question_ids(self.section), set())
        self.section.subject = self.subject
        self.section.topic = self.topic
        self.assertEqual(eligible_question_ids(self.section), {question.pk})
        self.section.language_mode = "bn"
        self.assertEqual(eligible_question_ids(self.section), set())

    def test_active_configuration_is_frozen(self):
        self.question()
        active = activate_pattern(self.pattern)
        active.duration_minutes = 30
        with self.assertRaises(ValidationError):
            active.save()
        with self.assertRaises(ValidationError):
            self.section.save()
        with self.assertRaises(ValidationError):
            self.section.delete()
        with self.assertRaises(ValidationError):
            active.delete()
        with self.assertRaises(ValidationError):
            ExamPattern.objects.filter(pk=active.pk).update(total_questions=2)
        deactivate_pattern(active)
        self.section.name = "Editable again"
        self.section.save()

    def test_explicit_activation_and_unique_scope(self):
        self.question()
        self.pattern.status = "active"
        with self.assertRaises(ValidationError):
            self.pattern.save()
        active = activate_pattern(self.pattern)
        second = ExamPattern.objects.create(exam=self.exam, name="Second", duration_minutes=30, total_questions=1, total_marks=1)
        ExamPatternSection.objects.create(language_mode="en", pattern=second, name="Section", question_count=1, display_order=1)
        with self.assertRaises(ValidationError):
            activate_pattern(second)
        stage = ExamStage.objects.create(exam=self.exam, name="Stage", code="S")
        second.stage = stage
        second.save()
        self.assertTrue(activate_pattern(second).is_active)
        self.assertTrue(active.is_active)

    def test_overlapping_pools_need_distinct_questions(self):
        self.question()
        self.pattern.total_questions = 2
        self.pattern.total_marks = 2
        self.pattern.save()
        ExamPatternSection.objects.create(language_mode="en", pattern=self.pattern, name="Other", question_count=1, display_order=2)
        with self.assertRaisesMessage(ValidationError, "Overlapping"):
            activate_pattern(self.pattern)
        self.question()
        self.assertTrue(activate_pattern(self.pattern).is_active)

    def test_inactive_exam_rejected(self):
        self.question()
        self.exam.is_active = False
        self.exam.save()
        with self.assertRaises(ValidationError):
            activate_pattern(self.pattern)

    def test_incomplete_options_and_unpublished_revisions_are_ineligible(self):
        question = self.question()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE questions_questiontranslation SET option_a = '   ' WHERE revision_id = %s", [question.published_revision_id])
        self.assertEqual(eligible_question_ids(self.section), set())
        with self.assertRaises(ValidationError):
            activate_pattern(self.pattern)

    def test_database_prevents_two_active_patterns_without_stage(self):
        self.question()
        activate_pattern(self.pattern)
        second = ExamPattern.objects.create(exam=self.exam, name="Second", duration_minutes=60, total_questions=1, total_marks=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE mock_tests_exampattern SET status = 'active' WHERE id = %s", [second.pk])

    def test_admin_active_paper_is_read_only_and_actions_remain_available(self):
        self.question()
        active = activate_pattern(self.pattern)
        user = get_user_model().objects.create_superuser(username="admin", password="test-password")
        self.client.force_login(user)
        url = reverse("admin:mock_tests_exampattern_change", args=[active.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {"name": "Changed"}).status_code, 403)
        response = self.client.post(reverse("admin:mock_tests_exampattern_changelist"), {"action": "deactivate_selected", "_selected_action": [active.pk]})
        self.assertEqual(response.status_code, 302)
        active.refresh_from_db()
        self.assertEqual(active.status, "inactive")

    def test_database_constraints_and_protection(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE mock_tests_exampattern SET duration_minutes = 0 WHERE id = %s", [self.pattern.pk])
        with self.assertRaises(ValidationError):
            ExamPatternSection.objects.create(language_mode="en", pattern=self.pattern, name="Duplicate", display_order=1, question_count=1)
        from django.db.models.deletion import ProtectedError
        with self.assertRaises(ProtectedError):
            self.exam.delete()

    def test_admin_registration_permissions_and_inline(self):
        self.assertIn(ExamPattern, admin.site._registry)
        self.assertIn(ExamPatternSection, admin.site._registry)
        url = reverse("admin:mock_tests_exampattern_change", args=[self.pattern.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        user = get_user_model().objects.create_user(username="staff", is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(url).status_code, 403)
        user.is_superuser = True
        user.save()
        response = self.client.get(url)
        self.assertContains(response, "sections-TOTAL_FORMS")
        self.assertContains(response, "Eligible questions")
