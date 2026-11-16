from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.db import connection, IntegrityError, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from .models import Subject, Part, Module, Submodule, Chapter, Topic


class ModulePartReassignmentTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(code='G', name='Geography', slug='geography')
        self.part = Part.objects.create(subject=self.subject, code='INDIA', name='India', slug='india')
        self.module = Module.objects.create(part=self.part, code='WB-M', name='West Bengal', slug='west-bengal')
        self.submodule = Submodule.objects.create(module=self.module, code='WB-S', name='Sub', slug='sub')
        self.chapter = Chapter.objects.create(submodule=self.submodule, code='WB-C', name='Chapter', slug='chapter')
        self.topic = Topic.objects.create(subject=self.subject, chapter=self.chapter, code='WB-T', name='Topic', slug='topic')

    def run_move(self, *args):
        output = StringIO()
        call_command('reassign_module_part', '--subject', 'G', '--module', 'WB-M', '--from-part', 'INDIA',
                     '--to-part', 'WB', *args, stdout=output)
        return output.getvalue()

    def test_preview_then_apply_keeps_descendant_ids_and_ordinary_guard(self):
        create = ('--create-part', '--part-name', 'West Bengal', '--part-order', '2')
        with CaptureQueriesContext(connection) as queries:
            self.assertIn('PREVIEW', self.run_move(*create))
        self.assertFalse(any(q['sql'].lstrip().split()[0].upper() in {'INSERT', 'UPDATE', 'DELETE'} for q in queries))
        self.assertFalse(Part.objects.filter(code='WB').exists())
        before = (self.module.pk, self.submodule.pk, self.chapter.pk, self.topic.pk)
        self.run_move(*create, '--apply')
        self.module.refresh_from_db()
        self.assertEqual(self.module.part.code, 'WB')
        self.assertEqual(self.module.part.display_order, 2)
        self.assertEqual(before, (self.module.pk, self.submodule.pk, self.chapter.pk, self.topic.pk))
        self.assertEqual(self.topic.chapter.submodule.module_id, self.module.pk)
        self.assertIn('Unchanged', self.run_move('--apply'))
        with self.assertRaises(ValidationError):
            self.module.part = self.part
            self.module.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Module.objects.filter(pk=self.module.pk).update(part=self.part)

    def test_cross_subject_and_source_mismatch_blocked(self):
        other = Subject.objects.create(code='O', name='Other', slug='other')
        Part.objects.create(subject=other, code='WB', name='Foreign', slug='foreign')
        with self.assertRaisesMessage(CommandError, 'another Subject'):
            self.run_move('--apply')
        self.assertEqual(Module.objects.get(pk=self.module.pk).part_id, self.part.pk)

    def test_late_failure_rolls_back_created_part(self):
        with patch.object(Module, 'save', side_effect=ValidationError('Late failure')):
            with self.assertRaisesMessage(CommandError, 'Late failure'):
                self.run_move('--create-part', '--part-name', 'West Bengal', '--apply')
        self.assertFalse(Part.objects.filter(code='WB').exists())
        self.assertEqual(Module.objects.get(pk=self.module.pk).part_id, self.part.pk)

    def test_authorization_is_exact_and_does_not_allow_cross_subject(self):
        other = Subject.objects.create(code='O', name='Other', slug='other')
        foreign = Part.objects.create(subject=other, code='FOREIGN', name='Foreign', slug='foreign')
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('exams.module_part_reassignment', %s, true)",
                               [f'{self.module.pk}:{self.part.pk}:{foreign.pk}'])
            Module.objects.filter(pk=self.module.pk).update(part=foreign)

    def test_destination_requires_explicit_creation(self):
        with self.assertRaisesMessage(CommandError, '--create-part'):
            self.run_move('--apply')

    def test_unexpected_source_and_other_module_not_authorized(self):
        target = Part.objects.create(subject=self.subject, code='WB', name='West Bengal', slug='west-bengal')
        wrong_source = Part.objects.create(subject=self.subject, code='WRONG', name='Wrong', slug='wrong')
        with self.assertRaisesMessage(CommandError, 'no longer belongs'):
            self.run_move('--from-part', wrong_source.code, '--apply')
        other = Module.objects.create(part=self.part, code='OTHER-M', name='Other module', slug='other-module')
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('exams.module_part_reassignment', %s, true)",
                               [f'{self.module.pk}:{self.part.pk}:{target.pk}'])
            Module.objects.filter(pk=other.pk).update(part=target)
