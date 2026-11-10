from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.core.management import call_command
from io import StringIO

from questions.models import QuestionExam
from questions.services import create_question
from .models import Chapter, Exam, ExamAuthority, Module, Part, Subject, Topic
from .selectors import subjects_for_exam


class HierarchyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.subject = Subject.objects.create(name="History", code="H", slug="history")
        cls.other = Subject.objects.create(name="Geography", code="G", slug="geography")
        cls.part = Part.objects.create(subject=cls.subject, name="India", slug="india")
        cls.module = Module.objects.create(part=cls.part, name="Ancient history", slug="ancient")
        cls.chapter = Chapter.objects.create(module=cls.module, name="Stone age", slug="stone-age")
        cls.topic = Topic.objects.create(subject=cls.subject, chapter=cls.chapter, name="Paleolithic", slug="paleolithic")

    def test_question_reuses_one_hierarchy_across_exams(self):
        question = create_question(subject=self.subject, topic=self.topic, revision={"language": "en",
            "question_text": "Question", "option_a": "A", "option_b": "B", "option_c": "C",
            "option_d": "D", "correct_answer": "A"})
        authority = ExamAuthority.objects.create(name="Authority", code="A", slug="authority")
        for code in ("WBCS", "Clerkship"):
            exam = Exam.objects.create(authority=authority, name=code, code=code, slug=code.lower())
            QuestionExam.objects.create(question=question, exam=exam)
            self.assertEqual(list(subjects_for_exam(exam.pk)), [self.subject])
        self.assertEqual(question.topic.chapter.module.part.subject_id, question.subject_id)
        self.assertEqual(Topic.objects.count(), 1)

    def test_existing_flat_topic_and_unicode_names_still_work(self):
        flat = Topic.objects.create(subject=self.subject, name="Legacy", slug="legacy")
        self.assertIsNone(flat.chapter_id)
        part = Part.objects.create(subject=self.subject, name="ভারত", slug="bharat")
        self.assertIn("ভারত", str(part))
        self.assertIn("Stone age", str(self.topic))

    def test_cross_subject_chapter_is_rejected_by_model_and_database(self):
        topic = Topic(subject=self.other, chapter=self.chapter, name="Invalid", slug="invalid")
        with self.assertRaises(ValidationError):
            topic.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Topic.objects.bulk_create([topic])

    def test_parent_changes_are_rejected_even_with_bulk_updates(self):
        other_part = Part.objects.create(subject=self.other, name="World", slug="world")
        other_module = Module.objects.create(part=other_part, name="Physical", slug="physical")
        for obj, field, value in ((self.part, "subject", self.other), (self.module, "part", other_part),
                                  (self.chapter, "module", other_module), (self.topic, "subject", self.other)):
            with self.subTest(model=type(obj).__name__):
                setattr(obj, field, value)
                with self.assertRaises(ValidationError):
                    obj.save()
                with self.assertRaises(IntegrityError), transaction.atomic():
                    type(obj).objects.filter(pk=obj.pk).update(**{field: value})
                obj.refresh_from_db()

    def test_scoped_slug_and_normalized_name_uniqueness_at_database_level(self):
        for model, fields in ((Part, {"subject": self.subject, "name": " india ", "slug": "different"}),
                              (Module, {"part": self.part, "name": "ANCIENT HISTORY", "slug": "different"}),
                              (Chapter, {"module": self.module, "name": "Stone age", "slug": "different"}),
                              (Topic, {"subject": self.subject, "chapter": self.chapter, "name": "PALEOLITHIC", "slug": "different"})):
            with self.subTest(model=model.__name__), self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.bulk_create([model(**fields)])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Part.objects.bulk_create([Part(subject=self.subject, name="Other", slug="india")])
        Part.objects.create(subject=self.other, name="India", slug="india")

    def test_attach_flat_topic_and_protect_ancestors(self):
        flat = Topic.objects.create(subject=self.subject, name="Neolithic", slug="neolithic")
        flat.chapter = self.chapter
        flat.save()
        flat.refresh_from_db()
        self.assertEqual(flat.chapter_id, self.chapter.pk)
        for obj in (self.subject, self.part, self.module, self.chapter):
            with self.subTest(model=type(obj).__name__), self.assertRaises(ProtectedError):
                obj.delete()

    def test_admin_registrations_and_inconsistent_topic_form(self):
        for model in (Part, Module, Chapter):
            self.assertIn(model, admin.site._registry)
        from django.forms import modelform_factory
        form = modelform_factory(Topic, fields=("name", "slug", "subject", "chapter"))(
            data={"name": "Invalid", "slug": "invalid", "subject": self.other.pk, "chapter": self.chapter.pk})
        self.assertFalse(form.is_valid())
        self.assertIn("chapter", form.errors)

    def test_read_only_integrity_audit(self):
        from .integrity import taxonomy_integrity_counts
        self.assertTrue(all(value == 0 for value in taxonomy_integrity_counts().values()))
        output = StringIO()
        call_command("audit_taxonomy", stdout=output)
        self.assertIn("Taxonomy integrity audit passed", output.getvalue())
