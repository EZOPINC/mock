from unittest.mock import patch

from django.core.exceptions import ValidationError

from exams.models import Subject
from questions.models import Question
from .services import confirm_import
from .tests import ImportFixture, values
from .validation import validate


class SubjectFallbackTests(ImportFixture):
    def test_preview_does_not_create_fallback_and_confirmation_creates_once(self):
        data = self.data([values(subject=""), values(subject="  ", question_number="2")])
        result = validate(data)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["rows"][0]["subject"].name, "UnIdentified")
        self.assertFalse(Subject.objects.filter(code="UNIDENTIFIED").exists())
        batch = confirm_import(data, self.user)
        fallback = Subject.objects.get(code="UNIDENTIFIED")
        self.assertEqual(fallback.name, "UnIdentified")
        self.assertEqual(Question.objects.filter(subject=fallback).count(), 2)
        for record in batch.imported_questions.all():
            self.assertEqual(record.source_metadata["resolved"]["subject_id"], fallback.pk)

    def test_existing_fallback_reused_and_explicit_default_wins(self):
        fallback = Subject.objects.create(name="UnIdentified", code="LEGACY", slug="legacy-unidentified")
        data = self.data([values(subject="")])
        self.assertEqual(validate(data)["rows"][0]["subject"], fallback)
        data["selection"]["subject_id"] = self.subject.pk
        self.assertEqual(validate(data)["rows"][0]["subject"], self.subject)
        data["rows"][0]["values"]["subject"] = "English"
        data["selection"]["subject_id"] = fallback.pk
        self.assertEqual(validate(data)["rows"][0]["subject"], self.subject)

    def test_nonblank_unknown_subject_still_requires_mapping(self):
        result = validate(self.data([values(subject="Unknown subject spelling")]))
        self.assertGreater(result["error_count"], 0)
        self.assertIsNone(result["rows"][0]["subject"])

    def test_new_fallback_rolls_back_if_import_fails(self):
        data = self.data([values(subject="")])
        with patch("imports.services.create_question", side_effect=ValidationError("Failure")), self.assertRaises(ValidationError):
            confirm_import(data, self.user)
        self.assertFalse(Subject.objects.filter(code="UNIDENTIFIED").exists())

    def test_reserved_code_collision_requires_resolution(self):
        Subject.objects.create(name="Different subject", code="UNIDENTIFIED", slug="other")
        self.assertGreater(validate(self.data([values(subject="")]))["error_count"], 0)

    def test_fallback_creation_checks_subject_add_permission(self):
        data = self.data([values(subject="")])
        original = type(self.user).has_perm
        def permissions(user, permission, obj=None):
            return False if permission == "exams.add_subject" else original(user, permission, obj)
        with patch.object(type(self.user), "has_perm", permissions), self.assertRaises(ValidationError):
            confirm_import(data, self.user)
        self.assertFalse(Subject.objects.filter(code="UNIDENTIFIED").exists())
