from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase

from exams.models import Subject, Topic
from .models import Question, QuestionTopic
from .tagging import set_question_topics


class TopicTagTransactionTests(TransactionTestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="History", code="H", slug="history")
        self.first = Topic.objects.create(subject=self.subject, name="Ancient", slug="ancient")
        self.second = Topic.objects.create(subject=self.subject, name="Modern", slug="modern")
        self.question = Question.objects.create(subject=self.subject)

    def test_unclassified_secondary_tag_cannot_commit(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO questions_questiontopic(question_id,topic_id,is_primary) VALUES(%s,%s,FALSE)", [self.question.pk, self.first.pk])
        self.assertFalse(QuestionTopic.objects.exists())
        self.question.refresh_from_db()
        self.assertIsNone(self.question.topic_id)

    def test_concurrent_replacements_serialize_on_master(self):
        barrier = Barrier(2)
        question_id = self.question.pk
        topics = [self.first.pk, self.second.pk]

        def assign(primary):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return set_question_topics(question_id, topics, primary_topic_id=primary).topic_id
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(assign, topics))
        self.assertCountEqual(results, topics)
        self.question.refresh_from_db()
        self.assertEqual(QuestionTopic.objects.filter(question=self.question).count(), 2)
        self.assertEqual(QuestionTopic.objects.get(question=self.question, is_primary=True).topic_id, self.question.topic_id)
