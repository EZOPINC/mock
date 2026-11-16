import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from .models import Subject, Module, Chapter, Topic


class BulkSubjectTaxonomyTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'subjects'
        self.directory.mkdir()
        self.log = Path(self.temp.name) / 'result.jsonl'

    def put(self, name, data):
        (self.directory / name).write_text(json.dumps(data), encoding='utf-8')

    def data(self, code):
        return {'subject': {'code': code, 'name': code},
                'modules': [{'code': code + '-M', 'name': 'Module'}],
                'chapters': [{'code': code + '-C', 'module_code': code + '-M', 'name': 'Chapter'}],
                'topics': [{'code': code + '-T', 'chapter_code': code + '-C', 'name': 'Topic'}]}

    def run_bulk(self, *args):
        return call_command('import_subject_taxonomies', str(self.directory), '--log-file', str(self.log), *args, stdout=StringIO())

    def records(self):
        return [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines()]

    def test_multiple_subjects_deterministic_order_and_repeat(self):
        self.put('b.json', self.data('B'))
        self.put('a.json', self.data('A'))
        self.run_bulk('--create-subjects')
        self.assertEqual(Topic.objects.count(), 2)
        self.assertEqual([row['file'] for row in self.records() if row['event'] == 'file'], ['a.json', 'b.json'])
        self.assertEqual(self.records()[-1]['totals']['topics']['create'], 2)
        ids = list(Topic.objects.order_by('code').values_list('pk', flat=True))
        self.log = self.log.with_name('repeat.jsonl')
        self.run_bulk()
        self.assertEqual(self.records()[-1]['totals']['topics']['unchanged'], 2)
        self.assertEqual(ids, list(Topic.objects.order_by('code').values_list('pk', flat=True)))

    def test_dry_run_zero_database_writes_but_creates_log(self):
        self.put('a.json', self.data('A'))
        with CaptureQueriesContext(connection) as queries:
            self.run_bulk('--dry-run', '--create-subjects')
        self.assertFalse(any(query['sql'].lstrip().split()[0].upper() in {'INSERT', 'UPDATE', 'DELETE'} for query in queries))
        self.assertFalse(Subject.objects.exists())
        self.assertEqual(self.records()[1]['status'], 'validated')
        self.assertTrue(self.records()[-1]['dry_run'])

    def test_missing_parent_and_bad_json_logged_then_continue(self):
        bad = self.data('BAD')
        bad['topics'][0]['chapter_code'] = 'missing-chapter'
        self.put('a-bad.json', bad)
        (self.directory / 'b-malformed.json').write_text('{broken', encoding='utf-8')
        self.put('c-good.json', self.data('GOOD'))
        with self.assertRaisesMessage(CommandError, '2 file(s) failed'):
            self.run_bulk('--create-subjects')
        results = self.records()
        self.assertIn('Missing chapter parent', results[1]['error'])
        self.assertEqual(results[2]['error_type'], 'JSONDecodeError')
        self.assertEqual(results[3]['status'], 'imported')
        self.assertFalse(Subject.objects.filter(code='BAD').exists())
        self.assertTrue(Topic.objects.filter(code='GOOD-T').exists())

    def test_failed_persistence_rolls_back_only_that_file(self):
        self.put('a.json', self.data('A'))
        self.put('b.json', self.data('B'))
        save = Topic.save
        def failing_save(topic, *args, **kwargs):
            if topic.code == 'A-T':
                raise ValidationError('Late row failure')
            return save(topic, *args, **kwargs)
        with patch.object(Topic, 'save', failing_save), self.assertRaises(CommandError):
            self.run_bulk('--create-subjects')
        self.assertFalse(Subject.objects.filter(code='A').exists())
        self.assertFalse(Module.objects.filter(code='A-M').exists())
        self.assertTrue(Subject.objects.filter(code='B').exists())

    def test_backup_skipped_by_default_and_can_be_included(self):
        backup = {'schema_version': 1, 'kind': 'subject_taxonomy_backup',
                  'subjects': [{'code': 'BACKUP', 'name': 'Backup'}]}
        self.put('backup.json', backup)
        self.put('a.json', self.data('A'))
        self.run_bulk('--create-subjects')
        self.assertFalse(Subject.objects.filter(code='BACKUP').exists())
        self.assertEqual(self.records()[-1]['skipped'], 1)
        self.log = self.log.with_name('included.jsonl')
        self.run_bulk('--include-backups', '--create-subjects')
        self.assertTrue(Subject.objects.filter(code='BACKUP').exists())

    def test_valid_direct_subject_chapter_and_unattached_module_warn(self):
        data = self.data('A')
        del data['chapters'][0]['module_code']
        self.put('a.json', data)
        self.run_bulk('--create-subjects')
        warnings = self.records()[1]['warnings']
        self.assertTrue(any('no children reference' in warning for warning in warnings))
        self.assertTrue(any('valid skipped-level path' in warning for warning in warnings))
        self.assertIsNone(Chapter.objects.get(code='A-C').module_id)

    def test_existing_log_is_never_overwritten_or_database_modified(self):
        self.put('a.json', self.data('A'))
        self.log.write_text('keep', encoding='utf-8')
        with self.assertRaisesMessage(CommandError, 'Cannot create a new results log'):
            self.run_bulk('--create-subjects')
        self.assertEqual(self.log.read_text(encoding='utf-8'), 'keep')
        self.assertFalse(Subject.objects.exists())

    def test_empty_or_missing_directory_fails(self):
        with self.assertRaisesMessage(CommandError, 'No JSON files'):
            self.run_bulk()
        with self.assertRaisesMessage(CommandError, 'does not exist'):
            call_command('import_subject_taxonomies', str(self.directory / 'missing'))

    def test_sub_module_aliases_and_explicit_repair_are_logged(self):
        data = self.data('A')
        self.put('a.json', data)
        self.run_bulk('--create-subjects')
        chapter_id = Chapter.objects.get(code='A-C').pk
        data['sub_modules'] = [{'code': 'A-S', 'module_code': 'A-M', 'name': 'Sub'}]
        data['chapters'][0]['sub_module_code'] = 'A-S'
        self.put('a.json', data)
        self.log = self.log.with_name('repair.jsonl')
        self.run_bulk('--attach-submodules')
        result = self.records()[1]
        self.assertEqual(result['counts']['submodules']['create'], 1)
        self.assertEqual(result['warnings'], [])
        chapter = Chapter.objects.get(code='A-C')
        self.assertEqual(chapter.pk, chapter_id)
        self.assertEqual(chapter.submodule.code, 'A-S')
        self.assertIsNone(chapter.module_id)
