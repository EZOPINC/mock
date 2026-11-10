from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Chapter, Module, Part, Subject, Topic


class FlexibleTaxonomyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.subject = Subject.objects.create(name="History", code="HISTORY", slug="history")
        cls.other = Subject.objects.create(name="Geography", code="GEO", slug="geo")
        cls.part = Part.objects.create(subject=cls.subject, name="India", slug="india")
        cls.module = Module.objects.create(part=cls.part, name="Ancient", slug="ancient")
        cls.chapter = Chapter.objects.create(module=cls.module, name="Stone age", slug="stone-age")

    def test_all_permitted_parent_paths(self):
        root_module = Module.objects.create(subject=self.subject, name="Root module", slug="root-module")
        chapters = [self.chapter]
        for index, parent in enumerate(({"part": self.part}, {"subject": self.subject}, {"module": root_module})):
            chapter = Chapter.objects.create(name=f"Chapter {index}", slug=f"chapter-{index}", **parent)
            self.assertEqual(chapter.subject_id, self.subject.pk)
            chapters.append(chapter)
        for index, parent in enumerate([{"subject": self.subject}, {"subject": self.subject, "part": self.part},
                                       {"module": self.module}, {"module": root_module}] + [{"chapter": item} for item in chapters]):
            topic = Topic(name=f"Topic {index}", slug=f"topic-{index}", **parent)
            topic.full_clean()
            topic.save()
            self.assertEqual(topic.subject_id, self.subject.pk)
            self.assertTrue(topic.code.startswith("TOPIC-"))
            self.assertIn(topic.name, str(topic))

    def test_multiple_parents_rejected_by_model_and_database(self):
        for obj in (Chapter(subject=self.subject, part=self.part, module=self.module, name="Invalid", slug="invalid"),
                    Topic(subject=self.subject, chapter=self.chapter, module=self.module, name="Invalid", slug="invalid"),
                    Topic(subject=self.subject, chapter=self.chapter, part=self.part, name="Invalid", slug="invalid"),
                    Topic(subject=self.subject, module=self.module, part=self.part, name="Invalid", slug="invalid")):
            with self.subTest(model=type(obj).__name__):
                with self.assertRaises(ValidationError):
                    obj.full_clean()
                with self.assertRaises(IntegrityError), transaction.atomic():
                    type(obj).objects.bulk_create([obj])

    def test_subject_is_required_without_deeper_parent(self):
        for model in (Module, Chapter, Topic):
            with self.subTest(model=model.__name__):
                with self.assertRaises(ValidationError):
                    model(name="Missing", slug="missing").save()
                with self.assertRaises(IntegrityError), transaction.atomic():
                    model.objects.bulk_create([model(name="Missing", slug="missing")])

    def test_cross_subject_ancestry_rejected_for_every_parent_type(self):
        cases = [(Module, {"part": self.part}), (Chapter, {"module": self.module}),
                 (Chapter, {"part": self.part}), (Topic, {"chapter": self.chapter}),
                 (Topic, {"module": self.module}), (Topic, {"part": self.part})]
        for model, parent in cases:
            obj = model(subject=self.other, name="Invalid", slug="invalid", **parent)
            with self.subTest(model=model.__name__, parent=parent):
                with self.assertRaises(ValidationError):
                    obj.full_clean()
                with self.assertRaises(IntegrityError), transaction.atomic():
                    model.objects.bulk_create([obj])

    def test_codes_unique_case_insensitively_and_stable_after_renaming(self):
        for model, values in ((Subject, {}), (Part, {"subject": self.subject}),
                              (Module, {"subject": self.subject}), (Chapter, {"subject": self.subject}),
                              (Topic, {"subject": self.subject})):
            obj = model.objects.create(name="First", slug="first", code="STABLE", **values)
            with self.subTest(model=model.__name__):
                for code in ("STABLE", "stable", " stable ", ""):
                    with self.assertRaises(IntegrityError), transaction.atomic():
                        model.objects.bulk_create([model(name="Second", slug="second", code=code, **values)])
                obj.name = "Renamed"
                obj.save()
                self.assertEqual(obj.code, "STABLE")
                if model != Subject:
                    with self.assertRaises(IntegrityError), transaction.atomic():
                        model.objects.filter(pk=obj.pk).update(code="CHANGED")

    def test_scoped_names_and_slugs_at_all_flexible_levels(self):
        cases = [(Module, {"subject": self.subject}), (Chapter, {"subject": self.subject}),
                 (Chapter, {"subject": self.subject, "part": self.part}),
                 (Topic, {"subject": self.subject}), (Topic, {"subject": self.subject, "part": self.part}),
                 (Topic, {"subject": self.subject, "module": self.module})]
        for model, parent in cases:
            with self.subTest(model=model.__name__, parent=parent):
                obj = model.objects.create(name="Scoped", slug="scoped", **parent)
                for name, slug in ((" SCOPED ", "different"), ("Different", "scoped")):
                    with self.assertRaises(IntegrityError), transaction.atomic():
                        model.objects.bulk_create([model(name=name, slug=slug, **parent)])
                obj.delete()
        # Same topic name/slug is valid under different immediate parents.
        Topic.objects.create(subject=self.subject, name="Shared", slug="shared")
        Topic.objects.create(subject=self.subject, chapter=self.chapter, name="Shared", slug="shared")
