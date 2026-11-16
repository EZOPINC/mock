"""Question-import regression coverage for optional Sub-modules and current paths."""
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook

from exams.models import Part, Module, Submodule, Chapter, Topic
from questions.models import Question
from .parsing import COLUMNS, parse_upload
from .services import confirm_import
from .taxonomy import TaxonomyCatalogue
from .tests import ImportFixture, csv_file, values
from .validation import validate


class QuestionTaxonomyIntegrityTests(ImportFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.india = Part.objects.create(subject=cls.subject, code='INDIA', name='India', slug='india')
        cls.wb = Part.objects.create(subject=cls.subject, code='WB', name='West Bengal', slug='west-bengal')
        cls.module = Module.objects.create(part=cls.wb, code='WB-M', name='WB Module', slug='wb-module')
        cls.submodule = Submodule.objects.create(module=cls.module, code='WB-S', name='WB Submodule', slug='wb-submodule')
        cls.chapter = Chapter.objects.create(submodule=cls.submodule, code='WB-C', name='WB Chapter', slug='wb-chapter')
        cls.leaf = Topic.objects.create(subject=cls.subject, chapter=cls.chapter, code='WB-T', name='WB Topic', slug='wb-topic')
        cls.secondary = Topic.objects.create(subject=cls.subject, code='EXTRA', name='Extra', slug='extra')

    def row(self, **changes):
        return values(**({'subject': '', 'topic': '', 'topic_code': 'WB-T'} | changes))

    def test_csv_xlsx_aliases_full_ancestry_and_normalized_codes(self):
        headers = tuple('sub_module_code' if column == 'submodule_code' else
                        'sub_module' if column == 'submodule' else column for column in COLUMNS)
        row = self.row(subject_code=' en ', part_code=' wb ', module_code='wb-m', sub_module_code='wb-s',
                       sub_module='WB Submodule', chapter_code='wb-c', topic_code='wb-t', additional_topic_codes='extra; EXTRA')
        book = Workbook()
        book.active.append(headers)
        book.active.append([row.get(header, '') for header in headers])
        stream = BytesIO()
        book.save(stream)
        for upload in (csv_file([row], headers=headers), SimpleUploadedFile('aliases.xlsx', stream.getvalue())):
            parsed = parse_upload(upload)
            result = TaxonomyCatalogue().resolve(parsed['rows'][0]['values'], {}, {}, {})
            self.assertFalse(result['taxonomy_errors'])
            self.assertEqual(result['topic'].pk, self.leaf.pk)
            self.assertEqual([node.pk for node in result['secondary_topics']], [self.secondary.pk])
            self.assertIn('West Bengal [WB]', result['taxonomy_path'])
            self.assertEqual(parsed['header_aliases']['sub_module_code'], 'submodule_code')

    def test_alias_and_canonical_headers_together_are_rejected(self):
        for alias, canonical in (('sub_module_code', 'submodule_code'), ('sub_module', 'submodule')):
            with self.subTest(alias=alias), self.assertRaisesMessage(ValidationError, 'Duplicate column headers'):
                parse_upload(csv_file([self.row()], headers=(*COLUMNS, alias)))

    def test_submodule_only_context_no_crash_or_implicit_question_tag(self):
        row = self.row(topic_code='', submodule_code='WB-S')
        result = TaxonomyCatalogue().resolve(row, {}, {}, {})
        self.assertFalse(result['taxonomy_errors'])
        self.assertIsNone(result['topic'])
        self.assertIn('WB Submodule [WB-S]', result['taxonomy_path'])
        data = self.data([row])
        preview = validate(data)
        self.assertEqual(preview['error_count'], 0)
        self.assertTrue(any('context only' in warning for warning in preview['rows'][0]['warnings']))
        question = confirm_import(data, self.user).imported_questions.get().question
        self.assertIsNone(question.topic_id)
        self.assertFalse(question.topic_associations.exists())

    def test_stale_part_ancestry_blocked_in_preview_and_confirmation(self):
        data = self.data([self.row(part_code='INDIA')])
        preview = validate(data)
        self.assertGreater(preview['error_count'], 0)
        self.assertTrue(any('ancestor path' in message for message in preview['rows'][0]['errors']))
        with self.assertRaises(ValidationError):
            confirm_import(data, self.user)
        self.assertFalse(Question.objects.exists())

    def test_missing_submodule_parent_is_a_preview_error_without_proposals(self):
        row = self.row(topic_code='', submodule='New unattached sub')
        catalogue = TaxonomyCatalogue()
        result = catalogue.resolve(row, {'subject_id': self.subject.pk}, {}, {})
        self.assertTrue(any('requires a Module parent' in error for error in result['taxonomy_errors']))
        self.assertFalse(catalogue.pending)
        self.assertFalse(Submodule.objects.filter(name='New unattached sub').exists())

    def test_submodule_topic_requires_chapter_in_preview(self):
        row = self.row(topic_code='', submodule_code='WB-S', topic='New topic')
        result = TaxonomyCatalogue().resolve(row, {}, {}, {})
        self.assertTrue(any('requires a Chapter' in error for error in result['taxonomy_errors']))
        self.assertFalse(Topic.objects.filter(name='New topic').exists())

    def test_named_new_path_includes_submodule_and_commits_atomically(self):
        data = self.data([self.row(topic_code='', module_code='WB-M', submodule='New sub',
                                   chapter='New chapter', topic='New topic')])
        self.assertEqual(validate(data)['error_count'], 0)
        self.assertFalse(Submodule.objects.filter(name='New sub').exists())
        question = confirm_import(data, self.user).imported_questions.get().question
        self.assertEqual(question.topic.chapter.submodule.module_id, self.module.pk)
        self.assertEqual(question.topic.chapter.submodule.subject_id, self.subject.pk)

    def test_bilingual_master_receives_one_shared_primary_and_secondary_tag_set(self):
        row = self.row(question_text_en='Which city is the capital of West Bengal?',
                       option_a_en='Kolkata', option_b_en='Siliguri', option_c_en='Asansol', option_d_en='Durgapur',
                       question_text_bn='পশ্চিমবঙ্গের রাজধানী কোন শহর?',
                       option_a_bn='কলকাতা', option_b_bn='শিলিগুড়ি', option_c_bn='আসানসোল', option_d_bn='দুর্গাপুর',
                       question_text='', option_a='', option_b='', option_c='', option_d='',
                       additional_topic_codes='EXTRA')
        parsed = parse_upload(csv_file([row], headers=(*COLUMNS, 'question_text_en', 'option_a_en', 'option_b_en',
                                   'option_c_en', 'option_d_en', 'question_text_bn', 'option_a_bn', 'option_b_bn', 'option_c_bn', 'option_d_bn')))
        data = self.data([self.row()])
        data.update(parsed)
        batch = confirm_import(data, self.user)
        question = batch.imported_questions.get().question
        self.assertEqual(Question.objects.count(), 1)
        self.assertEqual(set(question.current_revision.translations.values_list('language', flat=True)), {'en', 'bn'})
        self.assertEqual(set(question.topic_associations.values_list('topic_id', 'is_primary')),
                         {(self.leaf.pk, True), (self.secondary.pk, False)})

    def test_current_ancestry_revalidated_on_confirmation(self):
        data = self.data([self.row()])
        self.assertEqual(validate(data)['error_count'], 0)
        data['rows'][0]['values']['submodule_code'] = 'missing-submodule'
        with self.assertRaises(ValidationError):
            confirm_import(data, self.user)
        self.assertFalse(Question.objects.exists())

    def test_upload_page_exposes_field_reference(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('imports:upload'))
        self.assertContains(response, 'CSV/XLSX columns: required fields and taxonomy tagging')
        self.assertContains(response, 'sub_module_code')
