from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.urls import reverse

from exams.models import Subject
from questions.models import Question
from questions.services import add_translation, mark_reviewed, publish_question
from .models import PaperQuestion, PreviousYearPaper
from .services import publish_paper, unpublish_paper
from .tests import PaperFixture


class PaperAdministrationTests(PaperFixture):
    def test_optional_metadata_round_trip_and_old_defaults(self):
        self.assertIsNone(self.paper.duration_minutes)
        self.assertIsNone(self.paper.total_marks)
        self.assertIsNone(self.paper.subject_id)
        self.assertIsNone(self.paper.expected_question_count)
        self.assertEqual(self.paper.instructions, "")
        self.paper.duration_minutes = 90
        self.paper.total_marks = Decimal("100.50")
        self.paper.instructions = "Answer all questions.\nসব প্রশ্নের উত্তর দিন। ∑"
        self.paper.subject = self.subject
        self.paper.expected_question_count = 2
        self.paper.save()
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.duration_minutes, 90)
        self.assertEqual(self.paper.total_marks, Decimal("100.50"))
        self.assertIn("সব প্রশ্নের", self.paper.instructions)

    def test_metadata_positive_checks_in_validation_and_database(self):
        for fields in ({"duration_minutes": 0}, {"duration_minutes": -1}, {"total_marks": Decimal("-0.01")}, {"expected_question_count": 0}):
            with self.subTest(fields=fields):
                paper = PreviousYearPaper(exam=self.exam, year=2024, paper_name="Invalid", **fields)
                with self.assertRaises(ValidationError):
                    paper.full_clean()
                with patch.object(PreviousYearPaper, "full_clean"), self.assertRaises(IntegrityError), transaction.atomic():
                    paper.save()

    def test_subject_relationship_is_protected(self):
        subject = Subject.objects.create(name="Paper-only subject", code="PAPER", slug="paper-only")
        self.paper.subject = subject
        self.paper.save()
        with self.assertRaises(ProtectedError):
            subject.delete()

    def test_paper_subject_must_match_question_and_cannot_invalidate_existing_rows(self):
        row = self.row()
        other = Subject.objects.create(name="Other subject", code="OTHER", slug="other")
        self.paper.subject = other
        with self.assertRaises(ValidationError):
            self.paper.save()
        self.paper.subject = self.subject
        self.paper.save()
        other_paper = PreviousYearPaper.objects.create(exam=self.exam, year=2024, paper_name="Other subject paper", subject=other)
        with self.assertRaises(ValidationError):
            PaperQuestion.objects.create(paper=other_paper, question_revision=row.question_revision, question_number="1", display_order=1)

    def test_expected_count_allows_draft_progress_but_blocks_publication_mismatch(self):
        self.paper.expected_question_count = 2
        self.paper.save()
        self.row()
        with self.assertRaisesMessage(ValidationError, "Expected 2 questions; the paper has 1"):
            publish_paper(self.paper)
        second = self.question()
        PaperQuestion.objects.create(paper=self.paper, question_revision=second.published_revision, question_number="2", display_order=2)
        self.assertTrue(publish_paper(self.paper).is_published)

    def test_cannot_exceed_declared_count_or_lower_it_below_existing_rows(self):
        self.paper.expected_question_count = 1
        self.paper.save()
        self.row()
        second = self.question()
        with self.assertRaises(ValidationError):
            PaperQuestion.objects.create(paper=self.paper, question_revision=second.published_revision, question_number="2", display_order=2)
        self.assertEqual(self.paper.paper_questions.count(), 1)
        self.paper.expected_question_count = None
        self.paper.save()
        PaperQuestion.objects.create(paper=self.paper, question_revision=second.published_revision, question_number="2", display_order=2)
        self.paper.expected_question_count = 1
        with self.assertRaises(ValidationError):
            self.paper.save()

    def test_one_multilingual_master_can_belong_to_multiple_papers_without_copying(self):
        question = self.question()
        add_translation(question, language="bn", question_text="বাংলা প্রশ্ন", option_a="এক", option_b="দুই", option_c="তিন", option_d="চার")
        question = publish_question(mark_reviewed(question))
        self.paper.expected_question_count = 1
        self.paper.save()
        first = self.row(question=question)
        second_paper = PreviousYearPaper.objects.create(exam=self.exam, year=2024, paper_name="Another paper", expected_question_count=1)
        second = self.row(question=question, paper=second_paper)
        self.assertEqual(first.question_id, second.question_id)
        self.assertEqual(first.question_revision_id, second.question_revision_id)
        self.assertEqual(Question.objects.count(), 1)
        self.assertEqual(question.current_revision.translations.count(), 2)
        self.assertTrue(publish_paper(self.paper).is_published)
        self.assertTrue(publish_paper(second_paper).is_published)

    def test_published_metadata_requires_unpublication_before_editing(self):
        self.row()
        published = publish_paper(self.paper)
        for field, value in (("instructions", "Changed"), ("duration_minutes", 30), ("total_marks", Decimal("5")), ("subject_id", self.subject.pk), ("expected_question_count", 1)):
            paper = PreviousYearPaper.objects.get(pk=published.pk)
            setattr(paper, field, value)
            with self.subTest(field=field), self.assertRaises(ValidationError):
                paper.save()
        paper = unpublish_paper(published)
        paper.instructions = "Updated draft instructions"
        paper.save()

    def test_admin_can_save_metadata_with_inline_and_display_count_status(self):
        user = get_user_model().objects.create_superuser(username="admin", email="admin@example.test")
        self.client.force_login(user)
        question = self.question()
        response = self.client.post(reverse("admin:previous_year_previousyearpaper_add"), {
            "exam": self.exam.pk, "stage": self.stage.pk, "year": 2025, "paper_name": "Configured paper",
            "duration_minutes": 60, "total_marks": "50.00", "instructions": "Read carefully.",
            "subject": self.subject.pk, "expected_question_count": 1,
            "paper_questions-TOTAL_FORMS": "1", "paper_questions-INITIAL_FORMS": "0",
            "paper_questions-0-question_revision": question.published_revision_id,
            "paper_questions-0-question_number": "12(a)", "paper_questions-0-display_order": 1,
        })
        self.assertEqual(response.status_code, 302)
        paper = PreviousYearPaper.objects.get(paper_name="Configured paper")
        response = self.client.get(reverse("admin:previous_year_previousyearpaper_change", args=[paper.pk]))
        self.assertContains(response, "1 / 1")
        self.assertEqual(paper.total_marks, Decimal("50.00"))

    def test_admin_inline_over_declared_count_is_clear_validation_error(self):
        user = get_user_model().objects.create_superuser(username="admin", email="admin@example.test")
        self.client.force_login(user)
        questions = [self.question(), self.question()]
        data = {"exam": self.exam.pk, "year": 2025, "paper_name": "Overfull", "expected_question_count": 1,
                "paper_questions-TOTAL_FORMS": "2", "paper_questions-INITIAL_FORMS": "0"}
        for index, question in enumerate(questions):
            data.update({f"paper_questions-{index}-question_revision": question.published_revision_id,
                         f"paper_questions-{index}-question_number": str(index + 1), f"paper_questions-{index}-display_order": index + 1})
        response = self.client.post(reverse("admin:previous_year_previousyearpaper_add"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "the inline contains 2")
        self.assertFalse(PreviousYearPaper.objects.filter(paper_name="Overfull").exists())
