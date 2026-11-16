import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.test import TransactionTestCase, skipUnlessDBFeature

from mock_tests.test_attempts import AttemptFixture
from mock_tests.services import start_attempt
from previous_year.models import PreviousYearPaper
from questions.tagging import set_question_topics
from .models import Subject, Part, Module, Submodule, Chapter, Topic
from .taxonomy_purge import preservation_counts


class TaxonomyPurgeTests(AttemptFixture):
    def setUp(self):
        super().setUp()
        self.part = Part.objects.create(subject=self.subject, name='Old part', slug='old-part', code='OLD-P')
        self.module = Module.objects.create(part=self.part, name='Old module', slug='old-module', code='OLD-M')
        self.submodule = Submodule.objects.create(module=self.module, name='Old sub', slug='old-sub', code='OLD-S')
        self.chapter = Chapter.objects.create(submodule=self.submodule, name='Old chapter', slug='old-chapter', code='OLD-C')
        self.old_topic = Topic.objects.create(subject=self.subject, chapter=self.chapter, name='Old topic', slug='old-topic', code='OLD-T')
        self.codes = {'parts': ['OLD-P'], 'modules': ['OLD-M'], 'submodules': ['OLD-S'],
                      'chapters': ['OLD-C'], 'topics': ['OLD-T']}

    def run_purge(self, *args, subjects=None, codes=None):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'old-codes.json'
            path.write_text(json.dumps(self.codes if codes is None else codes), encoding='utf-8')
            out = StringIO()
            subject_args = [arg for code in (subjects or [self.subject.code]) for arg in ('--subject', code)]
            call_command('purge_subject_taxonomy', *subject_args, '--old-codes', str(path), *args, stdout=out)
            return out.getvalue()

    def test_preview_has_zero_writes_and_reports_internal_links(self):
        with CaptureQueriesContext(connection) as queries:
            output = self.run_purge()
        self.assertIn('PREVIEW (zero writes)', output)
        self.assertIn('exams.Topic.chapter: internal=1, external=0', output)
        self.assertIn('Cascade effects:', output)
        self.assertFalse(any(query['sql'].lstrip().split()[0].upper() in {'INSERT', 'UPDATE', 'DELETE'} for query in queries))
        self.assertTrue(Topic.objects.filter(pk=self.old_topic.pk).exists())


    def test_apply_preserves_nonempty_content_papers_patterns_and_attempts(self):
        self.ready()
        start_attempt(self.user, self.pattern)
        PreviousYearPaper.objects.create(exam=self.exam, subject=self.subject, year=2020, paper_name='Preserved paper')
        before = preservation_counts()
        self.assertGreater(before['questions.Question'], 0)
        self.assertGreater(before['mock_tests.MockAttempt'], 0)
        self.assertGreater(before['previous_year.PreviousYearPaper'], 0)
        self.assertIn('Applied successfully', self.run_purge('--apply'))
        self.assertEqual(before, preservation_counts())
        self.assertTrue(Subject.objects.filter(pk=self.subject.pk).exists())
        self.assertFalse(Part.objects.filter(pk=self.part.pk).exists())

    def test_child_omitted_from_explicit_set_blocks_parent(self):
        self.codes['topics'] = []
        with self.assertRaisesMessage(CommandError, 'referenced outside'):
            self.run_purge('--apply')
        self.assertTrue(Part.objects.filter(pk=self.part.pk).exists())

    def test_question_tag_many_to_many_blocks_without_detaching(self):
        question = self.question()
        set_question_topics(question, [self.topic.pk, self.old_topic.pk], primary_topic_id=self.topic.pk)
        before = preservation_counts()
        with self.assertRaisesMessage(CommandError, 'referenced outside'):
            self.run_purge('--apply')
        self.assertEqual(before, preservation_counts())
        self.assertTrue(question.topic_associations.filter(topic=self.old_topic).exists())

    def test_primary_topic_and_mock_section_references_block(self):
        self.section.topic = self.old_topic
        self.section.save()
        with self.assertRaisesMessage(CommandError, 'referenced outside'):
            self.run_purge()
        self.section.topic = None
        self.section.save()
        question = self.question()
        set_question_topics(question, [self.old_topic.pk], primary_topic_id=self.old_topic.pk)
        with self.assertRaisesMessage(CommandError, 'referenced outside'):
            self.run_purge('--apply')
        question.refresh_from_db()
        self.assertEqual(question.topic_id, self.old_topic.pk)

    def test_unknown_codes_subjects_and_out_of_scope_codes_abort(self):
        other = Subject.objects.create(code='OTHER', name='Foreign subject', slug='foreign-subject')
        Topic.objects.create(subject=other, code='FOREIGN', name='Foreign', slug='foreign')
        for subjects, codes, message in [([self.subject.code], {'topics': ['FOREIGN']}, 'outside'),
                                          (['UNKNOWN'], self.codes, 'Unknown subject'),
                                          ([self.subject.code], {'topics': ['missing']}, 'Unknown topics'),
                                          ([self.subject.code], {'topics': ['OLD-T', 'old-t']}, 'Duplicate'),
                                          ([self.subject.code], {}, 'at least one')]:
            with self.subTest(message=message), self.assertRaisesMessage(CommandError, message):
                self.run_purge('--apply', subjects=subjects, codes=codes)

    def test_provenance_not_guessed(self):
        with self.assertRaisesMessage(CommandError, 'origin is not recorded'):
            call_command('purge_subject_taxonomy', subject=[self.subject.code])

    def test_original_import_json_can_supply_explicit_codes(self):
        data = {'schema_version': 1, 'subject': {'code': self.subject.code, 'title': 'Subject'},
                'scope': 'Description only',
                **{kind: [{'code': code, 'subject_code': self.subject.code, 'title': 'Ignored label'}
                          for code in codes] for kind, codes in self.codes.items()}}
        self.assertIn('PREVIEW (zero writes)', self.run_purge(codes=data))
        self.assertTrue(Topic.objects.filter(pk=self.old_topic.pk).exists())
        self.assertIn('Applied successfully', self.run_purge('--apply', codes=data))
        self.assertFalse(Topic.objects.filter(pk=self.old_topic.pk).exists())

    def test_import_json_subject_mismatch_or_missing_code_fails(self):
        for data, message in [
            ({'subject': {'code': self.other_subject.code}, 'topics': ['OLD-T']}, 'outside'),
            ({'topics': [{'code': 'OLD-T', 'subject_code': self.other_subject.code}]}, 'outside'),
            ({'topics': [{'name': 'Old topic'}]}, 'explicit nonempty code'),
            ({'schema_version': 2, 'topics': ['OLD-T']}, 'version 1'),
        ]:
            with self.subTest(data=data), self.assertRaisesMessage(CommandError, message):
                self.run_purge('--apply', codes=data)
        self.assertTrue(Topic.objects.filter(pk=self.old_topic.pk).exists())

    def test_multiple_subjects_only_delete_explicit_codes(self):
        foreign = Topic.objects.create(subject=self.other_subject, code='OTHER-OLD', name='Old foreign', slug='old-foreign')
        untouched = Topic.objects.create(subject=self.other_subject, code='KEEP', name='Keep', slug='keep')
        self.codes['topics'].append('OTHER-OLD')
        self.run_purge('--apply', subjects=[self.subject.code, self.other_subject.code])
        self.assertFalse(Topic.objects.filter(pk=foreign.pk).exists())
        self.assertTrue(Topic.objects.filter(pk=untouched.pk).exists())
        self.assertTrue(Subject.objects.filter(pk=self.other_subject.pk).exists())

    def test_mock_rule_and_practice_session_are_external_blockers(self):
        from mock_tests.models import SectionSelectionRule
        from practice.services import start_session
        from uuid import uuid4

        rule = SectionSelectionRule.objects.create(section=self.section, module=self.module, question_count=1)
        with self.assertRaisesMessage(CommandError, 'referenced outside'):
            self.run_purge('--apply')
        rule.delete()
        question = self.question()
        set_question_topics(question, [self.old_topic.pk], primary_topic_id=self.old_topic.pk)
        session = start_session(self.user, exam=self.exam, subject=self.subject, topic=self.old_topic, count='available', token=uuid4())
        # Remove current classification through its workflow; historical session keeps its FK.
        set_question_topics(question, [self.topic.pk], primary_topic_id=self.topic.pk)
        with self.assertRaisesMessage(CommandError, 'referenced outside'):
            self.run_purge('--apply')
        session.refresh_from_db()
        self.assertEqual(session.topic_id, self.old_topic.pk)

    def test_late_failure_rolls_back_all_deletes(self):
        with patch('exams.taxonomy_purge.preservation_counts', return_value={'changed': 1}):
            # Patch only the apply-stage comparison, preserving the initial baseline.
            from exams.taxonomy_purge import apply_purge as apply
            def fail_comparison(selected, before):
                return apply(selected, {'unchanged': 1})
            with patch('exams.management.commands.purge_subject_taxonomy.apply_purge', side_effect=fail_comparison):
                with self.assertRaisesMessage(CommandError, 'counts changed'):
                    self.run_purge('--apply')
        self.assertTrue(Part.objects.filter(pk=self.part.pk).exists())
        self.assertTrue(Topic.objects.filter(pk=self.old_topic.pk).exists())

class TaxonomyPurgeLockTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update_nowait')
    def test_apply_locks_selected_rows_until_commit(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from django.db import DatabaseError, close_old_connections, transaction
        from .taxonomy_purge import apply_purge

        subject = Subject.objects.create(code='LOCK', name='Lock subject', slug='lock-subject')
        topic = Topic.objects.create(subject=subject, code='LOCK-T', name='Lock topic', slug='lock-topic')
        ready, proceed = Event(), Event()
        def paused_apply(selected, before):
            ready.set()
            if not proceed.wait(10):
                raise RuntimeError('Lock test timed out')
            return apply_purge(selected, before)
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'codes.json'
            path.write_text(json.dumps({'topics': ['LOCK-T']}), encoding='utf-8')
            def worker():
                close_old_connections()
                try:
                    call_command('purge_subject_taxonomy', '--subject', 'LOCK', '--old-codes', str(path), '--apply', stdout=StringIO())
                finally:
                    close_old_connections()
            with patch('exams.management.commands.purge_subject_taxonomy.apply_purge', side_effect=paused_apply), ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(worker)
                try:
                    self.assertTrue(ready.wait(10))
                    with self.assertRaises(DatabaseError), transaction.atomic():
                        Topic.objects.select_for_update(nowait=True).get(pk=topic.pk)
                finally:
                    proceed.set()
                future.result(timeout=10)
        self.assertFalse(Topic.objects.filter(pk=topic.pk).exists())


