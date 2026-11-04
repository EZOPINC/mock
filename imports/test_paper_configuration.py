from exams.models import Subject
from questions.models import Question
from .services import confirm_import
from .tests import ImportFixture, values
from .validation import validate


class PaperConfigurationImportTests(ImportFixture):
    def test_preview_rejects_subject_mismatch_without_creating_questions(self):
        other = Subject.objects.create(name="Mathematics", code="MATH", slug="math")
        self.paper.subject = other
        self.paper.save()
        result = validate(self.data())
        self.assertIn("must match", " ".join(result["rows"][0]["errors"]))
        self.assertFalse(Question.objects.exists())

    def test_preview_blocks_overflow_but_accepts_incomplete_draft(self):
        self.paper.expected_question_count = 1
        self.paper.save()
        data = self.data([values(question_number="1"), values(question_number="2")])
        self.assertIn("Expected 1 questions", " ".join(validate(data)["errors"]))
        self.paper.expected_question_count = 3
        self.paper.save()
        self.assertEqual(validate(data)["error_count"], 0)
        batch = confirm_import(data, self.user)
        self.assertEqual(batch.paper_id, self.paper.pk)
        self.assertEqual(self.paper.paper_questions.count(), 2)
