from django.core.exceptions import ValidationError
from django.urls import reverse

from previous_year.models import PaperQuestion
from previous_year.services import publish_paper
from questions.models import Question, QuestionExam
from questions.services import mark_reviewed, publish_question, add_translation
from .services import confirm_import
from .staging import digest, load
from .tests import ImportFixture, values, csv_file, xlsx_file
from .parsing import parse_upload
from .validation import validate


def bilingual_rows(**changes):
    return [values(question_number="1", question_text="Which is one?", difficulty_level="easy"),
            values(question_number="1", question_text="এক কোনটি?", option_a="এক", option_b="দুই", option_c="তিন", option_d="চার", language="bn", difficulty_level="easy") | changes]


class MultilingualImportTests(ImportFixture):
    def approve(self, data):
        groups = validate(data)["groups"]
        data["pairings"] = {group["number"]: group["signature"] for group in groups if group["requires_pairing"]}
        return data

    def test_bilingual_pairing_is_explicit_and_creates_one_master_paper_row(self):
        data = self.data(bilingual_rows())
        result = validate(data)
        self.assertGreater(result["error_count"], 0)
        with self.assertRaises(ValidationError):
            confirm_import(data, self.user)
        batch = confirm_import(self.approve(data), self.user)
        self.assertEqual(Question.objects.count(), 1)
        self.assertEqual(QuestionExam.objects.count(), 1)
        self.assertEqual(PaperQuestion.objects.count(), 1)
        self.assertEqual(batch.imported_questions.count(), 2)
        question = Question.objects.get()
        self.assertEqual(question.translations.count(), 2)
        self.assertEqual(question.correct_answer, "A")
        self.assertEqual(question.difficulty_level, "easy")
        self.assertEqual(question.review_status, "pending_review")

    def test_conflicting_shared_answers_and_same_language_duplicates_never_merge(self):
        for changes in ({"correct_answer": "B"}, {"language": "en"}, {"difficulty_level": "hard"}):
            data = self.approve(self.data(bilingual_rows(**changes)))
            self.assertGreater(validate(data)["error_count"], 0)
            with self.assertRaises(ValidationError):
                confirm_import(data, self.user)
        self.assertEqual(Question.objects.count(), 0)

    def test_changed_pairing_requires_new_confirmation(self):
        data = self.approve(self.data(bilingual_rows()))
        self.assertEqual(validate(data)["error_count"], 0)
        data["rows"][1]["values"]["question_text"] = "Changed translation"
        self.assertGreater(validate(data)["error_count"], 0)

    def test_general_mode_bilingual_and_single_language_csv_xlsx(self):
        for index, file in enumerate((csv_file(bilingual_rows()), xlsx_file([values(language="bn", question_text="বাংলা প্রশ্ন")]))):
            data = self.data()
            parsed = parse_upload(file)
            data.update(parsed)
            data["selection"] = {"import_type": "general", "exam_ids": [self.exam.pk], "exam_mapping": "selected"}
            batch = confirm_import(self.approve(data), self.user)
            self.assertIsNone(batch.paper_id)
            question = batch.imported_questions.first().question
            self.assertEqual(question.current_revision.translations.count(), 2 if index == 0 else 1)
        self.assertFalse(PaperQuestion.objects.exists())

    def test_preview_pairing_controls_save_and_approve_without_domain_writes(self):
        data = self.data(bilingual_rows())
        from .staging import save
        save(data)
        self.client.force_login(self.user)
        url = reverse("imports:preview", args=[data["token"]])
        response = self.client.get(url)
        self.assertContains(response, "Proposed translations")
        group = validate(data)["groups"][0]
        self.client.post(url, {"version": digest(data), "page": "1", f"pair_{group['key']}": "on"})
        self.assertEqual(validate(load(data["token"], self.user))["error_count"], 0)
        self.assertFalse(Question.objects.exists())

    def test_bilingual_public_paper_and_auth_mock_preview_use_saved_snapshot(self):
        batch = confirm_import(self.approve(self.data(bilingual_rows())), self.user)
        question = Question.objects.get()
        publish_question(mark_reviewed(question))
        publish_paper(self.paper)
        url = reverse("previous_year:paper_detail", args=[self.authority.slug, self.exam.slug, self.paper.year, self.paper.pk])
        response = self.client.get(url)
        self.assertContains(response, "Which is one?")
        self.assertContains(response, "এক কোনটি?")
        self.assertContains(response, 'class="translation-grid"')
        add_translation(question, language="bn", question_text="Private new translation", option_a="এক", option_b="দুই", option_c="তিন", option_d="চার")
        self.assertNotContains(self.client.get(url), "Private new translation")
        preview = reverse("mock_tests:question_preview", args=[question.pk])
        self.assertEqual(self.client.get(preview).status_code, 302)
        self.client.force_login(self.user)
        response = self.client.get(preview)
        self.assertContains(response, "এক কোনটি?")
        self.assertNotContains(response, "Correct answer:")
        self.assertNotContains(response, "Private new translation")
