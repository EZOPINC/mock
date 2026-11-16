from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Subject, Part, Module, Submodule, Chapter, Topic
from .subject_taxonomy import plan_taxonomy, persist_taxonomy
from .selectors import topics_with_ancestry


class SubmoduleTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(code='H', name='History', slug='history')
        self.part = Part.objects.create(subject=self.subject, name='India', slug='india')
        self.module = Module.objects.create(part=self.part, code='M', name='Ancient', slug='ancient')
        self.submodule = Submodule.objects.create(module=self.module, code='SM', name='Prehistory', slug='prehistory')

    def test_optional_parent_labels_and_batched_choices(self):
        nested = Chapter.objects.create(submodule=self.submodule, code='C', name='Stone Age', slug='stone')
        direct = Chapter.objects.create(module=self.module, code='D', name='Direct', slug='direct')
        topic = Topic.objects.create(subject=self.subject, chapter=nested, code='T', name='Sources', slug='sources')
        self.assertEqual(nested.subject_id, self.subject.pk)
        self.assertIsNone(nested.module_id)
        self.assertEqual(direct.module_id, self.module.pk)
        with self.assertNumQueries(1):
            self.assertEqual(str(topics_with_ancestry().get(pk=topic.pk)),
                             'History: India: Ancient: Prehistory: Stone Age: Sources')
        from imports.forms import UploadForm
        from general_question.forms import GeneralQuestionFilters
        for form in (UploadForm(), GeneralQuestionFilters()):
            with self.assertNumQueries(1):
                self.assertIn('Prehistory', str([label for value, label in form.fields['topic'].choices]))

    def test_model_and_database_guards(self):
        other = Subject.objects.create(code='O', name='Other', slug='other')
        foreign = Module.objects.create(subject=other, name='Foreign', slug='foreign')
        with self.assertRaises(ValidationError):
            Submodule.objects.create(subject=other, module=self.module, name='Invalid', slug='invalid')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Submodule.objects.filter(pk=self.submodule.pk).update(module=foreign)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Submodule.objects.bulk_create([Submodule(subject=other, module=self.module, name='Invalid', slug='invalid')])
        chapter = Chapter.objects.create(submodule=self.submodule, name='Nested', slug='nested')
        with self.assertRaises(ValidationError):
            Chapter.objects.create(subject=self.subject, submodule=self.submodule, module=self.module, name='Two', slug='two')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Chapter.objects.filter(pk=chapter.pk).update(module=self.module)
        root = Chapter.objects.create(subject=other, name='Root', slug='root')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Chapter.objects.filter(pk=root.pk).update(submodule=self.submodule)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Chapter.objects.filter(pk=chapter.pk).update(submodule=None)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Submodule.objects.bulk_create([Submodule(subject=self.subject, module=self.module, code=' sm ', name='Duplicate', slug='duplicate')])

    def test_json_plan_dry_repeat_and_invalid_parents(self):
        data = {'version': 1, 'subject': {'code': 'H'},
                'submodules': [{'code': 'NEW', 'module_code': 'M', 'name': 'New'}],
                'chapters': [{'code': 'C', 'submodule_code': 'NEW', 'name': 'Nested'},
                             {'code': 'D', 'module_code': 'M', 'name': 'Direct'}],
                'topics': [{'code': 'T', 'chapter_code': 'C', 'name': 'Sources'}]}
        plan, counts = plan_taxonomy(data)
        self.assertEqual(counts['chapters']['create'], 2)
        self.assertFalse(Chapter.objects.exists())
        with transaction.atomic():
            persist_taxonomy(plan)
        chapter = Chapter.objects.get(code='C')
        self.assertEqual(chapter.submodule.code, 'NEW')
        self.assertIsNone(chapter.module_id)
        self.assertEqual(plan_taxonomy(data)[1]['chapters']['unchanged'], 2)
        data['chapters'][0]['submodule_code'] = 'missing'
        with self.assertRaisesMessage(ValidationError, 'Missing submodule'):
            plan_taxonomy(data)
        self.assertEqual(Chapter.objects.get(code='C').pk, chapter.pk)
        data['chapters'][0]['submodule_code'] = 'NEW'
        data['chapters'][0]['module_code'] = 'M'
        with self.assertRaisesMessage(ValidationError, 'one immediate parent'):
            plan_taxonomy(data)

    def test_admin_module_and_submodule_filters_include_descendants(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from .admin import ModulePathFilter, SubmodulePathFilter

        chapter = Chapter.objects.create(submodule=self.submodule, name='Nested', slug='nested')
        topic = Topic.objects.create(subject=self.subject, chapter=chapter, name='Leaf', slug='leaf')
        request = RequestFactory().get('/')
        for model, node in ((Chapter, chapter), (Topic, topic)):
            model_admin = admin.site._registry[model]
            module_filter = ModulePathFilter(request, {'module_path': [str(self.module.pk)]}, model, model_admin)
            self.assertIn(node, module_filter.queryset(request, model.objects.all()))
            submodule_filter = SubmodulePathFilter(request, {'submodule_path': [str(self.submodule.pk)]}, model, model_admin)
            self.assertIn(node, submodule_filter.queryset(request, model.objects.all()))

