from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse

from exams.models import Exam, ExamAuthority, ExamStage, Subject
from questions.models import Question, QuestionExam
from questions.services import create_question, create_revision, mark_reviewed, publish_question
from .models import PaperQuestion, PreviousYearPaper
from .services import publish_paper, published_papers, unpublish_paper


def content(**overrides):
    return dict(language="en", question_text="Which option is correct?", option_a="First", option_b="Second", option_c="Third", option_d="Fourth", correct_answer="B", explanation="Second is correct.") | overrides


class PaperFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.authority = ExamAuthority.objects.create(
            name="Commission", code="PC", slug="commission")
        cls.exam = Exam.objects.create(
            authority=cls.authority, name="Clerk", code="CLERK", slug="clerk")
        cls.other_exam = Exam.objects.create(
            authority=cls.authority, name="Other", code="OTHER", slug="other")
        cls.stage = ExamStage.objects.create(
            exam=cls.exam, name="Preliminary", code="PRE")
        cls.subject = Subject.objects.create(
            name="English", code="EN", slug="english")

    def setUp(self):
        self.paper = PreviousYearPaper.objects.create(
            exam=self.exam, year=2023, paper_name="Preliminary Paper")

    def question(self, *, published=True, associate=True, **overrides):
        question = create_question(
            subject=self.subject, revision=content(**overrides))
        if associate:
            QuestionExam.objects.create(question=question, exam=self.exam)
        if published:
            question = publish_question(mark_reviewed(question))
        return question

    def row(self, *, question=None, paper=None, **overrides):
        question = question or self.question()
        return PaperQuestion.objects.create(paper=paper or self.paper, question_revision=question.published_revision, question_number="1(a)", display_order=1, **overrides)

    def detail_url(self, paper=None, **overrides):
        paper = paper or self.paper
        return reverse("previous_year:paper_detail", kwargs={"authority_slug": self.authority.slug, "exam_slug": self.exam.slug, "year": paper.year, "paper_id": paper.pk, **overrides})


class PaperModelTests(PaperFixture):
    def test_defaults_relationships_and_unicode(self):
        row = self.row()
        self.assertEqual(connection.vendor, "postgresql")
        self.assertFalse(self.paper.is_published)
        self.assertIsNone(self.paper.stage_id)
        self.assertEqual(row.question_id, row.question_revision.question_id)
        self.assertEqual(self.paper.paper_questions.get(), row)
        self.paper.paper_name = "বাংলা প্রশ্নপত্র"
        self.paper.save()
        self.paper.refresh_from_db()
        self.assertIn("বাংলা", str(self.paper))

    def test_normalized_identity_and_database_uniqueness(self):
        for part, session in ((None, None), ("", ""), ("  ", "  ")):
            with self.subTest(part=part), self.assertRaises(ValidationError):
                PreviousYearPaper.objects.create(
                    exam=self.exam, year=2023, paper_name=" preliminary PAPER ", part=part, session=session)
        with patch.object(PreviousYearPaper, "full_clean"), self.assertRaises(IntegrityError), transaction.atomic():
            PreviousYearPaper.objects.create(
                exam=self.exam, year=2023, paper_name=" Preliminary PAPER ", part=" ", session="")

    def test_nonnull_stage_identity_and_distinct_parts(self):
        self.paper.stage = self.stage
        self.paper.part = " Part I "
        self.paper.session = " Session I "
        self.paper.save()
        self.assertEqual(self.paper.part, "Part I")
        with self.assertRaises(ValidationError):
            PreviousYearPaper.objects.create(
                exam=self.exam, stage=self.stage, year=2023, paper_name="preliminary paper", part="part i", session="session i")
        PreviousYearPaper.objects.create(exam=self.exam, stage=self.stage, year=2023,
                                         paper_name="Preliminary Paper", part="Part II", session="Session I")
        PreviousYearPaper.objects.create(
            exam=self.other_exam, year=2023, paper_name="Preliminary Paper")

    def test_stage_must_belong_to_exam(self):
        self.paper.exam = self.other_exam
        self.paper.stage = self.stage
        with self.assertRaises(ValidationError):
            self.paper.save()

    def test_required_fields_and_positive_numbers(self):
        for year, name in ((0, "Bad"), (-1, "Bad"), (2024, "  ")):
            with self.subTest(year=year), self.assertRaises(ValidationError):
                PreviousYearPaper.objects.create(
                    exam=self.exam, year=year, paper_name=name)
        revision = self.question().published_revision
        for number, order in (("", 1), (" ", 1), ("1", 0), ("1", -1)):
            with self.subTest(number=number, order=order), self.assertRaises(ValidationError):
                PaperQuestion.objects.create(
                    paper=self.paper, question_revision=revision, question_number=number, display_order=order)

    def test_database_row_constraints(self):
        row = self.row()
        other = self.question()
        for revision, number, order in ((other.published_revision, "2", 1), (other.published_revision, "1(a)", 2), (row.question_revision, "2", 2), (other.published_revision, "2", 0)):
            with self.subTest(number=number, order=order), patch.object(PaperQuestion, "full_clean"), self.assertRaises(IntegrityError), transaction.atomic():
                PaperQuestion.objects.create(
                    paper=self.paper, question_revision=revision, question_number=number, display_order=order)

    def test_no_duplicate_identity_across_revisions(self):
        row = self.row()
        question = row.question
        create_revision(question, **content(question_text="New version"))
        question = publish_question(mark_reviewed(question))
        with self.assertRaises(ValidationError):
            PaperQuestion.objects.create(
                paper=self.paper, question_revision=question.published_revision, question_number="2", display_order=2)

    def test_revisions_taxonomy_and_papers_are_protected(self):
        row = self.row()
        for obj in (row.question_revision, row.question, self.paper, self.exam):
            with self.subTest(model=type(obj).__name__), self.assertRaises(ProtectedError):
                obj.delete()


class PaperWorkflowTests(PaperFixture):
    def test_reject_draft_unreviewed_and_wrong_exam_associations(self):
        for question in (self.question(published=False), self.question(associate=False)):
            revision = question.published_revision or question.current_revision
            with self.assertRaises(ValidationError):
                PaperQuestion.objects.create(
                    paper=self.paper, question_revision=revision, question_number="1", display_order=1)

    def test_new_association_requires_current_published_revision(self):
        question = self.question()
        old = question.published_revision
        create_revision(question, **content(question_text="New content"))
        publish_question(mark_reviewed(question))
        with self.assertRaises(ValidationError):
            PaperQuestion.objects.create(
                paper=self.paper, question_revision=old, question_number="1", display_order=1)

    def test_approved_live_revision_can_be_used_while_working_draft_pending(self):
        question = self.question()
        create_revision(
            question, **content(question_text="Unreviewed working draft"))
        row = self.row(question=question)
        publish_paper(self.paper)
        self.assertEqual(row.question_revision, question.published_revision)

    def test_publish_unpublish_and_reject_empty(self):
        with self.assertRaises(ValidationError):
            publish_paper(self.paper)
        self.row()
        paper = publish_paper(self.paper)
        self.assertTrue(paper.is_published)
        self.assertTrue(published_papers().filter(pk=paper.pk).exists())
        self.assertFalse(unpublish_paper(paper).is_published)
        self.assertFalse(published_papers().filter(pk=paper.pk).exists())

    def test_historical_reference_survives_new_publication_and_republication(self):
        row = self.row()
        publish_paper(self.paper)
        create_revision(
            row.question, **content(question_text="Replacement content"))
        publish_question(mark_reviewed(row.question))
        unpublish_paper(self.paper)
        publish_paper(self.paper)
        row.refresh_from_db()
        self.assertEqual(row.question_revision.question_text,
                         content()["question_text"])
        self.assertContains(self.client.get(
            self.detail_url()), content()["question_text"])
        self.assertNotContains(self.client.get(
            self.detail_url()), "Replacement content")

    def test_published_composition_is_frozen_until_unpublished(self):
        row = self.row()
        self.paper = publish_paper(self.paper)
        self.paper.paper_name = "Changed"
        with self.assertRaises(ValidationError):
            self.paper.save()
        row.question_number = "New number"
        for operation in (row.save, row.delete, lambda: PaperQuestion.objects.filter(pk=row.pk).delete(), self.paper.delete):
            with self.assertRaises(ValidationError):
                operation()
        unpublish_paper(self.paper)
        row.save()
        self.assertEqual(PaperQuestion.objects.get(
            pk=row.pk).question_number, "New number")

    def test_bulk_and_direct_publication_bypasses_rejected(self):
        self.paper.is_published = True
        with self.assertRaises(ValidationError):
            self.paper.save()
        with self.assertRaises(ValidationError):
            PreviousYearPaper.objects.filter(
                pk=self.paper.pk).update(is_published=True)
        with self.assertRaises(ValidationError):
            PaperQuestion.objects.bulk_create([])

    def test_invalidated_exam_association_blocks_publication_and_public_access(self):
        row = self.row()
        publish_paper(self.paper)
        QuestionExam.objects.filter(question=row.question).delete()
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)
        with self.assertRaises(ValidationError):
            publish_paper(self.paper)

    def test_changing_exam_cannot_invalidate_existing_rows(self):
        self.row()
        self.paper.exam = self.other_exam
        with self.assertRaises(ValidationError):
            self.paper.save()

    def test_publication_failure_rolls_back(self):
        self.row()
        with patch.object(PreviousYearPaper, "save", side_effect=ValidationError("failure")), self.assertRaises(ValidationError):
            publish_paper(self.paper)
        self.paper.refresh_from_db()
        self.assertFalse(self.paper.is_published)


class PaperPublicTests(PaperFixture):
    def test_guest_solutions_order_unicode_and_missing_explanation(self):
        first = self.row(question=self.question(
            language="bn", question_text="সঠিক উত্তর নির্বাচন করুন।", explanation=""))
        second = self.question(
            question_text="Later question", explanation="Because it is correct.")
        PaperQuestion.objects.create(
            paper=self.paper, question_revision=second.published_revision, question_number="2(b)", display_order=2)
        publish_paper(self.paper)
        response = self.client.get(self.detail_url())
        self.assertEqual(response.status_code, 200)
        for text in ("সঠিক উত্তর নির্বাচন করুন।", "Correct answer: B", "Explanation unavailable.", "Because it is correct.", "First", "Second", "Third", "Fourth", 'lang="bn"'):
            self.assertContains(response, text)
        self.assertLess(response.content.index(
            "সঠিক উত্তর".encode()), response.content.index(b"Later question"))
        self.assertContains(response, reverse("previous_year:paper_list", args=[
                            self.authority.slug, self.exam.slug]))

    def test_drafts_are_hidden_and_empty_states_are_public(self):
        self.row()
        for route, args in (("previous_year:index", []), ("previous_year:paper_list", [self.authority.slug, self.exam.slug])):
            response = self.client.get(reverse(route, args=args))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "No published papers")
            self.assertNotContains(response, self.paper.paper_name)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)

    def test_papers_newest_first_and_metadata_displayed(self):
        self.paper.part = "Part I"
        self.paper.session = "Morning"
        self.paper.save()
        self.row()
        publish_paper(self.paper)
        newer = PreviousYearPaper.objects.create(
            exam=self.exam, year=2024, paper_name="Newer Paper")
        self.row(paper=newer)
        publish_paper(newer)
        response = self.client.get(reverse("previous_year:paper_list", args=[
                                   self.authority.slug, self.exam.slug]))
        self.assertContains(response, "Part I")
        self.assertContains(response, "Morning")
        self.assertLess(response.content.index(b"2024"),
                        response.content.index(b"2023"))

    def test_scoping_invalid_urls_and_inactive_navigation(self):
        self.row()
        publish_paper(self.paper)
        for overrides in ({"exam_slug": self.other_exam.slug}, {"authority_slug": "missing"}, {"year": 2000}, {"paper_id": 999999}):
            self.assertEqual(self.client.get(
                self.detail_url(**overrides)).status_code, 404)
        for obj in (self.exam, self.authority):
            obj.is_active = False
            obj.save()
            self.assertEqual(self.client.get(
                self.detail_url()).status_code, 404)
            obj.is_active = True
            obj.save()

    def test_html_is_escaped_and_line_breaks_preserved(self):
        self.row(question=self.question(
            question_text="<script>alert(1)</script>\nNext line"))
        publish_paper(self.paper)
        response = self.client.get(self.detail_url())
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(response, "<br>")
        self.assertNotContains(response, "<script>alert(1)</script>")


class PaperAdminTests(PaperFixture):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.test")
        self.url = reverse("admin:previous_year_previousyearpaper_changelist")

    def test_registration_and_guest_student_staff_permissions(self):
        self.assertTrue(admin.site.is_registered(PreviousYearPaper))
        self.assertEqual(self.client.get(self.url).status_code, 302)
        user = get_user_model().objects.create_user(username="student")
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        user.is_staff = True
        user.save()
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_admin_preview_publication_and_unpublication(self):
        self.row()
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("admin:previous_year_previousyearpaper_preview", args=[self.paper.pk]))
        self.assertContains(response, "Admin preview")
        self.assertContains(response, content()["question_text"])
        for action, expected in (("publish_selected", True), ("unpublish_selected", False)):
            response = self.client.post(
                self.url, {"action": action, "_selected_action": [self.paper.pk]}, follow=True)
            self.assertEqual(response.status_code, 200)
            self.paper.refresh_from_db()
            self.assertEqual(self.paper.is_published, expected)

    def test_empty_publish_errors_and_invalid_inline_errors_displayed(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {
                                    "action": "publish_selected", "_selected_action": [self.paper.pk]}, follow=True)
        self.assertContains(response, "An empty paper cannot be published")
        question = self.question(associate=False)
        response = self.client.post(reverse("admin:previous_year_previousyearpaper_add"), {
            "exam": self.exam.pk, "year": 2025, "paper_name": "Invalid associations",
            "paper_questions-TOTAL_FORMS": "1", "paper_questions-INITIAL_FORMS": "0",
            "paper_questions-0-question_revision": question.published_revision_id,
            "paper_questions-0-question_number": "1", "paper_questions-0-display_order": "1",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Question must be associated")
        self.assertFalse(PreviousYearPaper.objects.filter(
            paper_name="Invalid associations").exists())

    def test_admin_create_paper_and_association(self):
        self.client.force_login(self.user)
        question = self.question()
        response = self.client.post(reverse("admin:previous_year_previousyearpaper_add"), {
            "exam": self.exam.pk, "stage": self.stage.pk, "year": 2025, "paper_name": "New Paper",
            "paper_questions-TOTAL_FORMS": "1", "paper_questions-INITIAL_FORMS": "0",
            "paper_questions-0-question_revision": question.published_revision_id,
            "paper_questions-0-question_number": "12(a)", "paper_questions-0-display_order": "1",
        })
        self.assertEqual(response.status_code, 302)
        paper = PreviousYearPaper.objects.get(paper_name="New Paper")
        self.assertFalse(paper.is_published)
        self.assertEqual(paper.paper_questions.get().question_id, question.pk)

    def test_view_only_staff_cannot_publish_and_preview_is_private(self):
        preview = reverse(
            "admin:previous_year_previousyearpaper_preview", args=[self.paper.pk])
        self.assertEqual(self.client.get(preview).status_code, 302)
        user = get_user_model().objects.create_user(username="viewer", is_staff=True)
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label="previous_year", codename="view_previousyearpaper"))
        self.client.force_login(user)
        self.assertEqual(self.client.get(preview).status_code, 200)
        self.client.post(
            self.url, {"action": "publish_selected", "_selected_action": [self.paper.pk]})
        self.paper.refresh_from_db()
        self.assertFalse(self.paper.is_published)

    def test_admin_csrf_and_published_readonly_form(self):
        self.row()
        publish_paper(self.paper)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("admin:previous_year_previousyearpaper_change", args=[self.paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="paper_name"')
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, {
                         "action": "unpublish_selected", "_selected_action": [self.paper.pk]}).status_code, 403)
