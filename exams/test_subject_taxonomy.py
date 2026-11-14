import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from .models import Subject, Module, Chapter, Topic


class SubjectTaxonomyTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(code="HI", name="History", slug="history")
        self.legacy = Topic.objects.create(subject=self.subject, name="Legacy", slug="legacy")
        self.data = {"version": 1, "subject": {"code": "HI"}, "scope": "Ancient India",
                     "chapters": [{"code": "C", "title": "Stone Age", "sort_order": 1}],
                     "topics": [{"code": "T", "chapter_code": "C", "title": "Sources", "notes": "Notes"}]}

    def run_import(self, *args):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "taxonomy.json"
            path.write_text(json.dumps(self.data), encoding="utf-8")
            output = StringIO()
            call_command("import_subject_taxonomy", str(path), *args, stdout=output)
            return output.getvalue()

    def test_dry_run_repeat_rename_and_preserve_legacy(self):
        self.assertIn("create=1", self.run_import("--dry-run"))
        self.assertFalse(Chapter.objects.exists())
        self.assertEqual(Topic.objects.count(), 1)
        self.run_import()
        topic = Topic.objects.get(code="T")
        self.assertIsNone(topic.chapter.module_id)
        self.assertEqual(topic.notes, "Notes")
        self.assertIn("topics: create=0, update=0, unchanged=1", self.run_import())
        self.data["topics"][0]["title"] = "New display name"
        self.assertIn("update=1", self.run_import("--dry-run"))
        self.run_import()
        self.assertEqual(Topic.objects.get(code="T").pk, topic.pk)
        self.legacy.refresh_from_db()
        self.assertIsNone(self.legacy.chapter_id)

    def test_modules_and_explicit_subject_creation(self):
        self.data["subject"] = {"code": "NEW", "name": "New subject"}
        self.data["modules"] = [{"code": "M", "name": "Module"}]
        self.data["chapters"][0]["module_code"] = "M"
        with self.assertRaisesMessage(CommandError, "Unknown subject"):
            self.run_import()
        self.run_import("--create-subjects", "--dry-run")
        self.assertFalse(Subject.objects.filter(code="NEW").exists())
        self.run_import("--create-subjects")
        self.assertEqual(Topic.objects.get(code="T").chapter.module.code, "M")

    def test_missing_duplicate_cross_subject_and_reparent_rejected(self):
        self.data["topics"][0]["chapter_code"] = "missing"
        with self.assertRaisesMessage(CommandError, "Missing chapter"):
            self.run_import()
        self.assertFalse(Chapter.objects.exists())
        self.data["topics"][0]["chapter_code"] = "C"
        self.data["chapters"].append(dict(self.data["chapters"][0]))
        with self.assertRaisesMessage(CommandError, "Duplicate"):
            self.run_import("--dry-run")
        self.data["chapters"].pop()
        other = Subject.objects.create(code="OTHER", name="Other", slug="other")
        Module.objects.create(subject=other, code="FOREIGN", name="Foreign", slug="foreign")
        self.data["chapters"][0]["module_code"] = "FOREIGN"
        with self.assertRaisesMessage(CommandError, "Cross-subject"):
            self.run_import()
        self.data["chapters"][0].pop("module_code")
        self.run_import()
        self.data["chapters"].append({"code": "C2", "name": "Other chapter"})
        self.data["topics"][0]["chapter_code"] = "C2"
        with self.assertRaisesMessage(CommandError, "reparenting"):
            self.run_import()
        self.assertFalse(Chapter.objects.filter(code="C2").exists())

    def test_atomic_rollback_after_write_failure(self):
        from unittest.mock import patch
        with patch.object(Topic, "save", side_effect=ValueError("failure")):
            with self.assertRaisesMessage(CommandError, "failure"):
                self.run_import()
        self.assertFalse(Chapter.objects.exists())

    def test_omitted_existing_name_collision_rejected_in_dry_run(self):
        Chapter.objects.create(subject=self.subject, code="EXISTING", name="Stone Age", slug="stone")
        with self.assertRaisesMessage(CommandError, "Duplicate name"):
            self.run_import("--dry-run")
        self.assertFalse(Chapter.objects.filter(code="C").exists())
