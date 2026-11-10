from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from exams.models import Subject, Part, Module, Chapter, Topic
from previous_year.models import PaperQuestion
from questions.models import Question, QuestionTopic
from questions.tagging import set_question_topics
from . import staging
from .models import ImportBatch
from .parsing import COLUMNS, TAXONOMY_COLUMNS, columns_for, parse_upload
from .services import confirm_import
from .taxonomy import TaxonomyCatalogue
from .tests import ImportFixture, csv_file, values, xlsx_file
from .validation import validate


class TaxonomyImportTests(ImportFixture):
    def test_parent_name_columns_resolve_case_insensitively_in_csv_and_xlsx(self):
        row = values(subject="english", part="india", module="LANGUAGE", chapter="Basics", topic="Primary")
        for upload in (csv_file([row]), xlsx_file([row])):
            data = self.data()
            data.update(parse_upload(upload))
            result = validate(data)
            self.assertEqual(result["error_count"], 0)
            self.assertEqual(result["rows"][0]["topic"].pk, self.primary.pk)

    def test_parent_name_conflicts_unknown_names_and_ambiguity_are_rejected(self):
        Module.objects.create(subject=self.subject, name="Language", slug="root-language")
        for changes in ({"module": "Language"}, {"part": "Wrong", "part_code": "P1"}):
            data = self.data([values(**changes)])
            self.assertGreater(validate(data)["error_count"], 0)
        data = self.data([values(part="India", module="Language", chapter="Basics", topic="Primary")])
        self.assertEqual(validate(data)["error_count"], 0)

    def test_new_hierarchy_is_read_only_in_preview_and_created_for_pair(self):
        row = values(part="New part", module="New module", chapter="New chapter", topic="New topic", topic_code="NEW-T")
        data = self.data([row, {**row, "language": "bn", "question_text": "Translated question"}])
        models = (Subject, Part, Module, Chapter, Topic)
        counts = [model.objects.count() for model in models]
        group = validate(data)["groups"][0]
        self.assertEqual(counts, [model.objects.count() for model in models])
        data["pairings"] = {group["number"]: group["signature"]}
        self.assertEqual(validate(data)["error_count"], 0)
        batch = confirm_import(data, self.user)
        topic = batch.imported_questions.first().question.topic
        self.assertEqual(topic.code, "NEW-T")
        self.assertEqual(topic.chapter.module.part.name, "New part")
        self.assertEqual(topic.subject, self.subject)
        self.assertEqual([counts[0]] + [count + 1 for count in counts[1:]],
                         [model.objects.count() for model in models])
        self.assertEqual(confirm_import(data, self.user).pk, batch.pk)

    def test_new_hierarchy_requires_existing_subject_and_rolls_back(self):
        data = self.data([values(subject="Missing subject", part="New part", topic="New topic")])
        with self.assertRaises(ValidationError):
            confirm_import(data, self.user)
        self.assertFalse(Subject.objects.filter(name="Missing subject").exists())
        self.assertFalse(Part.objects.filter(name="New part").exists())
        data = self.data([values(part="New part", topic="New topic")])
        with patch("imports.services.create_question", side_effect=ValidationError("Failure")):
            with self.assertRaises(ValidationError):
                confirm_import(data, self.user)
        self.assertFalse(Part.objects.filter(name="New part").exists())
        self.assertFalse(Topic.objects.filter(name="New topic").exists())

    def test_source_number_is_metadata_when_both_number_headers_exist(self):
        data = self.data([values(question_number="1", source_question_number="original-42", topic="Grammar")])
        batch = confirm_import(data, self.user)
        self.assertEqual(PaperQuestion.objects.get().question_number, "1")
        self.assertEqual(batch.imported_questions.get().source_metadata["original"]["source_question_number"], "original-42")

    def test_source_number_can_supply_missing_question_number_header(self):
        row = values(source_question_number="0042")
        data = self.data()
        data.update(parse_upload(csv_file([row], headers=[column for column in COLUMNS if column != "question_number"])))
        self.assertEqual(data["rows"][0]["values"]["question_number"], "0042")
        self.assertEqual(validate(data)["error_count"], 0)
        confirm_import(data, self.user)
        self.assertEqual(PaperQuestion.objects.get().question_number, "0042")

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.part = Part.objects.create(subject=cls.subject, name="India", slug="india", code="P1")
        cls.module = Module.objects.create(part=cls.part, name="Language", slug="language", code="M1")
        cls.chapter = Chapter.objects.create(module=cls.module, name="Basics", slug="basics", code="C1")
        cls.primary = Topic.objects.create(subject=cls.subject, chapter=cls.chapter, name="Primary", slug="primary", code="T1")
        cls.secondary = Topic.objects.create(subject=cls.subject, name="Secondary", slug="secondary", code="T2")
        cls.other_subject = Subject.objects.create(name="History", code="HI", slug="history")
        cls.foreign = Topic.objects.create(subject=cls.other_subject, name="Foreign", slug="foreign", code="TF")

    def coded(self, **changes):
        return values(subject="", subject_code="EN", topic_code="T1", **changes)

    def test_csv_xlsx_complete_path_and_secondary_tags_in_both_modes(self):
        row = self.coded(part_code="P1", module_code="M1", chapter_code="C1", additional_topic_codes="T2; T2 | T1,T2")
        for upload in (csv_file([row]), xlsx_file([row])):
            parsed = parse_upload(upload)
            self.assertEqual(parsed["rows"][0]["values"]["chapter_code"], "C1")
        for mode in ("previous_year", "general"):
            data = self.data([row])
            if mode == "general":
                data["selection"] = {"import_type": mode, "exam_ids": [self.exam.pk]}
            result = validate(data)
            self.assertEqual(result["error_count"], 0)
            self.assertIn("Basics [C1]", result["rows"][0]["taxonomy_path"])
            batch = confirm_import(data, self.user)
            question = batch.imported_questions.get().question
            self.assertEqual(question.topic_id, self.primary.pk)
            self.assertEqual(set(question.topic_associations.values_list("topic_id", "is_primary")), {(self.primary.pk, True), (self.secondary.pk, False)})
            self.assertEqual(question.publication_status, "draft")
            self.assertEqual(question.review_status, "pending_review")
            self.assertEqual(set(question.exams.values_list("pk", flat=True)), {self.exam.pk})
            self.assertEqual(confirm_import(data, self.user).pk, batch.pk)
        self.assertEqual(PaperQuestion.objects.count(), 1)

    def test_every_skipped_parent_path_and_subject_inference(self):
        root_module = Module.objects.create(subject=self.subject, name="Root module", slug="root-module")
        root_chapter = Chapter.objects.create(subject=self.subject, name="Root chapter", slug="root-chapter")
        part_chapter = Chapter.objects.create(part=self.part, name="Part chapter", slug="part-chapter")
        parents = [{}, {"part": self.part}, {"module": self.module}, {"chapter": self.chapter},
                   {"module": root_module}, {"chapter": root_chapter}, {"chapter": part_chapter}]
        for index, parent in enumerate(parents):
            topic = Topic.objects.create(subject=self.subject, name=f"Skipped {index}", slug=f"skipped-{index}", **parent)
            row = values(subject="", topic_code=topic.code, **{kind + "_code": node.code for kind, node in parent.items()})
            result = validate(self.data([row]))
            self.assertEqual(result["error_count"], 0)
            self.assertEqual(result["rows"][0]["subject"].pk, self.subject.pk)
            self.assertEqual(result["rows"][0]["topic"].pk, topic.pk)

    def test_unknown_codes_names_and_invalid_ancestry_block_without_writes(self):
        other_part = Part.objects.create(subject=self.subject, name="World", slug="world", code="P2")
        bad = [{"topic_code": "missing"}, {"additional_topic_codes": "missing"},
               {"subject_code": "HI"}, {"part_code": other_part.code},
               {"additional_topic_codes": "TF"}, {"subject": "History"},
               {"topic": "Grammar"}, {"chapter_code": "missing"}, {"subject_code": "missing"}]
        before = Question.objects.count()
        for changes in bad:
            row = self.coded()
            row.update(changes)
            data = self.data([row])
            self.assertGreater(validate(data)["error_count"], 0, changes)
            with self.assertRaises(ValidationError):
                confirm_import(data, self.user)
        self.assertEqual(Question.objects.count(), before)
        self.assertFalse(ImportBatch.objects.exists())

    def test_ambiguous_topic_name_can_be_disambiguated_by_parent_code(self):
        Topic.objects.create(subject=self.subject, name="Primary", slug="root-primary")
        data = self.data([values(topic="primary")])
        self.assertGreater(validate(data)["error_count"], 0)
        data["rows"][0]["values"]["chapter_code"] = "C1"
        result = validate(data)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["rows"][0]["topic"].pk, self.primary.pk)

    def test_blank_topic_is_allowed_but_secondary_only_is_rejected(self):
        data = self.data([values()])
        question = confirm_import(data, self.user).imported_questions.get().question
        self.assertIsNone(question.topic_id)
        self.assertFalse(question.topic_associations.exists())
        data = self.data([values(question_number="2", additional_topic_codes="T2")])
        self.assertGreater(validate(data)["error_count"], 0)

    def test_intermediate_without_topic_is_context_only(self):
        result = validate(self.data([values(subject="", module_code="M1")]))
        self.assertEqual(result["error_count"], 0)
        self.assertIsNone(result["rows"][0]["topic"])
        self.assertTrue(any("context only" in warning for warning in result["rows"][0]["warnings"]))

    def test_bilingual_pairing_requires_identical_topic_sets_and_reapproval(self):
        english = self.coded(additional_topic_codes="T2")
        bengali = self.coded(language="bn", question_text="বাংলা প্রশ্ন", additional_topic_codes="T2;T2")
        data = self.data([english, bengali])
        group = validate(data)["groups"][0]
        data["pairings"] = {group["number"]: group["signature"]}
        self.assertEqual(validate(data)["error_count"], 0)
        data["rows"][1]["values"]["additional_topic_codes"] = ""
        self.assertGreater(validate(data)["error_count"], 0)
        data["rows"][1]["values"]["additional_topic_codes"] = "T2;T2"
        batch = confirm_import(data, self.user)
        question = Question.objects.get()
        self.assertEqual(batch.row_count, 2)
        self.assertEqual(question.current_revision.translations.count(), 2)
        self.assertEqual(question.topic_associations.count(), 2)

    def test_duplicate_text_never_overwrites_existing_tags(self):
        first = confirm_import(self.data([self.coded(additional_topic_codes="T2")]), self.user)
        original = first.imported_questions.get().question
        data = self.data([values(question_number="2", topic_code=self.topic.code)])
        data["selection"]["acknowledge_existing"] = True
        self.assertTrue(any("duplicate" in warning for warning in validate(data)["rows"][0]["warnings"]))
        duplicate = confirm_import(data, self.user).imported_questions.get().question
        self.assertNotEqual(original.pk, duplicate.pk)
        original.refresh_from_db()
        self.assertEqual(original.topic_id, self.primary.pk)
        self.assertEqual(set(original.topic_associations.values_list("topic_id", flat=True)), {self.primary.pk, self.secondary.pk})

    def test_late_tagging_failure_rolls_back_batch_questions_and_paper_rows(self):
        data = self.data([self.coded(), values(question_number="2", topic_code="T2")])
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValidationError("Late tagging failure")
            return set_question_topics(*args, **kwargs)
        with patch("imports.services.set_question_topics", side_effect=fail_second), self.assertRaises(ValidationError):
            confirm_import(data, self.user)
        self.assertFalse(Question.objects.exists())
        self.assertFalse(QuestionTopic.objects.exists())
        self.assertFalse(PaperQuestion.objects.exists())
        self.assertFalse(ImportBatch.objects.exists())

    def test_preview_displays_paths_and_edits_codes_before_commit(self):
        data = self.data([self.coded(additional_topic_codes="unknown")])
        self.client.force_login(self.user)
        url = reverse("imports:preview", args=[data["token"]])
        response = self.client.get(url)
        self.assertContains(response, "Primary [T1]")
        self.assertContains(response, "Unknown additional topic code")
        response = self.client.post(url, {"action": "edit", "version": staging.digest(data),
            "row_0_additional_topic_codes": "T2", "page": "1"})
        self.assertEqual(response.status_code, 200)
        saved = staging.load(data["token"], self.user)
        self.assertEqual(validate(saved)["error_count"], 0)
        question = confirm_import(saved, self.user).imported_questions.get().question
        self.assertEqual(question.topic_associations.count(), 2)

    def test_old_staging_can_edit_new_columns_and_original_metadata_is_preserved(self):
        data = self.data()
        for column in TAXONOMY_COLUMNS:
            data["rows"][0]["values"].pop(column)
        staging.save(data)
        self.client.force_login(self.user)
        response = self.client.get(reverse("imports:preview", args=[data["token"]]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["version"], staging.digest(data))
        self.assertTrue(set(TAXONOMY_COLUMNS) <= set(columns_for(data)))
        self.assertEqual(validate(data)["error_count"], 0)
        self.assertFalse(Question.objects.exists())
        data["rows"][0]["values"]["topic_code"] = "T1"
        batch = confirm_import(data, self.user)
        metadata = batch.imported_questions.get().source_metadata
        self.assertEqual(metadata["original"]["topic_code"], "")
        self.assertEqual(metadata["corrected"]["topic_code"], "T1")
        self.assertEqual(metadata["resolved"]["topic_ids"], [self.primary.pk])

    def test_ambiguous_subject_names_need_explicit_mapping_or_code(self):
        Subject.objects.create(name="ENGLISH", slug="english-duplicate", code="EN2")
        data = self.data([values(subject="english")])
        self.assertGreater(validate(data)["error_count"], 0)
        data["rows"][0]["values"]["subject_code"] = "EN"
        self.assertEqual(validate(data)["error_count"], 0)

    def test_csv_xlsx_samples_have_matching_supported_headers_and_rows(self):
        parsed = []
        for suffix in ("csv", "xlsx"):
            path = settings.BASE_DIR / "docs" / "samples" / f"questions-taxonomy.{suffix}"
            data = parse_upload(SimpleUploadedFile(path.name, path.read_bytes()))
            self.assertEqual(data["source_headers"], list(COLUMNS))
            parsed.append([row["values"] for row in data["rows"]])
        self.assertEqual(parsed[0], parsed[1])

    def test_taxonomy_resolution_query_count_does_not_grow_per_row(self):
        with self.assertNumQueries(5):
            catalogue = TaxonomyCatalogue()
        with self.assertNumQueries(0):
            for _ in range(30):
                resolved = catalogue.resolve(self.coded(additional_topic_codes="T2"), {}, {}, {})
                self.assertFalse(resolved["taxonomy_errors"])
