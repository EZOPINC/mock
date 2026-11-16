import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from .models import Subject, Part, Module, Submodule, Chapter, Topic
from .subject_taxonomy import export_taxonomy


class SubjectTaxonomyExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.subject = Subject.objects.create(code='H', name='History', slug='custom-history', display_order=4)
        Subject.objects.create(code='E', name='English', slug='custom-english')
        part = Part.objects.create(subject=cls.subject, code='P', name='India', slug='custom-india')
        module = Module.objects.create(part=part, code='M', name='Ancient', slug='custom-ancient')
        root_module = Module.objects.create(subject=cls.subject, code='RM', name='Direct module', slug='direct-module')
        submodule = Submodule.objects.create(module=module, code='SM', name='Prehistory', slug='prehistory')
        chapters = []
        for index, parent in enumerate(({'submodule': submodule}, {'module': module}, {'part': part}, {})):
            chapters.append(Chapter.objects.create(subject=cls.subject, code=f'C{index}', name=f'Chapter {index}',
                                                   slug=f'custom-chapter-{index}', display_order=index, **parent))
        for index, parent in enumerate([{'chapter': chapter} for chapter in chapters] + [
                {}, {'module': module}, {'part': part}, {'module': root_module}]):
            Topic.objects.create(subject=cls.subject, code=f'T{index}', name=f'Topic {index}',
                                 slug=f'custom-topic-{index}', notes='Notes: \u09ac\u09be\u0982\u09b2\u09be', display_order=index, **parent)

    def test_all_subjects_and_paths_export_in_six_queries(self):
        with self.assertNumQueries(6):
            data = export_taxonomy()
        self.assertEqual(len(data['subjects']), 2)
        self.assertEqual(len(data['topics']), 8)
        self.assertEqual(data['chapters'][0]['submodule_code'], 'SM')
        self.assertNotIn('module_code', data['chapters'][0])
        self.assertNotIn('chapter_code', data['topics'][4])
        self.assertEqual(data['subjects'][1]['slug'], 'custom-history')

    def test_export_restore_empty_database_and_repeat(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'all.json'
            call_command('export_subject_taxonomy', str(path), stdout=StringIO())
            original = json.loads(path.read_text(encoding='utf-8'))
            for model in (Topic, Chapter, Submodule, Module, Part, Subject):
                model.objects.all().delete()
            with CaptureQueriesContext(connection) as queries:
                call_command('import_subject_taxonomy', str(path), '--create-subjects', '--dry-run', stdout=StringIO())
            self.assertFalse(any(query['sql'].lstrip().split()[0].upper() in {'INSERT', 'UPDATE', 'DELETE'} for query in queries))
            self.assertFalse(Subject.objects.exists())
            call_command('import_subject_taxonomy', str(path), '--create-subjects', stdout=StringIO())
            self.assertEqual(export_taxonomy(), original)
            identities = list(Topic.objects.order_by('code').values_list('pk', 'chapter_id', 'module_id', 'part_id'))
            output = StringIO()
            call_command('import_subject_taxonomy', str(path), stdout=output)
            self.assertIn('topics: create=0, update=0, unchanged=8', output.getvalue())
            self.assertEqual(identities, list(Topic.objects.order_by('code').values_list('pk', 'chapter_id', 'module_id', 'part_id')))

    def test_existing_backup_import_keeps_ids_and_requires_explicit_overwrite(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'all.json'
            call_command('export_subject_taxonomy', str(path), stdout=StringIO())
            with self.assertRaises(CommandError):
                call_command('export_subject_taxonomy', str(path), stdout=StringIO())
            call_command('export_subject_taxonomy', str(path), '--overwrite', stdout=StringIO())
            original = export_taxonomy()
            topic_ids = list(Topic.objects.order_by('code').values_list('pk', flat=True))
            call_command('import_subject_taxonomy', str(path), stdout=StringIO())
            self.assertEqual(export_taxonomy(), original)
            self.assertEqual(topic_ids, list(Topic.objects.order_by('code').values_list('pk', flat=True)))

    def test_empty_database_export_is_importable(self):
        for model in (Topic, Chapter, Submodule, Module, Part, Subject):
            model.objects.all().delete()
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'empty.json'
            call_command('export_subject_taxonomy', str(path), stdout=StringIO())
            call_command('import_subject_taxonomy', str(path), stdout=StringIO())
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), export_taxonomy())
