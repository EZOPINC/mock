from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from exams.models import Part, Module, Submodule, Chapter, Topic
from .models import Question, QuestionSource, QuestionSourceReference
from .services import create_question
from .tagging import set_question_topics
from .tests import QuestionFixture, content


class QuestionAdminQueryTests(QuestionFixture):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username='performance-admin')
        self.client.force_login(self.user)
        self.url = reverse('admin:questions_question_changelist')
        self.part = Part.objects.create(subject=self.subject, name='Part', slug='part')
        self.module = Module.objects.create(part=self.part, name='Module', slug='module')
        self.submodule = Submodule.objects.create(module=self.module, name='Submodule', slug='submodule')
        self.chapter = Chapter.objects.create(submodule=self.submodule, name='Chapter', slug='chapter')
        self.nested = Topic.objects.create(subject=self.subject, chapter=self.chapter, name='Nested', slug='nested')
        self.question = create_question(subject=self.subject, topic=self.nested, revision=content())
        set_question_topics(self.question, [self.nested.pk, self.topic.pk], primary_topic_id=self.nested.pk)

    def measured_page(self, parameters=None):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url, parameters or {})
        self.assertEqual(response.status_code, 200)
        return response, len(queries)

    def test_query_count_does_not_grow_with_topics_or_question_rows(self):
        response, baseline = self.measured_page()
        self.assertContains(response, 'English: Part: Module: Submodule: Chapter: Nested')
        for index in range(12):
            topic = Topic.objects.create(subject=self.subject, chapter=self.chapter, name=f'Extra {index}', slug=f'extra-{index}')
            create_question(subject=self.subject, topic=topic, revision=content(question_text=f'Question {index}'))
        response, grown = self.measured_page()
        self.assertEqual(grown, baseline)
        self.assertLessEqual(grown, 25)
        self.assertEqual(response.context['cl'].result_count, 13)

    def test_all_skipped_parent_labels_are_loaded_without_per_row_queries(self):
        for index, parent in enumerate(({}, {'part': self.part}, {'module': self.module}, {'chapter': self.chapter})):
            topic = Topic.objects.create(subject=self.subject, name=f'Path {index}', slug=f'path-{index}', **parent)
            create_question(subject=self.subject, topic=topic, revision=content())
        _, baseline = self.measured_page()
        topic = Topic.objects.create(subject=self.subject, module=self.module, name='Another', slug='another')
        create_question(subject=self.subject, topic=topic, revision=content())
        response, grown = self.measured_page()
        self.assertEqual(grown, baseline)
        self.assertContains(response, 'English: Part: Module: Another')

    def test_existing_primary_secondary_and_parent_filter_urls_still_work(self):
        for path, node in (('topic', self.nested), ('topic_associations__topic', self.topic),
                           ('topic__chapter', self.chapter), ('topic__chapter__submodule', self.submodule)):
            response, _ = self.measured_page({path + '__id__exact': node.pk})
            self.assertEqual([row.pk for row in response.context['cl'].result_list], [self.question.pk])
        response, _ = self.measured_page({'topic__isnull': 'True'})
        self.assertEqual(response.context['cl'].result_count, 0)

    def test_related_only_filter_still_excludes_unused_topics(self):
        unused = Topic.objects.create(subject=self.subject, name='Unused', slug='unused')
        response, _ = self.measured_page()
        filters = {spec.field_path: spec for spec in response.context['cl'].filter_specs if hasattr(spec, 'field_path')}
        any_topic = filters['topic_associations__topic']
        self.assertEqual({pk for pk, label in any_topic.lookup_choices}, {self.nested.pk, self.topic.pk})
        self.assertIn(unused.pk, {pk for pk, label in filters['topic'].lookup_choices})

    def test_search_remains_deduplicated_with_multiple_matching_sources(self):
        for index in range(2):
            source = QuestionSource.objects.create(source_name=f'Needle {index}', source_document=f'Needle document {index}')
            QuestionSourceReference.objects.create(question=self.question, source=source)
        response, count = self.measured_page({'q': 'Needle'})
        self.assertEqual(response.context['cl'].result_count, 1)
        self.assertLessEqual(count, 25)

    def test_anonymous_users_still_require_admin_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
