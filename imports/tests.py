import csv
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import time
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from exams.models import Exam, ExamAuthority, Subject, Topic
from previous_year.models import PaperQuestion, PreviousYearPaper
from previous_year.services import publish_paper, published_papers
from questions.models import Question, QuestionExam, QuestionRevision, QuestionSourceReference
from questions.services import mark_reviewed, publish_question
from . import staging
from .models import ImportBatch, ImportedQuestion
from .parsing import COLUMNS, parse_upload
from .services import confirm_import
from .validation import validate


def values(**overrides):
    return dict.fromkeys(COLUMNS, "") | {"question_number": "1(a)", "question_text": "Choose an answer.\nPreserve this line.", "option_a": "One", "option_b": "Two", "option_c": "Three", "option_d": "Four", "correct_answer": "A", "subject": "English", "language": "en"} | overrides


def csv_file(rows=None, headers=COLUMNS, name="questions.csv"):
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows or [values()]:
        writer.writerow([row.get(key.strip().lower(), "") for key in headers])
    return SimpleUploadedFile(name, output.getvalue().encode("utf-8-sig"))


def xlsx_file(rows=None, *, second_sheet=False, formula=False):
    book = Workbook()
    book.active.title = "Questions"
    book.active.append(list(COLUMNS) + [None])
    for row in rows or [values()]:
        book.active.append([row[key] for key in COLUMNS] + [None])
    if formula:
        book.active.cell(2, 2, "=1+1")
    if second_sheet:
        book.create_sheet("Other")
    stream = BytesIO()
    book.save(stream)
    book.close()
    return SimpleUploadedFile("questions.xlsx", stream.getvalue())


class ParsingTests(TestCase):
    def test_review_flag_alias_csv_and_xlsx(self):
        headers = [" Review_Flag " if field == "review_status" else field for field in COLUMNS]
        row = values(review_flag="reviewed")
        book = Workbook()
        book.active.append(headers)
        book.active.append([row.get(field.strip().lower(), "") for field in headers])
        stream = BytesIO()
        book.save(stream)
        book.close()
        for upload in (csv_file([row], headers=headers), SimpleUploadedFile("questions.xlsx", stream.getvalue())):
            with self.subTest(name=upload.name):
                data = parse_upload(upload)
                self.assertEqual(data["rows"][0]["values"]["review_status"], "reviewed")
                self.assertEqual(data["header_aliases"], {"review_flag": "review_status"})

    def test_review_flag_and_review_status_together_are_rejected(self):
        with self.assertRaisesMessage(ValidationError, "Keep only one"):
            parse_upload(csv_file(headers=(*COLUMNS, "review_flag")))

    def test_csv_headers_case_whitespace_and_unicode_multiline(self):
        row = values(language="bn", question_text="  বাংলা প্রশ্ন\nপরের লাইন  ")
        data = parse_upload(csv_file([row], headers=[" " + key.upper() + " " for key in COLUMNS]))
        self.assertEqual(data["rows"][0]["values"]["question_text"], row["question_text"])
        self.assertEqual(data["rows"][0]["source_row"], 2)

    def test_xlsx_and_trailing_empty_column(self):
        data = parse_upload(xlsx_file([values(question_text="বাংলা", language="bn")]))
        self.assertEqual(data["worksheet"], "Questions")
        self.assertEqual(data["rows"][0]["values"]["question_text"], "বাংলা")

    def test_required_headers_and_duplicate_unknown_headers(self):
        for headers in (("question_text",), (*COLUMNS, "question_text"), (*COLUMNS, "unknown")):
            with self.subTest(headers=headers), self.assertRaises(ValidationError):
                parse_upload(csv_file(headers=headers))

    def test_optional_columns_not_required(self):
        from .parsing import REQUIRED
        self.assertEqual(len(parse_upload(csv_file(headers=REQUIRED))["rows"]), 1)

    def test_multisheet_requires_explicit_selection(self):
        with self.assertRaises(ValidationError):
            parse_upload(xlsx_file(second_sheet=True))
        self.assertEqual(parse_upload(xlsx_file(second_sheet=True), "Questions")["worksheet"], "Questions")

    def test_formulas_invalid_files_and_size_limits(self):
        for file in (xlsx_file(formula=True), SimpleUploadedFile("bad.xlsm", b"bad"), SimpleUploadedFile("bad.xlsx", b"bad")):
            with self.subTest(name=file.name), self.assertRaises(ValidationError):
                parse_upload(file)
        with override_settings(IMPORT_MAX_UPLOAD_BYTES=10), self.assertRaises(ValidationError):
            parse_upload(csv_file())

    def test_nonempty_unnamed_column_and_row_limit(self):
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow([*COLUMNS, ""])
        writer.writerow([values()[key] for key in COLUMNS] + ["do not discard"])
        with self.assertRaises(ValidationError):
            parse_upload(SimpleUploadedFile("questions.csv", output.getvalue().encode()))
        with override_settings(IMPORT_MAX_ROWS=1), self.assertRaises(ValidationError):
            parse_upload(csv_file([values(), values(question_number="2")]))


class ImportFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(username="admin", email="admin@example.test")
        cls.authority = ExamAuthority.objects.create(name="Commission", code="PC", slug="commission")
        cls.exam = Exam.objects.create(authority=cls.authority, name="Clerkship", code="CLERK", slug="clerkship")
        cls.subject = Subject.objects.create(name="English", code="EN", slug="english")
        cls.topic = Topic.objects.create(subject=cls.subject, name="Grammar", slug="grammar")
        cls.paper = PreviousYearPaper.objects.create(exam=cls.exam, year=2023, paper_name="Preliminary")

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(IMPORT_STAGING_ROOT=Path(self.directory.name))
        self.override.enable()
        self.addCleanup(self.override.disable)

    def data(self, rows=None, *, new_paper=False):
        result = parse_upload(csv_file(rows))
        for row in result["rows"]:
            row["original_values"] = dict(row["values"])
        return staging.create(self.user, {**result, "selection": {
            "authority_id": self.authority.pk, "exam_id": self.exam.pk,
            "paper_id": None if new_paper else self.paper.pk,
            "paper": {"year": 2024, "stage_id": None, "paper_name": "New Paper", "part": "", "session": ""},
            "exam_aliases": "", "paper_aliases": "",
        }, "subject_map": {}, "topic_map": {}})


class ValidationTests(ImportFixture):
    def test_preview_no_domain_or_audit_database_writes(self):
        data = self.data()
        before = (Question.objects.count(), QuestionRevision.objects.count(), ImportBatch.objects.count(), PaperQuestion.objects.count(), PreviousYearPaper.objects.count())
        self.assertEqual(validate(data)["error_count"], 0)
        self.assertEqual(before, (Question.objects.count(), QuestionRevision.objects.count(), ImportBatch.objects.count(), PaperQuestion.objects.count(), PreviousYearPaper.objects.count()))

    def test_invalid_content_answer_language_and_subject(self):
        for change in ({"option_d": ""}, {"correct_answer": "E"}, {"language": "fr"}, {"subject": "Unknown"}, {"source_page": "-1", "source_document": "Book"}):
            with self.subTest(change=change):
                self.assertGreater(validate(self.data([values(**change)]))["error_count"], 0)

    def test_optional_topic_and_explicit_taxonomy_mapping(self):
        data = self.data([values(subject="Alias", topic="Alias topic")])
        self.assertGreater(validate(data)["error_count"], 0)
        data["subject_map"] = {"alias": self.subject.pk}
        data["topic_map"] = {"alias / alias topic": self.topic.pk}
        self.assertEqual(validate(data)["error_count"], 0)
        data["rows"][0]["values"]["topic"] = ""
        self.assertEqual(validate(data)["error_count"], 0)

    def test_previous_year_source_tags_are_metadata_not_required_mappings(self):
        data = self.data([values(exam_categories="PSC Clerkship", previous_year_tags="Prelims 2023")])
        self.assertEqual(validate(data)["error_count"], 0)
        data["rows"].append({"source_row": 3, "values": values(question_number="2", previous_year_tags="Prelims 2022")})
        self.assertEqual(validate(data)["error_count"], 0)
        self.assertGreater(validate(data)["warning_count"], 0)

    def test_duplicate_numbers_and_duplicate_text_warning(self):
        data = self.data([values(), values()])
        result = validate(data)
        self.assertGreater(result["error_count"], 0)
        self.assertGreater(result["warning_count"], 0)
        data["rows"][1]["values"]["question_number"] = "2"
        self.assertEqual(validate(data)["error_count"], 0)

    def test_existing_paper_number_conflict_and_file_hash(self):
        data = self.data()
        confirm_import(data, self.user)
        data["token"] = str(uuid.uuid4())
        result = validate(data)
        self.assertIn("already been imported", " ".join(result["errors"]))
        self.assertIn("already exists", " ".join(result["rows"][0]["errors"]))

    def test_existing_import_requires_explicit_append_acknowledgment(self):
        confirm_import(self.data(), self.user)
        second = self.data([values(question_number="2")])
        self.assertIn("explicitly acknowledge", " ".join(validate(second)["errors"]))
        second["selection"]["acknowledge_existing"] = True
        self.assertEqual(validate(second)["error_count"], 0)
        confirm_import(second, self.user)
        self.assertEqual(PaperQuestion.objects.filter(paper=self.paper).count(), 2)

    def test_normal_manual_association_still_rejects_draft_revisions(self):
        from questions.services import create_question
        revision_data = {key: values()[key] for key in ("language", "question_text", "option_a", "option_b", "option_c", "option_d", "correct_answer", "explanation")}
        question = create_question(subject=self.subject, revision=revision_data)
        QuestionExam.objects.create(question=question, exam=self.exam)
        with self.assertRaises(ValidationError):
            PaperQuestion.objects.create(paper=self.paper, question_revision=question.current_revision, question_number="1", display_order=1)


class ConfirmationTests(ImportFixture):
    def test_review_flag_alias_is_audit_metadata_not_approval(self):
        data = self.data([values(review_status="reviewed")])
        data["header_aliases"] = {"review_flag": "review_status"}
        batch = confirm_import(data, self.user)
        record = batch.imported_questions.get()
        self.assertEqual(batch.mapping_metadata["header_aliases"], {"review_flag": "review_status"})
        self.assertEqual(record.source_metadata["original"]["review_status"], "reviewed")
        self.assertEqual(record.question.review_status, "pending_review")
        self.assertEqual(record.question.publication_status, "draft")

    def test_draft_transaction_audit_source_and_preserved_text(self):
        data = self.data([values(language="bn", question_text="  বাংলা প্রশ্ন\nদ্বিতীয় লাইন  ", source_document="Book.pdf", source_page="iv", review_status="42", verification_notes="reviewed", updated_by="legacy", difficulty_level="hard")])
        batch = confirm_import(data, self.user)
        question = batch.imported_questions.get().question
        self.assertEqual(connection.vendor, "postgresql")
        self.assertEqual(question.review_status, "pending_review")
        self.assertEqual(question.publication_status, "draft")
        self.assertEqual(question.current_revision.question_text, data["rows"][0]["values"]["question_text"])
        self.assertEqual(QuestionSourceReference.objects.get(question=question).source_page, "iv")
        self.assertEqual(batch.imported_questions.get().source_metadata["original"]["review_status"], "42")
        self.assertFalse(published_papers().filter(pk=self.paper.pk).exists())
        with self.assertRaises(ValidationError):
            publish_paper(self.paper)
        publish_question(mark_reviewed(question))
        self.assertTrue(publish_paper(self.paper).is_published)

    def test_repeated_confirmation_is_idempotent(self):
        data = self.data()
        first = confirm_import(data, self.user)
        self.assertEqual(confirm_import(data, self.user).pk, first.pk)
        self.assertEqual(Question.objects.count(), 1)

    def test_atomic_rollback_after_a_row_was_created(self):
        data = self.data([values(), values(question_number="2")], new_paper=True)
        original = PaperQuestion.save
        count = 0
        def failing(instance, *args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise ValidationError("Late failure")
            return original(instance, *args, **kwargs)
        with patch.object(PaperQuestion, "save", new=failing), self.assertRaises(ValidationError):
            confirm_import(data, self.user)
        for model in (Question, QuestionRevision, QuestionExam, PaperQuestion, ImportBatch, ImportedQuestion):
            self.assertEqual(model.objects.count(), 0)
        self.assertFalse(PreviousYearPaper.objects.filter(paper_name="New Paper").exists())

    def test_confirmation_revalidates_changed_taxonomy_and_permissions(self):
        data = self.data()
        self.subject.name = "Renamed after preview"
        self.subject.save()
        with self.assertRaises(ValidationError):
            confirm_import(data, self.user)
        self.user.is_staff = False
        self.user.save()
        with self.assertRaises(PermissionDenied):
            confirm_import(data, self.user)


class ImportViewTests(ImportFixture):
    def test_staff_permissions_and_stage_owner(self):
        url = reverse("imports:upload")
        self.assertEqual(self.client.get(url).status_code, 302)
        staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(url).status_code, 403)
        data = self.data()
        other = get_user_model().objects.create_superuser(username="other", email="other@example.test")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("imports:preview", args=[data["token"]])).status_code, 404)

    def test_upload_preview_edit_confirm_complete(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("imports:upload"), {"file": csv_file(), "import_type": "previous_year", "year": self.paper.year, "authority": self.authority.pk, "exam": self.exam.pk, "paper": self.paper.pk})
        self.assertEqual(response.status_code, 302)
        preview_url = response.url
        response = self.client.get(preview_url)
        self.assertContains(response, "Check every row")
        self.assertEqual(Question.objects.count(), 0)
        data = response.context["data"]
        response = self.client.post(preview_url, {"version": staging.digest(data), "page": "1", "row_0_question_text": "Edited text"})
        self.assertEqual(response.status_code, 200)
        data = staging.load(data["token"], self.user)
        response = self.client.post(reverse("imports:confirm", args=[data["token"]]), {"version": staging.digest(data)})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(response.url), "Imported safely")
        self.assertEqual(Question.objects.get().current_revision.question_text, "Edited text")
        self.assertEqual(ImportedQuestion.objects.get().source_metadata["original"]["question_text"], values()["question_text"])

    def test_csrf_stale_versions_and_cancel(self):
        self.client.force_login(self.user)
        data = self.data()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        confirm_url = reverse("imports:confirm", args=[data["token"]])
        self.assertEqual(csrf_client.post(confirm_url, {"version": staging.digest(data)}).status_code, 403)
        self.assertEqual(self.client.get(confirm_url).status_code, 405)
        self.client.post(confirm_url, {"version": "stale"})
        self.assertEqual(Question.objects.count(), 0)
        self.client.post(reverse("imports:cancel", args=[data["token"]]))
        self.assertFalse(staging.path_for(data["token"]).exists())

    def test_expiry_and_cleanup(self):
        data = self.data()
        data["expires_at"] = time.time() - 1
        staging.save(data)
        self.assertEqual(staging.cleanup(), 1)
        self.assertFalse(staging.path_for(data["token"]).exists())

    def test_paginated_filtered_preview_and_escaping(self):
        self.client.force_login(self.user)
        data = self.data([values(question_number=str(n), question_text="<script>unsafe</script>") for n in range(30)])
        response = self.client.get(reverse("imports:preview", args=[data["token"]]), {"page": 2})
        self.assertEqual(len(response.context["page"]), 5)
        self.assertNotContains(response, "<script>unsafe</script>")
        self.assertContains(response, "&lt;script&gt;")


class ImportConcurrencyTests(TransactionTestCase):
    def test_concurrent_confirmation_creates_one_batch(self):
        user = get_user_model().objects.create_superuser(username="admin", email="admin@example.test")
        authority = ExamAuthority.objects.create(name="Commission", code="PC", slug="pc")
        exam = Exam.objects.create(authority=authority, name="Exam", code="EX", slug="ex")
        Subject.objects.create(name="English", code="EN", slug="en")
        paper = PreviousYearPaper.objects.create(exam=exam, year=2023, paper_name="Paper")
        data = parse_upload(csv_file()) | {"owner": user.pk, "token": str(uuid.uuid4()), "subject_map": {}, "topic_map": {},
            "selection": {"authority_id": authority.pk, "exam_id": exam.pk, "paper_id": paper.pk, "paper": {}, "exam_aliases": "", "paper_aliases": ""}}
        barrier = Barrier(2)
        def run(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return confirm_import(data, get_user_model().objects.get(pk=user.pk)).pk
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(run, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(Question.objects.count(), 1)
        self.assertEqual(ImportBatch.objects.count(), 1)
