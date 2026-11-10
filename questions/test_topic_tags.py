from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from unittest.mock import patch

from exams.models import Subject, Topic
from .forms import QuestionAdminForm
from .models import Question, QuestionTopic
from .selectors import questions_by_topics
from .tagging import set_question_topics
from .tests import QuestionFixture


class QuestionTopicTests(QuestionFixture):
    def setUp(self):
        self.extra = Topic.objects.create(subject=self.subject, name="Vocabulary", slug="vocabulary")
        self.other_subject = Subject.objects.create(name="History", code="H", slug="history")
        self.foreign = Topic.objects.create(subject=self.other_subject, name="Ancient", slug="ancient")
        self.question = self.make_question()

    def test_legacy_creation_and_edits_synchronize_primary_without_signals(self):
        self.assertEqual(list(self.question.topic_associations.values_list("topic_id", "is_primary")), [(self.topic.pk, True)])
        self.question.topic = self.extra
        self.question.save()
        self.assertEqual(self.question.topic_associations.get(is_primary=True).topic_id, self.extra.pk)
        self.assertFalse(self.question.topic_associations.get(topic=self.topic).is_primary)
        self.question.topic = None
        self.question.save()
        self.assertFalse(self.question.topic_associations.exists())

    def test_multiple_topics_single_primary_and_idempotent_replacement(self):
        revision = self.question.current_revision_id
        ids = [self.topic.pk, self.extra.pk]
        set_question_topics(self.question, ids, primary_topic_id=self.extra.pk)
        before = list(self.question.topic_associations.values_list("pk", "topic_id", "is_primary"))
        set_question_topics(self.question, ids, primary_topic_id=self.extra.pk)
        self.assertEqual(list(self.question.topic_associations.values_list("pk", "topic_id", "is_primary")), before)
        self.question.refresh_from_db()
        self.assertEqual(self.question.topic_id, self.extra.pk)
        self.assertEqual(self.question.current_revision_id, revision)
        set_question_topics(self.question, [], primary_topic_id=None)
        self.question.refresh_from_db()
        self.assertIsNone(self.question.topic_id)
        self.assertEqual(self.question.topic_associations.count(), 0)

    def test_invalid_assignments_roll_back(self):
        for ids, primary in (([self.topic.pk, self.topic.pk], self.topic.pk), ([self.topic.pk, self.foreign.pk], self.topic.pk),
                             ([self.topic.pk], None), ([self.topic.pk], self.extra.pk), ([], self.topic.pk), ([999999], 999999)):
            with self.subTest(ids=ids, primary=primary), self.assertRaises(ValidationError):
                set_question_topics(self.question, ids, primary_topic_id=primary)
        self.question.refresh_from_db()
        self.assertEqual(self.question.topic_id, self.topic.pk)
        self.assertEqual(self.question.topic_associations.count(), 1)

    def test_model_add_remove_and_last_primary_rules(self):
        tag = QuestionTopic.objects.create(question=self.question, topic=self.extra)
        self.assertFalse(tag.is_primary)
        with self.assertRaises(ValidationError):
            self.question.topic_associations.get(is_primary=True).delete()
        tag.delete()
        self.question.topic_associations.get(is_primary=True).delete()
        self.question.refresh_from_db()
        self.assertIsNone(self.question.topic_id)
        tag = QuestionTopic.objects.create(question=self.question, topic=self.extra, is_primary=True)
        self.question.refresh_from_db()
        self.assertEqual(self.question.topic_id, self.extra.pk)
        tag.is_primary = False
        with self.assertRaises(ValidationError):
            tag.save()

    def test_database_rejects_duplicate_cross_subject_and_multiple_primary(self):
        for topic_id, primary in ((self.topic.pk, False), (self.extra.pk, True), (self.foreign.pk, False)):
            with self.subTest(topic_id=topic_id, primary=primary), self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("INSERT INTO questions_questiontopic(question_id,topic_id,is_primary) VALUES(%s,%s,%s)", [self.question.pk, topic_id, primary])

    def test_database_rejects_missing_primary_and_subject_reassignment(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM questions_questiontopic WHERE question_id=%s", [self.question.pk])
                cursor.execute("SET CONSTRAINTS questions_tag_pointer_consistency, questions_primary_tag_consistency IMMEDIATE")
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE questions_question SET subject_id=%s WHERE id=%s", [self.other_subject.pk, self.question.pk])
        self.question.subject = self.other_subject
        with self.assertRaises(ValidationError):
            self.question.save()

    def test_raw_legacy_pointer_write_synchronizes_tags(self):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE questions_question SET topic_id=%s WHERE id=%s", [self.extra.pk, self.question.pk])
        self.assertEqual(self.question.topic_associations.get(is_primary=True).topic_id, self.extra.pk)

    def test_assigned_topics_cannot_be_deleted_or_moved(self):
        set_question_topics(self.question, [self.topic.pk, self.extra.pk], primary_topic_id=self.topic.pk)
        with self.assertRaises(ProtectedError):
            self.extra.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE exams_topic SET subject_id=%s WHERE id=%s", [self.other_subject.pk, self.extra.pk])

    def test_any_topic_selector_deduplicates_master_question(self):
        set_question_topics(self.question, [self.topic.pk, self.extra.pk], primary_topic_id=self.topic.pk)
        self.assertEqual(list(questions_by_topics([self.topic.pk, self.extra.pk])), [self.question])
        self.assertEqual(list(questions_by_topics([self.extra.pk])), [self.question])
        self.assertEqual(list(Question.objects.filter(topic=self.topic)), [self.question])

    def test_general_question_filter_includes_secondary_topic(self):
        from general_question.views import filtered
        set_question_topics(self.question, [self.topic.pk, self.extra.pk], primary_topic_id=self.topic.pk)
        request = RequestFactory().get("/", {"topic": self.extra.pk})
        with patch("general_question.views.public_questions", return_value=Question.objects.all()):
            form, questions, _ = filtered(request)
        self.assertTrue(form.is_valid())
        self.assertEqual(list(questions), [self.question])

    def test_admin_form_initial_values_scope_and_primary_validation(self):
        set_question_topics(self.question, [self.topic.pk, self.extra.pk], primary_topic_id=self.topic.pk)
        form = QuestionAdminForm(instance=self.question)
        self.assertEqual(form.initial["additional_topics"], [self.extra.pk])
        for primary, extras in ((self.topic.pk, [self.foreign.pk]), ("", [self.extra.pk]), (self.topic.pk, [self.topic.pk]),
                                (self.topic.pk, [self.extra.pk, self.extra.pk])):
            with self.subTest(primary=primary, extras=extras):
                bound = QuestionAdminForm(instance=self.question, data={"subject": self.subject.pk, "topic": primary, "additional_topics": extras})
                self.assertFalse(bound.is_valid())

    def test_admin_save_and_any_topic_filter(self):
        user = get_user_model().objects.create_superuser(username="tag-admin")
        request = RequestFactory().post("/")
        request.user = user
        model_admin = admin.site._registry[Question]
        admin_form = model_admin.get_form(request, self.question)
        form = admin_form(instance=self.question, data={"subject": self.subject.pk, "topic": self.topic.pk, "additional_topics": [self.extra.pk]})
        self.assertTrue(hasattr(form.fields["topic"].widget, "widget"))
        self.assertTrue(form.is_valid(), form.errors)
        question = form.save(commit=False)
        model_admin.save_model(request, question, form, change=True)
        model_admin.save_related(request, form, [], change=True)
        self.assertEqual(question.topic_associations.count(), 2)
        self.client.force_login(user)
        response = self.client.get(reverse("admin:questions_question_changelist"), {"topic_associations__topic__id__exact": self.extra.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["cl"].result_list), [self.question])
