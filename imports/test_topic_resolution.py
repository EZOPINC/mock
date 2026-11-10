from unittest.mock import patch

from django.core.exceptions import ValidationError

from exams.models import Subject, Topic
from questions.models import Question
from .models import ImportBatch
from .services import confirm_import
from .tests import ImportFixture, values
from .validation import normalized, validate


class TopicResolutionTests(ImportFixture):
    def test_import_reuses_classified_topic_without_changing_its_hierarchy(self):
        from exams.models import Part, Module, Chapter
        part = Part.objects.create(subject=self.subject, name="India", slug="india")
        module = Module.objects.create(part=part, name="Language", slug="language")
        chapter = Chapter.objects.create(module=module, name="Grammar", slug="grammar")
        self.topic.chapter = chapter
        self.topic.save()
        data = self.data([values(topic="grammar")])
        result = validate(data)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["rows"][0]["topic"].pk, self.topic.pk)
        confirm_import(data, self.user)
        self.assertEqual(Question.objects.get().topic_id, self.topic.pk)
        self.topic.refresh_from_db()
        self.assertEqual(self.topic.chapter_id, chapter.pk)

    def test_same_topic_name_in_different_chapters_requires_explicit_mapping(self):
        from exams.models import Part, Module, Chapter
        part = Part.objects.create(subject=self.subject, name="India", slug="india")
        module = Module.objects.create(part=part, name="Language", slug="language")
        for slug in ("first", "second"):
            chapter = Chapter.objects.create(module=module, name=slug, slug=slug)
            Topic.objects.create(subject=self.subject, chapter=chapter, name="Shared topic", slug=slug)
        data = self.data([values(topic="Shared topic")])
        self.assertGreater(validate(data)["error_count"], 0)
        selected = Topic.objects.get(slug="second")
        data["topic_map"] = {normalized("English / Shared topic"): selected.pk}
        self.assertEqual(validate(data)["error_count"], 0)
        confirm_import(data, self.user)
        self.assertEqual(Question.objects.get().topic_id, selected.pk)

    def test_subject_and_exact_topic_ignore_case(self):
        for name in ("english", "ENGLISH", " English "):
            with self.subTest(name=name):
                result = validate(self.data([values(subject=name, topic="gRaMmAr")]))
                self.assertEqual(result["error_count"], 0)
                self.assertEqual(result["rows"][0]["subject"], self.subject)
                self.assertEqual(result["rows"][0]["topic"], self.topic)

    def test_prefix_is_rejected_and_exact_match_has_priority(self):
        self.assertGreater(validate(self.data([values(topic="GRAMmatical rules")]))["error_count"], 0)
        Topic.objects.create(subject=self.subject, name="Grammar advanced", slug="advanced")
        result = validate(self.data([values(topic="grammar")]))
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["rows"][0]["topic"], self.topic)

    def test_unknown_topic_requires_existing_mapping(self):
        Topic.objects.create(subject=self.subject, name="Grammar advanced", slug="advanced")
        data = self.data([values(topic="Grammatical rules")])
        self.assertGreater(validate(data)["error_count"], 0)
        self.assertFalse(Topic.objects.filter(name="Grammatical rules").exists())
        data["topic_map"] = {normalized("English / Grammatical rules"): self.topic.pk}
        self.assertEqual(validate(data)["error_count"], 0)
        self.assertEqual(validate(data)["rows"][0]["topic"], self.topic)

    def test_explicit_topic_creation_then_revalidation_reuses_record(self):
        data = self.data([values(topic="Literature"), values(question_number="2", topic="LITERATURE")])
        before = Topic.objects.count()
        self.assertGreater(validate(data)["error_count"], 0)
        self.assertEqual(Topic.objects.count(), before)
        topic = Topic.objects.create(subject=self.subject, name="Literature", slug="literature")
        self.assertEqual(validate(data)["error_count"], 0)
        batch = confirm_import(data, self.user)
        self.assertEqual(Topic.objects.count(), before + 1)
        self.assertEqual(set(Question.objects.values_list("topic_id", flat=True)), {topic.pk})
        self.assertEqual(confirm_import(data, self.user), batch)

    def test_missing_subject_or_invalid_alias_never_creates_topic(self):
        for changes in ({"subject": "Unknown", "topic": "Literature"}, {"subject": "", "topic": "Literature"}):
            data = self.data([values(**changes)])
            self.assertGreater(validate(data)["error_count"], 0)
        data = self.data([values(topic="Literature")])
        data["topic_map"] = {normalized("English / Literature"): 999999}
        self.assertGreater(validate(data)["error_count"], 0)
        self.assertFalse(Topic.objects.filter(name="Literature").exists())

    def test_new_topic_and_batch_rollback_with_failed_question_creation(self):
        data = self.data([values(topic="Literature")])
        with patch("imports.services.create_question", side_effect=ValidationError("failure")):
            with self.assertRaises(ValidationError):
                confirm_import(data, self.user)
        self.assertFalse(Topic.objects.filter(name="Literature").exists())
        self.assertFalse(ImportBatch.objects.exists())

    def test_topic_creation_requires_permission(self):
        data = self.data([values(topic="Literature")])
        with patch("django.contrib.auth.models.PermissionsMixin.has_perm", side_effect=lambda perm, obj=None: perm != "exams.add_topic"):
            with self.assertRaises(ValidationError):
                confirm_import(data, self.user)
        self.assertFalse(Topic.objects.filter(name="Literature").exists())
        self.assertFalse(ImportBatch.objects.exists())

    def test_unknown_names_are_invalid_and_existing_bengali_names_resolve(self):
        self.assertGreater(validate(self.data([values(topic="X" * 201)]))["error_count"], 0)
        topic = Topic.objects.create(subject=self.subject, name="\u09ac\u09be\u0982\u09b2\u09be", slug="bangla")
        data = self.data([values(topic=topic.name)])
        self.assertEqual(validate(data)["error_count"], 0)
        confirm_import(data, self.user)
        self.assertEqual(Question.objects.get().topic_id, topic.pk)

    def test_general_import_retains_explicit_mapping_rule(self):
        data = self.data([values(topic="Literature")])
        data["selection"] = {"import_type": "general", "exam_ids": [self.exam.pk]}
        self.assertGreater(validate(data)["error_count"], 0)

    def test_bilingual_pairing_preserves_existing_topic_identity(self):
        topic = Topic.objects.create(subject=self.subject, name="Literature", slug="literature")
        data = self.data([values(topic="Literature"), values(language="bn", topic="LITERATURE")])
        group = validate(data)["groups"][0]
        data["pairings"] = {"1(a)": group["signature"]}
        self.assertEqual(validate(data)["error_count"], 0)
        confirm_import(data, self.user)
        self.assertEqual(Question.objects.count(), 1)
        self.assertEqual(Question.objects.get().topic_id, topic.pk)
        self.assertEqual(Question.objects.get().current_revision.translations.count(), 2)

    def test_bilingual_rows_with_different_topics_cannot_be_paired(self):
        Topic.objects.create(subject=self.subject, name="Literature", slug="literature")
        Topic.objects.create(subject=self.subject, name="Poetry", slug="poetry")
        data = self.data([values(topic="Literature"), values(language="bn", topic="Poetry")])
        group = validate(data)["groups"][0]
        data["pairings"] = {"1(a)": group["signature"]}
        result = validate(data)
        self.assertGreater(result["error_count"], 0)
        self.assertTrue(any("Ambiguous translation match" in error for row in result["rows"] for error in row["errors"]))

    def test_ambiguous_prefix_never_creates_topic_on_confirmation(self):
        Topic.objects.create(subject=self.subject, name="Grammar advanced", slug="advanced")
        data = self.data([values(topic="Grammatical rules")])
        with self.assertRaises(ValidationError):
            confirm_import(data, self.user)
        self.assertFalse(Topic.objects.filter(name="Grammatical rules").exists())
        self.assertFalse(Question.objects.exists())

    def test_duplicate_exact_names_still_require_explicit_mapping(self):
        from exams.models import Module
        module = Module.objects.create(subject=self.subject, name="Another branch", slug="another-branch")
        Topic.objects.create(subject=self.subject, module=module, name="GRAMMAR", slug="grammar-duplicate")
        data = self.data([values(topic="grammar")])
        result = validate(data)
        self.assertGreater(result["error_count"], 0)
        self.assertTrue(any("ambiguous" in error for error in result["rows"][0]["errors"]))
