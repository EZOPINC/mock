"""Import creation query budgets and rollback coverage on PostgreSQL."""
from collections import Counter
from contextlib import nullcontext
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from questions.creation import created_question, creation_batch
from questions.models import Question, QuestionRevision, QuestionTranslation
from .models import ImportBatch, ImportedQuestion
from .services import confirm_import
from .tests import ImportFixture, values


class ImportCreationTests(ImportFixture):
    def general_data(self, prefix, count=2):
        data = self.data([values(question_number=str(index + 1),
            question_text=f'{prefix} question {index}', topic='Grammar') for index in range(count)])
        data['selection'] = dict(import_type='general', exam_ids=[self.exam.pk], exam_mapping='selected')
        for index, row in enumerate(data['rows']):
            if index < count * 7 // 10:
                row['values'].update(question_text_bn=f'{prefix} Bengali edition {index}',
                    option_a_bn='A', option_b_bn='B', option_c_bn='C', option_d_bn='D')
            row['original_values'] = dict(row['values'])
        return data

    def test_100_question_query_budget_against_individual_creation(self):
        measurements = {}
        for optimized in (False, True):
            data = self.general_data(str(optimized), 100)
            operations = Counter()

            def count_queries(execute, sql, params, many, context):
                operations[sql.split()[0]] += 1
                return execute(sql, params, many, context)

            scope = nullcontext() if optimized else patch('imports.services.creation_batch',
                return_value=nullcontext(SimpleNamespace(remember_reference=lambda obj: None)))
            start = perf_counter()
            with scope, connection.execute_wrapper(count_queries):
                batch = confirm_import(data, self.user)
            measurements[optimized] = operations
            print('Import creation benchmark:', 'optimized' if optimized else 'baseline',
                round(perf_counter() - start, 3), 'seconds;', dict(operations))
            self.assertEqual(batch.imported_questions.count(), 100)
            self.assertEqual(QuestionTranslation.objects.filter(question__import_records__batch=batch).count(), 170)
        before, after = measurements[False], measurements[True]
        self.assertLess(after['SELECT'], before['SELECT'] * .85)
        self.assertLess(after['SAVEPOINT'], before['SAVEPOINT'])
        self.assertEqual(after['INSERT'], before['INSERT'])
        self.assertEqual(Question.objects.filter(review_status='pending_review', publication_status='draft').count(), 200)

    def test_late_translation_validation_failure_rolls_back_entire_import(self):
        data = self.general_data('invalid')
        original = QuestionTranslation.save
        calls = []

        def invalidate_second(translation, *args, **kwargs):
            calls.append(translation.question_id)
            if len(calls) == 2:
                translation.option_b = ''
            return original(translation, *args, **kwargs)

        with patch.object(QuestionTranslation, 'save', invalidate_second):
            with self.assertRaises(ValidationError):
                confirm_import(data, self.user)
        self.assertEqual(Question.objects.count(), 0)
        self.assertEqual(QuestionRevision.objects.count(), 0)
        self.assertEqual(QuestionTranslation.objects.count(), 0)
        self.assertEqual(ImportBatch.objects.count(), 0)
        self.assertIsNone(created_question(calls[0]))

    def test_late_database_failure_rolls_back_and_retry_works(self):
        data = self.general_data('retry')
        original = ImportedQuestion.save
        calls = []

        def fail_second(record, *args, **kwargs):
            calls.append(record.question_id)
            if len(calls) == 2:
                raise IntegrityError('Injected late database failure')
            return original(record, *args, **kwargs)

        with patch.object(ImportedQuestion, 'save', fail_second):
            with self.assertRaises(ValidationError):
                confirm_import(data, self.user)
        self.assertFalse(Question.objects.exists())
        self.assertFalse(ImportBatch.objects.exists())
        self.assertIsNone(created_question(calls[0]))
        batch = confirm_import(data, self.user)
        self.assertEqual(batch.imported_questions.count(), 2)

    def test_uncached_foreign_key_still_requires_valid_reference(self):
        data = self.general_data('bad reference')
        original = Question.save

        def invalid_subject(question, *args, **kwargs):
            question.subject_id = 2147483647
            return original(question, *args, **kwargs)

        with patch.object(Question, 'save', invalid_subject):
            with self.assertRaises(ValidationError) as error:
                confirm_import(data, self.user)
        self.assertIn('subject', error.exception.message_dict)
        self.assertFalse(Question.objects.exists())
        self.assertFalse(ImportBatch.objects.exists())

    def test_existing_content_remains_immutable_inside_creation_scope(self):
        batch = confirm_import(self.general_data('immutable', 1), self.user)
        question = batch.imported_questions.get().question
        revision = question.current_revision
        revision.correct_answer = 'B'
        with self.assertRaises(ValidationError):
            with transaction.atomic(), creation_batch():
                revision.save(_assembly=True)
        revision.refresh_from_db()
        self.assertEqual(revision.correct_answer, 'A')
        edition = revision.translations.get()
        edition.question_text = 'Attempted overwrite'
        with self.assertRaises(ValidationError):
            with transaction.atomic(), creation_batch():
                edition.save(_assembly=True)
        edition.refresh_from_db()
        self.assertNotEqual(edition.question_text, 'Attempted overwrite')
