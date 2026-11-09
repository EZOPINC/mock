from unittest.mock import patch

from django.core.exceptions import ValidationError

from exams.models import Subject, Topic
from questions.models import Question
from .models import ImportBatch
from .services import confirm_import
from .tests import ImportFixture, values
from .validation import normalized, validate


class TopicResolutionTests(ImportFixture):
    def test_subject_and_exact_topic_ignore_case(self):
        for name in ("english", "ENGLISH", " English "):
            with self.subTest(name=name):
                result = validate(self.data([values(subject=name, topic="gRaMmAr")]))
                self.assertEqual(result["error_count"], 0)
                self.assertEqual(result["rows"][0]["subject"], self.subject)
                self.assertEqual(result["rows"][0]["topic"], self.topic)

    def test_unique_prefix_within_subject_and_exact_match_priority(self):
        other = Subject.objects.create(name="Other", code="OTHER", slug="other")
        Topic.objects.create(subject=other, name="Grammar elsewhere", slug="grammar")
        data = self.data([values(topic="GRAMmatical rules")])
        result = validate(data)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["rows"][0]["topic"], self.topic)
        self.assertTrue(any("four characters" in warning for warning in result["rows"][0]["warnings"]))
        Topic.objects.create(subject=self.subject, name="Grammar advanced", slug="advanced")
        result = validate(self.data([values(topic="grammar")]))
        self.assertEqual(result["rows"][0]["topic"], self.topic)

    def test_ambiguous_prefix_proposes_exact_new_topic_or_accepts_manual_mapping(self):
        Topic.objects.create(subject=self.subject, name="Grammar advanced", slug="advanced")
        data = self.data([values(topic="Grammatical rules")])
        result = validate(data)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["rows"][0]["topic"].name, "Grammatical rules")
        self.assertIsNone(result["rows"][0]["topic"].pk)
        self.assertFalse(Topic.objects.filter(name="Grammatical rules").exists())
        data["topic_map"] = {normalized("English / Grammatical rules"): self.topic.pk}
        self.assertEqual(validate(data)["error_count"], 0)
        self.assertEqual(validate(data)["rows"][0]["topic"], self.topic)

    def test_preview_does_not_write_confirmation_reuses_new_topic(self):
        data = self.data([values(topic="Literature"), values(question_number="2", topic="LITERATURE")])
        before = Topic.objects.count()
        result = validate(data)
        self.assertEqual(result["error_count"], 0)
        self.assertIsNone(result["rows"][0]["topic"].pk)
        self.assertEqual(Topic.objects.count(), before)
        batch = confirm_import(data, self.user)
        questions = Question.objects.all()
        self.assertEqual(Topic.objects.count(), before + 1)
        self.assertEqual(questions.values("topic_id").distinct().count(), 1)
        self.assertEqual(questions.first().topic.subject_id, self.subject.pk)
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
            with self.assertRaisesMessage(ValidationError, "Add topic permission"):
                confirm_import(data, self.user)
        self.assertFalse(Topic.objects.filter(name="Literature").exists())
        self.assertFalse(ImportBatch.objects.exists())

    def test_long_names_are_invalid_and_bengali_names_get_valid_slug(self):
        self.assertGreater(validate(self.data([values(topic="X" * 201)]))["error_count"], 0)
        data = self.data([values(topic="\u09ac\u09be\u0982\u09b2\u09be")])
        self.assertEqual(validate(data)["error_count"], 0)
        confirm_import(data, self.user)
        Topic.objects.get(name="\u09ac\u09be\u0982\u09b2\u09be").full_clean()

    def test_general_import_retains_explicit_mapping_rule(self):
        data = self.data([values(topic="Literature")])
        data["selection"] = {"import_type": "general", "exam_ids": [self.exam.pk]}
        self.assertGreater(validate(data)["error_count"], 0)

    def test_bilingual_pairing_preserves_proposed_topic_identity(self):
        data = self.data([values(topic="Literature"), values(language="bn", topic="LITERATURE")])
        group = validate(data)["groups"][0]
        data["pairings"] = {"1(a)": group["signature"]}
        self.assertEqual(validate(data)["error_count"], 0)
        confirm_import(data, self.user)
        self.assertEqual(Question.objects.count(), 1)
        self.assertEqual(Topic.objects.filter(name="Literature").count(), 1)
        self.assertEqual(Question.objects.get().current_revision.translations.count(), 2)

    def test_bilingual_rows_with_different_new_topics_cannot_be_paired(self):
        data = self.data([values(topic="Literature"), values(language="bn", topic="Poetry")])
        group = validate(data)["groups"][0]
        data["pairings"] = {"1(a)": group["signature"]}
        result = validate(data)
        self.assertGreater(result["error_count"], 0)
        self.assertTrue(any("Ambiguous translation match" in error for row in result["rows"] for error in row["errors"]))

    def test_ambiguous_prefix_creates_exact_topic_on_confirmation(self):
        Topic.objects.create(subject=self.subject, name="Grammar advanced", slug="advanced")
        data = self.data([values(topic="Grammatical rules")])
        confirm_import(data, self.user)
        question = Question.objects.get()
        self.assertEqual(question.topic.name, "Grammatical rules")
        self.assertEqual(question.topic.subject_id, self.subject.pk)

    def test_duplicate_exact_names_still_require_explicit_mapping(self):
        Topic.objects.create(subject=self.subject, name="GRAMMAR", slug="grammar-duplicate")
        data = self.data([values(topic="grammar")])
        result = validate(data)
        self.assertGreater(result["error_count"], 0)
        self.assertTrue(any("ambiguous" in error for error in result["rows"][0]["errors"]))
