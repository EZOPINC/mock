from django.core.exceptions import ValidationError

from .language import infer_language
from .services import confirm_import
from .tests import ImportFixture, values
from .validation import validate


class LanguageInferenceTests(ImportFixture):
    def test_supported_script_detection_and_ambiguous_text(self):
        cases = [
            (values(question_text="Choose the answer", language=""), "en"),
            (values(question_text="সঠিক উত্তর নির্বাচন করুন।", language=""), "bn"),
            (values(question_text="বাংলা with English terms", language=""), "bn"),
            (values(question_text="2 + 2 = ?", option_a="১", option_b="২", option_c="৩", option_d="৪"), ""),
            (values(question_text="सही उत्तर चुनें"), ""),
            (values(question_text="Find α in this equation"), "en"),
        ]
        for row, expected in cases:
            with self.subTest(text=row["question_text"]):
                self.assertEqual(infer_language(row), expected)

    def test_missing_language_is_inferred_and_saved_with_original_audit(self):
        for index, text in enumerate(("Choose the correct answer", "সঠিক উত্তর কোনটি?")):
            expected = "en" if index == 0 else "bn"
            data = self.data([values(question_number=str(index + 1), question_text=text, language="")])
            data["selection"]["acknowledge_existing"] = True
            result = validate(data)
            self.assertEqual(result["error_count"], 0)
            self.assertEqual(result["rows"][0]["revision"]["language"], expected)
            self.assertTrue(any("Language inferred" in warning for warning in result["rows"][0]["warnings"]))
            record = confirm_import(data, self.user).imported_questions.get()
            self.assertEqual(record.question.current_revision.language, expected)
            self.assertEqual(record.source_metadata["original"]["language"], "")
            self.assertEqual(record.source_metadata["resolved"]["language"], expected)

    def test_explicit_row_and_batch_values_override_inference(self):
        data = self.data([values(question_text="বাংলা প্রশ্ন", language="en")])
        data["selection"]["language"] = "bn"
        self.assertEqual(validate(data)["rows"][0]["revision"]["language"], "en")
        data["rows"][0]["values"]["language"] = ""
        data["selection"]["language"] = "en"
        self.assertEqual(validate(data)["rows"][0]["revision"]["language"], "en")
        data["rows"][0]["values"]["language"] = "fr"
        self.assertGreater(validate(data)["error_count"], 0)

    def test_ambiguous_text_still_requires_language_correction(self):
        data = self.data([values(language="", question_text="2+2=?", option_a="1", option_b="2", option_c="3", option_d="4")])
        self.assertGreater(validate(data)["error_count"], 0)
        with self.assertRaises(ValidationError):
            confirm_import(data, self.user)


class LanguageLabelTests(ImportFixture):
    def test_csv_and_xlsx_normalize_labels_preserving_source(self):
        from .parsing import parse_upload
        from .tests import csv_file, xlsx_file
        for factory in (csv_file, xlsx_file):
            for label, expected in (("English", "en"), (" BENGALI ", "bn"), ("en", "en"), ("BN", "bn"), ("", ""), ("French", "french"), ("English | Bengali", "en|bn")):
                with self.subTest(format=factory.__name__, label=label):
                    row = parse_upload(factory([values(language=label)]))["rows"][0]
                    self.assertEqual(row["values"]["language"], expected)
                    self.assertEqual(row["original_values"]["language"], label)

    def test_preview_corrections_accept_labels_and_unknown_names_stay_invalid(self):
        for label, code in (("English", "en"), ("Bengali", "bn")):
            result = validate(self.data([values(language=label)]))
            self.assertEqual(result["error_count"], 0)
            self.assertEqual(result["rows"][0]["revision"]["language"], code)
        self.assertGreater(validate(self.data([values(language="French")]))["error_count"], 0)
