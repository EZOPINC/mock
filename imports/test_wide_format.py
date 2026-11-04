import csv
from io import BytesIO, StringIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook

from previous_year.models import PaperQuestion
from questions.models import Question
from .parsing import columns_for, parse_upload, preview_page_size
from .services import confirm_import
from .staging import digest, load, save
from .tests import ImportFixture, values
from .validation import validate


def extracted_values(**changes):
    row = values(subject="", correct_answer="", language="en,bn")
    for field in ("question_text", "option_a", "option_b", "option_c", "option_d"):
        row[f"{field}_en"] = row[field]
    row.update(question_text_bn="বাংলা প্রশ্ন ∑ x²\nদ্বিতীয় লাইন", option_a_bn="এক", option_b_bn="দুই", option_c_bn="তিন", option_d_bn="চার",
               handwritten_mark_unverified="A", needs_review="Y")
    return row | changes


def extracted_file(rows=None, *, xlsx=False, only_wide=False):
    rows = rows or [extracted_values()]
    headers = list(rows[0])
    if only_wide:
        headers = [key for key in headers if key not in {"question_text", "option_a", "option_b", "option_c", "option_d"}]
    if xlsx:
        book = Workbook()
        book.active.append(headers)
        for row in rows:
            book.active.append([row.get(key, "") for key in headers])
        stream = BytesIO()
        book.save(stream)
        book.close()
        return SimpleUploadedFile("extracted.xlsx", stream.getvalue())
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows([row.get(key, "") for key in headers] for row in rows)
    return SimpleUploadedFile("extracted.csv", stream.getvalue().encode("utf-8-sig"))


class WideExtractionImportTests(ImportFixture):
    def data_from_file(self, upload):
        data = self.data()
        data.update(parse_upload(upload))
        for row in data["rows"]:
            row["original_values"] = dict(row["values"])
        return data

    def test_csv_xlsx_and_wide_only_headers_create_two_versions_per_physical_row(self):
        for xlsx, only_wide in ((False, False), (True, False), (False, True)):
            data = self.data_from_file(extracted_file([extracted_values(correct_answer="B")], xlsx=xlsx, only_wide=only_wide))
            result = validate(data)
            self.assertEqual(result["error_count"], 0)
            self.assertEqual(result["master_count"], 1)
            self.assertEqual(result["rows"][0]["translation_languages"], ["en", "bn"])
            self.assertFalse(result["groups"][0]["requires_pairing"])
            self.assertEqual(data["input_format"], "wide_multilingual")
        self.assertFalse(Question.objects.exists())

    def test_unverified_handwritten_marks_never_fill_missing_answers(self):
        data = self.data_from_file(extracted_file())
        result = validate(data)
        self.assertGreater(result["error_count"], 0)
        self.assertEqual(result["rows"][0]["revision"]["correct_answer"], "")
        self.assertTrue(any("NOT a verified answer key" in warning for warning in result["rows"][0]["warnings"]))
        with self.assertRaises(ValidationError):
            confirm_import(data, self.user)
        self.assertFalse(Question.objects.exists())

    def test_corrected_answer_imports_one_master_two_translations_and_original_audit(self):
        data = self.data_from_file(extracted_file())
        data["rows"][0]["values"]["correct_answer"] = "B"
        batch = confirm_import(data, self.user)
        question = Question.objects.get()
        self.assertEqual(question.correct_answer, "B")
        self.assertEqual(question.publication_status, "draft")
        self.assertEqual(question.review_status, "pending_review")
        self.assertEqual(question.current_revision.translations.count(), 2)
        self.assertEqual(question.current_revision.translations.get(language="bn").question_text, extracted_values()["question_text_bn"])
        self.assertEqual(PaperQuestion.objects.count(), 1)
        record = batch.imported_questions.get()
        self.assertEqual(record.source_metadata["original"]["correct_answer"], "")
        self.assertEqual(record.source_metadata["original"]["language"], "en,bn")
        self.assertEqual(record.source_metadata["original"]["handwritten_mark_unverified"], "A")
        self.assertEqual(record.source_metadata["original"]["needs_review"], "Y")
        self.assertEqual(record.source_metadata["resolved"]["languages"], ["en", "bn"])

    def test_partial_language_and_generic_conflicts_need_manual_correction(self):
        for changes in ({"option_d_bn": ""}, {"question_text": "Different generic question"}):
            result = validate(self.data_from_file(extracted_file([extracted_values(correct_answer="A", **changes)])))
            self.assertGreater(result["error_count"], 0)

    def test_absent_language_block_never_creates_placeholder_translation(self):
        row = extracted_values(correct_answer="C")
        for field in ("question_text", "option_a", "option_b", "option_c", "option_d"):
            row[field + "_bn"] = ""
        data = self.data_from_file(extracted_file([row]))
        result = validate(data)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["rows"][0]["translation_languages"], ["en"])

    def test_generic_english_plus_explicit_bengali_columns_preserves_both(self):
        row = extracted_values(correct_answer="B")
        for key in list(row):
            if key.endswith("_en"):
                del row[key]
        result = validate(self.data_from_file(extracted_file([row])))
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(set(result["rows"][0]["translation_languages"]), {"en", "bn"})

    def test_duplicate_wide_question_numbers_are_not_silently_merged(self):
        data = self.data_from_file(extracted_file([extracted_values(correct_answer="A"), extracted_values(correct_answer="A")]))
        self.assertGreater(validate(data)["error_count"], 0)

    def test_wide_preview_editing_uses_safe_dynamic_page_size_and_escaped_metadata(self):
        data = self.data_from_file(extracted_file([extracted_values(question_number=str(n), handwritten_mark_unverified="<script>unsafe</script>") for n in range(30)]))
        save(data)
        self.client.force_login(self.user)
        url = reverse("imports:preview", args=[data["token"]])
        response = self.client.get(url)
        self.assertContains(response, "question_text_bn")
        self.assertContains(response, "needs_review")
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>unsafe</script>")
        size = preview_page_size(data)
        self.assertLess(size, 25)
        self.assertLess(size * len(columns_for(data)), 900)
        self.client.post(url, {"version": digest(data), "page": "2", f"row_{size}_correct_answer": "D"})
        edited = load(data["token"], self.user)
        self.assertEqual(edited["rows"][size]["values"]["correct_answer"], "D")
        self.assertEqual(edited["rows"][0]["values"]["correct_answer"], "")
