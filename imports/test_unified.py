from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection
from django.urls import reverse

from exams.models import Exam, ExamAuthority, Subject, Topic
from previous_year.models import PaperQuestion, PreviousYearPaper
from questions.models import Question, QuestionExam
from .context import context_hash
from .forms import UploadForm
from .models import ImportBatch
from .parsing import REQUIRED, parse_upload
from .services import confirm_import
from .tests import ImportFixture, csv_file, values, xlsx_file
from .validation import validate


class UnifiedImportTests(ImportFixture):
    def general(self, rows=None, **selection):
        data = self.data(rows)
        data["selection"] = {"import_type": "general", "exam_ids": [self.exam.pk], "exam_mapping": "selected", **selection}
        return data

    def test_only_six_headers_required_csv_and_xlsx_optional_values_blank(self):
        self.assertEqual(len(REQUIRED), 6)
        parsed = parse_upload(csv_file(headers=REQUIRED))
        self.assertEqual(parsed["rows"][0]["values"]["correct_answer"], "")
        data = self.general()
        data["rows"] = parsed["rows"]
        self.assertGreater(validate(data)["error_count"], 0)
        parsed_xlsx = parse_upload(xlsx_file([values(correct_answer="", subject="", language="")]))
        self.assertEqual(parsed_xlsx["rows"][0]["values"]["language"], "")

    def test_general_multiple_exams_no_paper_and_draft_defaults(self):
        other = Exam.objects.create(authority=self.authority, name="Other", code="OTHER", slug="other")
        data = self.general(exam_ids=[self.exam.pk, other.pk])
        existing_papers = PreviousYearPaper.objects.count()
        batch = confirm_import(data, self.user)
        question = batch.imported_questions.get().question
        self.assertIsNone(batch.paper_id)
        self.assertEqual(PreviousYearPaper.objects.count(), existing_papers)
        self.assertFalse(PaperQuestion.objects.exists())
        self.assertEqual(set(question.exams.values_list("pk", flat=True)), {self.exam.pk, other.pk})
        self.assertEqual(question.publication_status, "draft")
        self.assertEqual(question.review_status, "pending_review")
        data["token"] = "4a8e11c6-5318-46a7-86b6-1c53c7ae1111"
        data["selection"]["exam_ids"] = [other.pk, self.exam.pk]
        self.assertGreater(validate(data)["error_count"], 0)

    def test_general_transaction_rolls_back_all_rows(self):
        from questions.services import create_question
        data = self.general([values(), values(question_number="2")])
        calls = 0
        def fail_second(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValidationError("A late row failed.")
            return create_question(**kwargs)
        with patch("imports.services.create_question", side_effect=fail_second), self.assertRaises(ValidationError):
            confirm_import(data, self.user)
        self.assertEqual(Question.objects.count(), 0)
        self.assertEqual(QuestionExam.objects.count(), 0)
        self.assertEqual(ImportBatch.objects.count(), 0)
        self.assertFalse(PaperQuestion.objects.exists())

    def test_defaults_resolve_missing_fields_without_inventing_answer(self):
        data = self.general([values(subject="", topic="", language="", correct_answer="")], subject_id=self.subject.pk, topic_id=self.topic.pk, language="bn")
        result = validate(data)
        self.assertEqual(result["rows"][0]["subject"], self.subject)
        self.assertEqual(result["rows"][0]["topic"], self.topic)
        self.assertEqual(result["rows"][0]["revision"]["language"], "bn")
        self.assertGreater(result["error_count"], 0)
        with self.assertRaises(ValidationError):
            confirm_import(data, self.user)
        data["rows"][0]["values"]["correct_answer"] = "D"
        batch = confirm_import(data, self.user)
        self.assertEqual(batch.imported_questions.get().question.current_revision.correct_answer, "D")
        self.assertEqual(batch.imported_questions.get().source_metadata["resolved"]["language"], "bn")

    def test_language_inferred_and_blank_subject_reuses_existing_unidentified(self):
        Subject.objects.create(name="UnIdentified", code="UNIDENTIFIED", slug="unidentified")
        data = self.general([values(subject="", language="")])
        result = validate(data)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["rows"][0]["subject"].name, "UnIdentified")
        self.assertEqual(result["rows"][0]["revision"]["language"], "en")
        data["subject_map"] = {"": self.subject.pk}
        data["selection"]["language"] = "en"
        self.assertEqual(validate(data)["error_count"], 0)

    def test_rows_override_batch_taxonomy_and_language(self):
        other = Subject.objects.create(name="Bengali", code="BN", slug="bengali")
        data = self.general([values(subject="Bengali", language="bn")], subject_id=self.subject.pk, language="en")
        result = validate(data)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["rows"][0]["subject"], other)
        self.assertEqual(result["rows"][0]["revision"]["language"], "bn")
        data["selection"]["topic_id"] = self.topic.pk
        self.assertGreater(validate(data)["error_count"], 0)

    def test_row_exam_mapping_uses_existing_records_and_rejects_ambiguity(self):
        other_authority = ExamAuthority.objects.create(name="Other Authority", code="OA", slug="oa")
        other = Exam.objects.create(authority=other_authority, name="Clerkship", code="CLERK", slug="clerk")
        data = self.general([values(exam_categories="Clerkship")], exam_mapping="rows")
        self.assertGreater(validate(data)["error_count"], 0)
        data["rows"][0]["values"]["exam_categories"] = "Other Authority / Clerkship"
        batch = confirm_import(data, self.user)
        self.assertEqual(list(batch.imported_questions.get().question.exams.all()), [other])

    def test_unknown_categories_block_only_explicit_row_mapping(self):
        data = self.general([values(exam_categories="Unknown exam")])
        self.assertEqual(validate(data)["error_count"], 0)
        data["selection"]["exam_mapping"] = "rows"
        self.assertGreater(validate(data)["error_count"], 0)
        data["rows"][0]["values"]["exam_categories"] = ""
        self.assertEqual(validate(data)["rows"][0]["exams"], [self.exam])

    def test_previous_year_default_name_and_automatic_reuse(self):
        data = self.data(new_paper=True)
        data["selection"]["import_type"] = "previous_year"
        data["selection"]["paper"]["paper_name"] = ""
        batch = confirm_import(data, self.user)
        self.assertEqual(batch.paper.paper_name, "Previous Year Paper")
        second = self.data([values(question_number="2")], new_paper=True)
        second["selection"]["paper"].update(paper_name="Previous Year Paper")
        second["selection"]["acknowledge_existing"] = True
        self.assertEqual(confirm_import(second, self.user).paper_id, batch.paper_id)
        self.assertEqual(PaperQuestion.objects.filter(paper=batch.paper).count(), 2)

    def test_duplicate_file_is_scoped_by_mode_exam_set_and_paper_identity(self):
        first = self.general()
        confirm_import(first, self.user)
        repeated = self.general()
        self.assertGreater(validate(repeated)["error_count"], 0)
        other = Exam.objects.create(authority=self.authority, name="Other", code="OTHER", slug="other")
        different_context = self.general(exam_ids=[other.pk])
        confirm_import(different_context, self.user)
        previous = self.data()
        confirm_import(previous, self.user)
        self.assertEqual(ImportBatch.objects.count(), 3)

    def test_general_question_numbers_are_batch_local_and_unique(self):
        duplicate = self.general([values(), values()])
        self.assertGreater(validate(duplicate)["error_count"], 0)
        confirm_import(self.general(), self.user)
        # A distinct batch in a different exam context may use the same local number.
        other = Exam.objects.create(authority=self.authority, name="Other", code="OTHER", slug="other")
        confirm_import(self.general(exam_ids=[other.pk]), self.user)
        self.assertFalse(PaperQuestion.objects.exists())

    def test_type_and_mode_specific_required_fields(self):
        form = UploadForm(data={"exam": self.exam.pk}, files={"file": csv_file()})
        self.assertFalse(form.is_valid())
        self.assertIn("import_type", form.errors)
        form = UploadForm(data={"import_type": "previous_year", "exam": self.exam.pk}, files={"file": csv_file()})
        self.assertFalse(form.is_valid())
        self.assertIn("year", form.errors)
        general = UploadForm(data={"import_type": "general", "exams": [self.exam.pk], "year": "not applicable"}, files={"file": csv_file()})
        self.assertTrue(general.is_valid(), general.errors)

    def test_general_upload_preview_and_completion_render_without_paper(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("imports:upload"), {"import_type": "general", "exams": [self.exam.pk], "file": xlsx_file()})
        self.assertEqual(response.status_code, 302)
        preview = self.client.get(response.url)
        self.assertContains(preview, "General Question Bank")
        self.assertContains(preview, "Not applicable (no paper will be created)")
        self.assertEqual(Question.objects.count(), 0)
        data = preview.context["data"]
        from .staging import digest
        result = self.client.post(reverse("imports:confirm", args=[data["token"]]), {"version": digest(data)}, follow=True)
        self.assertContains(result, "Imported safely")
        self.assertNotContains(result, "Open paper in Admin")
        self.assertFalse(PaperQuestion.objects.exists())

    def test_existing_batch_context_backfill_matches_runtime_hash(self):
        batch = confirm_import(self.data(), self.user)
        batch.context_sha256 = ""
        batch.save(update_fields=["context_sha256"])
        migration = import_module("imports.migrations.0002_unified_import")
        migration.backfill_contexts(apps, SimpleNamespace(connection=connection))
        batch.refresh_from_db()
        self.assertEqual(batch.context_sha256, context_hash(self.data(), batch.paper))
