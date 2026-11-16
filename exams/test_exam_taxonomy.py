import json
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from .models import ExamAuthority, Exam, ExamStage
from .exam_taxonomy import export_catalogue


class ExamTaxonomyTests(TestCase):
    def setUp(self):
        self.data = {'schema_version': 1, 'kind': 'exam_taxonomy', 'authorities': [
            {'code': 'A', 'name': 'Authority', 'slug': 'authority', 'is_active': False, 'exams': [
                {'code': 'E', 'name': 'Exam', 'slug': 'exam', 'is_active': False,
                 'stages': [{'code': 'PRE', 'name': 'Preliminary', 'display_order': 3}]}]},
            {'code': 'B', 'name': 'Other', 'slug': 'other', 'exams': [
                {'code': 'E', 'name': 'Other exam', 'slug': 'exam',
                 'stages': [{'code': 'PRE', 'name': 'First', 'display_order': 1}]}]}]}

    def run_import(self, *args, data=None):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'catalogue.json'
            path.write_text(json.dumps(self.data if data is None else data), encoding='utf-8')
            output = StringIO()
            call_command('import_exam_taxonomy', str(path), *args, stdout=output)
            return output.getvalue()

    def test_dry_run_zero_writes_then_repeat_preserves_ids(self):
        with CaptureQueriesContext(connection) as queries:
            self.assertIn('authorities: create=2', self.run_import('--dry-run'))
        self.assertFalse(any(query['sql'].lstrip().split()[0].upper() in {'INSERT', 'UPDATE', 'DELETE'} for query in queries))
        self.assertFalse(ExamAuthority.objects.exists())
        self.run_import()
        identities = list(ExamStage.objects.order_by('pk').values_list('pk', 'exam_id', 'exam__authority_id'))
        self.assertIn('stages: create=0, update=0, unchanged=2', self.run_import())
        self.assertEqual(identities, list(ExamStage.objects.order_by('pk').values_list('pk', 'exam_id', 'exam__authority_id')))
        self.assertFalse(ExamAuthority.objects.get(code='A').is_active)
        self.assertFalse(Exam.objects.get(authority__code='A', code='E').is_active)

    def test_export_restore_and_file_overwrite_guard(self):
        self.run_import()
        data = export_catalogue()
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'backup.json'
            call_command('export_exam_taxonomy', str(path), stdout=StringIO())
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), data)
            with self.assertRaises(CommandError):
                call_command('export_exam_taxonomy', str(path), stdout=StringIO())
            ExamStage.objects.all().delete()
            Exam.objects.all().delete()
            ExamAuthority.objects.all().delete()
            call_command('import_exam_taxonomy', str(path), stdout=StringIO())
            self.assertEqual(export_catalogue(), data)

    def test_renames_preserve_ids_and_omitted_records(self):
        self.run_import()
        exam = Exam.objects.get(authority__code='A', code='E')
        stage = exam.stages.get(code='PRE')
        self.data['authorities'] = self.data['authorities'][:1]
        self.data['authorities'][0]['exams'][0]['name'] = 'Renamed'
        self.data['authorities'][0]['exams'][0]['stages'][0]['name'] = 'Renamed stage'
        self.run_import()
        exam.refresh_from_db()
        self.assertEqual(exam.name, 'Renamed')
        self.assertEqual(exam.stages.get(code='PRE').pk, stage.pk)
        self.assertTrue(ExamAuthority.objects.filter(code='B').exists())

    def test_invalid_duplicate_and_slug_collision_fail_before_writes(self):
        invalid = []
        duplicate = deepcopy(self.data)
        duplicate['authorities'].append(deepcopy(duplicate['authorities'][0]))
        invalid.append(duplicate)
        duplicate = deepcopy(self.data)
        duplicate['authorities'][0]['exams'].append(deepcopy(duplicate['authorities'][0]['exams'][0]))
        invalid.append(duplicate)
        duplicate = deepcopy(self.data)
        duplicate['authorities'][0]['exams'][0]['stages'].append({'code': 'PRE', 'name': 'Duplicate'})
        invalid.append(duplicate)
        for field, value in [('slug', 'invalid slug'), ('is_active', 'false'), ('name', '')]:
            bad = deepcopy(self.data)
            bad['authorities'][1][field] = value
            invalid.append(bad)
        bad = deepcopy(self.data)
        bad['authorities'][1]['slug'] = 'authority'
        invalid.append(bad)
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(CommandError):
                self.run_import(data=data)
            self.assertFalse(ExamAuthority.objects.exists())

    def test_late_failure_rolls_back_entire_import(self):
        from django.core.exceptions import ValidationError
        with patch.object(ExamStage, 'save', side_effect=ValidationError('Late failure')):
            with self.assertRaisesMessage(CommandError, 'Late failure'):
                self.run_import()
        self.assertFalse(ExamAuthority.objects.exists())
        self.assertFalse(Exam.objects.exists())
