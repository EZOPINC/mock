from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from exams.models import Exam, ExamAuthority, Subject, Topic
from . import services
from .models import Question, QuestionExam, QuestionRevision, QuestionSource, QuestionSourceReference


def content(**overrides):
    return dict(language="en", question_text="Choose the correct answer.", option_a="One", option_b="Two", option_c="Three", option_d="Four", correct_answer="A", explanation="Explanation") | overrides


class QuestionFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.subject = Subject.objects.create(name="English", code="EN", slug="english")
        cls.topic = Topic.objects.create(subject=cls.subject, name="Grammar", slug="grammar")
        cls.authority = ExamAuthority.objects.create(name="Commission", code="PC", slug="commission")
        cls.exam = Exam.objects.create(authority=cls.authority, name="Exam", code="EXAM", slug="exam")

    def make_question(self, **overrides):
        return services.create_question(subject=self.subject, topic=self.topic, revision=content(**overrides))

    def publish(self, question):
        services.mark_reviewed(question)
        return services.publish_question(question)


class QuestionModelTests(QuestionFixture):
    def test_initial_revision_and_defaults(self):
        question = self.make_question()
        self.assertEqual(connection.vendor, "postgresql")
        self.assertEqual(question.publication_status, "draft")
        self.assertEqual(question.review_status, "pending_review")
        self.assertIsNone(question.published_revision_id)
        self.assertEqual(question.current_revision.revision_number, 1)
        self.assertEqual(question.current_revision.question, question)

    def test_bengali_is_independent_and_preserved(self):
        english = self.make_question()
        bengali = self.make_question(language="bn", question_text="সঠিক উত্তর নির্বাচন করুন।", explanation="ব্যাখ্যা")
        self.assertNotEqual(english.pk, bengali.pk)
        self.assertEqual(bengali.current_revision.language, "bn")
        self.assertEqual(bengali.current_revision.question_text, "সঠিক উত্তর নির্বাচন করুন।")
        self.assertEqual(bengali.current_revision.explanation, "ব্যাখ্যা")

    def test_language_cannot_change(self):
        question = self.make_question()
        for language in ("bn", "fr", ""):
            with self.subTest(language=language), self.assertRaises(ValidationError):
                services.create_revision(question, **content(language=language))
        self.assertEqual(question.revisions.count(), 1)

    def test_required_content_and_answers(self):
        for field in ("question_text", "option_a", "option_b", "option_c", "option_d"):
            for value in ("", "  "):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    self.make_question(**{field: value})
        for answer in ("E", "a", "", "AB"):
            with self.subTest(answer=answer), self.assertRaises(ValidationError):
                self.make_question(correct_answer=answer)
        self.assertEqual(Question.objects.count(), 0)

    def test_topic_must_match_subject(self):
        other = Subject.objects.create(name="Math", code="MATH", slug="math")
        with self.assertRaises(ValidationError):
            services.create_question(subject=other, topic=self.topic, revision=content())
        question = services.create_question(subject=other, revision=content())
        self.assertIsNone(question.topic_id)

    def test_exam_association_uniqueness_and_protection(self):
        question = self.make_question()
        QuestionExam.objects.create(question=question, exam=self.exam)
        with self.assertRaises(IntegrityError), transaction.atomic():
            QuestionExam.objects.create(question=question, exam=self.exam)
        self.assertEqual(list(question.exams.all()), [self.exam])
        with self.assertRaises(ProtectedError):
            self.exam.delete()
        invalid = QuestionExam(question=question, exam_id=999999)
        with self.assertRaises(ValidationError):
            invalid.full_clean()

    def test_multiple_sources_and_metadata(self):
        question = self.make_question()
        for name in ("Book A", "Book B"):
            source = QuestionSource.objects.create(source_name=name, source_document=f"{name}.pdf")
            reference = QuestionSourceReference.objects.create(question=question, source=source, source_page="iv", source_question_number="12(b)")
            self.assertEqual(reference.source_page, "iv")
            with self.assertRaises(ProtectedError):
                source.delete()
        self.assertEqual(question.sources.count(), 2)

    def test_revision_number_uniqueness(self):
        question = self.make_question()
        with self.assertRaises(ValidationError):
            QuestionRevision.objects.create(question=question, revision_number=1, **content())
        # Bypass only model validation to verify the PostgreSQL constraint.
        with patch.object(QuestionRevision, "full_clean"), self.assertRaises(IntegrityError), transaction.atomic():
            QuestionRevision.objects.create(question=question, revision_number=1, **content())

    def test_database_checks_for_revision_content_and_enums(self):
        question = self.make_question()
        for overrides in ({"revision_number": 0}, {"language": "INVALID"}, {"correct_answer": "E"}, {"option_d": ""}, {"question_text": ""}):
            data = {"revision_number": 2, **content(), **overrides}
            with self.subTest(data=overrides), patch.object(QuestionRevision, "full_clean"), self.assertRaises(IntegrityError), transaction.atomic():
                QuestionRevision.objects.create(question=question, **data)

    def test_question_database_status_checks(self):
        for overrides in ({"publication_status": "invalid"}, {"review_status": "invalid"}, {"publication_status": "published"}):
            with self.subTest(overrides=overrides), patch.object(Question, "full_clean"), self.assertRaises(IntegrityError), transaction.atomic():
                Question(subject=self.subject, **overrides).save(_workflow=True)

    def test_current_revision_cannot_belong_to_other_question(self):
        question = self.make_question()
        other = self.make_question()
        question.current_revision = other.current_revision
        with self.assertRaises(ValidationError):
            question.full_clean()

    def test_published_pointer_must_be_owned_and_previously_published(self):
        question = self.make_question()
        question.published_revision = question.current_revision
        with self.assertRaises(ValidationError):
            question.full_clean()
        other = services.publish_question(services.mark_reviewed(self.make_question()))
        question.published_revision = other.published_revision
        with self.assertRaises(ValidationError):
            question.full_clean()

    def test_draft_content_changes_also_create_new_revisions(self):
        question = self.make_question()
        revision = question.current_revision
        revision.question_text = "Changed"
        with self.assertRaises(ValidationError):
            revision.save()
        revision.refresh_from_db()
        self.assertEqual(revision.question_text, content()["question_text"])

    def test_revisions_and_referenced_questions_cannot_be_deleted(self):
        question = self.publish(self.make_question())
        old = question.current_revision
        services.create_revision(question, **content(question_text="New draft"))
        for operation in (old.delete, lambda: QuestionRevision.objects.filter(pk=old.pk).delete(), question.delete, lambda: Question.objects.filter(pk=question.pk).delete(), self.subject.delete, self.topic.delete):
            with self.assertRaises(ProtectedError):
                operation()
        self.assertTrue(QuestionRevision.objects.filter(pk=old.pk).exists())


class QuestionWorkflowTests(QuestionFixture):
    def test_review_then_publication(self):
        question = self.make_question()
        self.assertIsNone(services.get_published_revision(question))
        with self.assertRaises(ValidationError):
            services.publish_question(question)
        question = self.publish(question)
        self.assertEqual(question.published_revision_id, question.current_revision_id)
        self.assertIsNotNone(question.published_revision.published_at)
        self.assertEqual(services.get_published_revision(question), question.published_revision)

    def test_empty_question_cannot_be_reviewed(self):
        question = Question.objects.create(subject=self.subject)
        with self.assertRaises(ValidationError):
            services.mark_reviewed(question)

    def test_new_draft_does_not_replace_published_content(self):
        question = self.publish(self.make_question())
        old = question.published_revision
        new = services.create_revision(question, **content(question_text="New content"))
        question.refresh_from_db()
        self.assertEqual(new.revision_number, 2)
        self.assertEqual(question.current_revision_id, new.pk)
        self.assertEqual(question.review_status, "pending_review")
        self.assertEqual(services.get_published_revision(question), old)
        with self.assertRaises(ValidationError):
            services.publish_question(question)
        self.publish(question)
        self.assertEqual(services.get_published_revision(question), new)
        old.refresh_from_db()
        self.assertIsNotNone(old.published_at)
        self.assertEqual(old.question_text, content()["question_text"])

    def test_historical_published_revision_cannot_change_or_clear_marker(self):
        question = self.publish(self.make_question())
        old = question.published_revision
        services.create_revision(question, **content())
        self.publish(question)
        for field, value in (("question_text", "Changed"), ("published_at", None), ("language", "bn"), ("revision_number", 99)):
            revision = QuestionRevision.objects.get(pk=old.pk)
            setattr(revision, field, value)
            with self.subTest(field=field), self.assertRaises(ValidationError):
                revision.save()

    def test_bulk_writes_cannot_bypass_workflow(self):
        question = self.make_question()
        for operation in (
            lambda: Question.objects.filter(pk=question.pk).update(publication_status="published"),
            lambda: QuestionRevision.objects.filter(question=question).update(question_text="changed"),
            lambda: Question.objects.bulk_create([Question(subject=self.subject)]),
            lambda: QuestionRevision.objects.bulk_create([QuestionRevision(question=question, revision_number=2, **content())]),
            lambda: Question.objects.bulk_update([question], ["review_status"]),
        ):
            with self.assertRaises(ValidationError):
                operation()
        question.publication_status = "published"
        with self.assertRaises(ValidationError):
            question.save()

    def test_stale_review_and_publication_are_rejected(self):
        question = self.make_question()
        old = question.current_revision_id
        services.mark_reviewed(question, revision_id=old)
        services.create_revision(question, **content())
        for operation in (services.mark_reviewed, services.publish_question):
            with self.assertRaises(ValidationError):
                operation(question, revision_id=old)

    def test_public_query_excludes_drafts_and_unreviewed_content(self):
        draft = self.make_question()
        reviewed = self.make_question()
        services.mark_reviewed(reviewed)
        live = self.publish(self.make_question())
        approved = live.published_revision
        services.create_revision(live, **content(question_text="Secret draft"))
        self.assertEqual(list(services.published_questions()), [live])
        self.assertEqual(services.get_published_revision(live), approved)
        for question in (draft, reviewed):
            self.assertIsNone(services.get_published_revision(question))

    def test_initial_creation_rolls_back_on_invalid_revision(self):
        with self.assertRaises(ValidationError):
            self.make_question(correct_answer="X")
        self.assertEqual(Question.objects.count(), 0)
        self.assertEqual(QuestionRevision.objects.count(), 0)

    def test_revision_creation_rolls_back_when_pointer_save_fails(self):
        question = self.make_question()
        with patch.object(Question, "save", side_effect=ValidationError("Failure")), self.assertRaises(ValidationError):
            services.create_revision(question, **content())
        self.assertEqual(question.revisions.count(), 1)
        question.refresh_from_db()
        self.assertEqual(question.current_revision.revision_number, 1)

    def test_publication_rolls_back_marker_when_pointer_save_fails(self):
        question = self.make_question()
        services.mark_reviewed(question)
        with patch.object(Question, "save", side_effect=ValidationError("Failure")), self.assertRaises(ValidationError):
            services.publish_question(question)
        question.refresh_from_db()
        self.assertIsNone(question.current_revision.published_at)
        self.assertIsNone(question.published_revision_id)


class QuestionAdminTests(QuestionFixture):
    def setUp(self):
        self.question = self.make_question()
        self.superuser = get_user_model().objects.create_superuser(username="admin", email="admin@example.test")
        self.url = reverse("admin:questions_question_changelist")

    def sign_in(self):
        self.client.force_login(self.superuser)

    def action(self, action):
        return self.client.post(self.url, {"action": action, "_selected_action": [self.question.pk]}, follow=True)

    def test_models_registered_and_guest_student_staff_permissions(self):
        for model in (Question, QuestionRevision, QuestionExam, QuestionSource, QuestionSourceReference):
            self.assertTrue(admin.site.is_registered(model))
        self.assertEqual(self.client.get(self.url).status_code, 302)
        student = get_user_model().objects.create_user(username="student")
        self.client.force_login(student)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        student.is_staff = True
        student.save()
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_view_only_staff_cannot_create_revision_or_publish(self):
        user = get_user_model().objects.create_user(username="viewer", is_staff=True)
        user.user_permissions.add(Permission.objects.get(content_type__app_label="questions", codename="view_question"))
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        url = reverse("admin:questions_question_new_revision", args=[self.question.pk])
        self.assertEqual(self.client.post(url, content()).status_code, 403)
        self.action("review_questions")
        self.question.refresh_from_db()
        self.assertEqual(self.question.review_status, "pending_review")

    def test_admin_pages_and_readonly_historical_revisions(self):
        self.sign_in()
        for route, args in (("admin:questions_question_add", []), ("admin:questions_question_change", [self.question.pk]), ("admin:questions_questionrevision_change", [self.question.current_revision_id]), ("admin:questions_question_new_revision", [self.question.pk])):
            self.assertEqual(self.client.get(reverse(route, args=args)).status_code, 200)
        revision_url = reverse("admin:questions_questionrevision_change", args=[self.question.current_revision_id])
        self.assertEqual(self.client.post(revision_url, {"question_text": "changed"}).status_code, 403)

    def test_actions_validate_review_and_publication(self):
        self.sign_in()
        response = self.action("publish_questions")
        self.assertContains(response, "Review the current revision before publishing")
        self.assertIsNone(services.get_published_revision(self.question))
        self.action("review_questions")
        self.action("publish_questions")
        self.assertIsNotNone(services.get_published_revision(self.question))

    def test_revision_form_displays_errors_and_keeps_published_version(self):
        self.sign_in()
        question = self.publish(self.question)
        url = reverse("admin:questions_question_new_revision", args=[question.pk])
        response = self.client.post(url, content(language="bn"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Language cannot change")
        response = self.client.post(url, content(question_text="New draft"))
        self.assertRedirects(response, reverse("admin:questions_question_change", args=[question.pk]))
        self.assertEqual(services.get_published_revision(question), question.published_revision)

    def test_admin_initial_creation_and_association_inlines(self):
        self.sign_in()
        source = QuestionSource.objects.create(source_name="Book", source_document="book.pdf")
        data = {"subject": self.subject.pk, "topic": self.topic.pk, **content(),
                "revisions-TOTAL_FORMS": "0", "revisions-INITIAL_FORMS": "0",
                "exam_associations-TOTAL_FORMS": "1", "exam_associations-INITIAL_FORMS": "0",
                "exam_associations-0-exam": self.exam.pk,
                "source_references-TOTAL_FORMS": "1", "source_references-INITIAL_FORMS": "0",
                "source_references-0-source": source.pk, "source_references-0-source_page": "12"}
        response = self.client.post(reverse("admin:questions_question_add"), data)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["adminform"].form.errors)
        question = Question.objects.exclude(pk=self.question.pk).get()
        self.assertEqual(question.revisions.count(), 1)
        self.assertEqual(question.exams.get(), self.exam)
        self.assertEqual(question.sources.get(), source)
        self.assertEqual(question.publication_status, "draft")

    def test_admin_revision_endpoint_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.superuser)
        url = reverse("admin:questions_question_new_revision", args=[self.question.pk])
        self.assertEqual(client.post(url, content()).status_code, 403)


class QuestionConcurrencyTests(TransactionTestCase):
    """Real transactions and separate connections are required to test row locks."""

    def setUp(self):
        subject = Subject.objects.create(name="English", code="EN", slug="english")
        self.question = services.create_question(subject=subject, revision=content())

    def run_concurrently(self, *operations):
        barrier = Barrier(len(operations))

        def run(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            return list(executor.map(run, operations))

    def test_concurrent_revision_numbers_are_serialized(self):
        def create():
            return services.create_revision(self.question.pk, **content()).revision_number
        self.assertEqual(sorted(self.run_concurrently(create, create)), [2, 3])
        self.question.refresh_from_db()
        self.assertEqual(self.question.current_revision.revision_number, 3)

    def test_publication_racing_new_draft_never_publishes_unreviewed_content(self):
        services.mark_reviewed(self.question)
        services.publish_question(self.question)
        second = services.create_revision(self.question, **content(question_text="Reviewed update"))
        services.mark_reviewed(self.question, revision_id=second.pk)

        def publish():
            try:
                services.publish_question(self.question.pk, revision_id=second.pk)
                return "published"
            except ValidationError:
                return "stale"

        def create():
            return services.create_revision(self.question.pk, **content(question_text="Unreviewed update")).pk

        result, draft_id = self.run_concurrently(publish, create)
        self.assertIn(result, ("published", "stale"))
        self.question.refresh_from_db()
        self.assertEqual(self.question.current_revision_id, draft_id)
        self.assertEqual(self.question.review_status, "pending_review")
        self.assertNotEqual(self.question.published_revision_id, draft_id)
        self.assertIsNone(self.question.current_revision.published_at)
