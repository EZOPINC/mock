from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.http import Http404
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from exams.models import Exam, ExamAuthority, Subject, Topic
from questions.eligibility import eligible_question_ids
from questions.models import Question, QuestionExam
from questions.services import add_translation, create_question, create_revision, mark_reviewed, publish_question
from .forms import PracticeStartForm
from .models import PracticeQuestion, PracticeSession
from .services import abandon_session, performance, progress, start_session, submit_answer


class PracticeFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.authority = ExamAuthority.objects.create(name="Authority", code="A", slug="authority")
        cls.exam = Exam.objects.create(authority=cls.authority, name="Exam", code="E", slug="exam")
        cls.other_exam = Exam.objects.create(authority=cls.authority, name="Other exam", code="O", slug="other-exam")
        cls.subject = Subject.objects.create(name="Mathematics", code="M", slug="mathematics")
        cls.other_subject = Subject.objects.create(name="History", code="H", slug="history")
        cls.topic = Topic.objects.create(subject=cls.subject, name="Arithmetic", slug="arithmetic")
        cls.other_topic = Topic.objects.create(subject=cls.other_subject, name="Ancient", slug="ancient")
        cls.user = get_user_model().objects.create_user(username="student")
        cls.other_user = get_user_model().objects.create_user(username="other")

    def question(self, *, subject=None, topic="default", exam=None, published=True, language="en", **changes):
        subject = subject or self.subject
        if topic == "default":
            topic = self.topic if subject.pk == self.subject.pk else None
        question = create_question(subject=subject, topic=topic, revision=dict(language=language,
            question_text="Original question " + str(Question.objects.count() + 1), option_a="First", option_b="Second",
            option_c="Third", option_d="Fourth", correct_answer="A", explanation="VERIFIED SOLUTION") | changes)
        QuestionExam.objects.create(question=question, exam=exam or self.exam)
        return publish_question(mark_reviewed(question)) if published else question

    def session(self, **changes):
        return start_session(self.user, exam=self.exam, subject=self.subject, token=changes.pop("token", uuid4()), **changes)

    def session_url(self, session):
        return reverse("practice:session", args=[session.pk])

    def configure_url(self):
        return reverse("practice:configure", args=[self.authority.slug, self.exam.slug, self.subject.slug])


class PracticeServiceTests(PracticeFixture):
    def test_completion_failure_rolls_back_answer_and_feedback(self):
        self.question()
        session = self.session()
        row = session.questions.get()
        with patch.object(PracticeSession, "save", side_effect=ValidationError("Completion write failed")):
            with self.assertRaises(ValidationError):
                submit_answer(self.user, session.pk, row.pk, "A")
        row.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(row.selected_answer, "")
        self.assertIsNone(row.is_correct)
        self.assertEqual(session.status, "in_progress")

    def test_eligibility_filters_exam_subject_topic_and_drafts(self):
        good = self.question()
        self.question(exam=self.other_exam)
        self.question(published=False)
        self.question(subject=self.other_subject)
        no_topic = self.question(topic=None)
        self.assertEqual(eligible_question_ids(self.exam.pk, subject_id=self.subject.pk), {good.pk, no_topic.pk})
        self.assertEqual(eligible_question_ids(self.exam.pk, subject_id=self.subject.pk, topic_id=self.topic.pk), {good.pk})
        self.assertEqual(self.session(topic=self.topic).questions.get().question_id, good.pk)

    def test_incomplete_options_and_inactive_exam_excluded(self):
        question = self.question()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE questions_questiontranslation SET option_a = '   ' WHERE revision_id = %s", [question.published_revision_id])
        self.assertEqual(eligible_question_ids(self.exam.pk), set())
        with self.assertRaises(ValidationError):
            self.session()
        self.assertFalse(PracticeSession.objects.exists())
        self.exam.is_active = False
        self.exam.save()
        self.assertEqual(eligible_question_ids(self.exam.pk), set())

    def test_available_count_order_and_unique_master_questions(self):
        self.question()
        self.question()
        self.question()
        session = self.session()
        rows = list(session.questions.all())
        self.assertEqual(len({row.question_id for row in rows}), 3)
        self.assertEqual([row.display_order for row in rows], [1, 2, 3])
        self.assertEqual(session.configuration["total_questions"], 3)
        self.assertEqual(session.status, "in_progress")
        self.assertIsNone(session.completed_at)

    def test_numeric_count_and_configuration_options(self):
        for _ in range(10):
            self.question()
        self.assertEqual(self.session(count="10").questions.count(), 10)
        with self.assertRaises(ValidationError):
            self.session(count="20")
        with self.assertRaises(ValidationError):
            self.session(count="5")
        form = PracticeStartForm(topic_ids=[self.topic.pk], available_count=50)
        self.assertEqual([value for value, label in form.fields["count"].choices], ["10", "20", "30", "50", "available"])

    def test_duplicate_start_is_idempotent_and_context_is_checked(self):
        self.question()
        token = uuid4()
        first = self.session(token=token)
        second = self.session(token=token)
        self.assertEqual(first.pk, second.pk)
        with self.assertRaises(ValidationError):
            self.session(token=token, topic=self.topic)
        self.assertEqual(PracticeSession.objects.count(), 1)
        submit_answer(self.user, first.pk, first.questions.get().pk, "A")
        self.assertEqual(self.session(token=token).pk, first.pk)

    def test_empty_pool_and_wrong_topic_rejected(self):
        with self.assertRaises(ValidationError):
            self.session()
        self.question()
        with self.assertRaises(ValidationError):
            self.session(topic=self.other_topic)
        self.assertFalse(PracticeSession.objects.exists())

    def test_creation_failure_rolls_back_session_and_rows(self):
        self.question()
        original = PracticeQuestion.save
        def fail_after_write(row, *args, **kwargs):
            original(row, *args, **kwargs)
            raise ValidationError("Injected failure")
        with patch.object(PracticeQuestion, "save", fail_after_write):
            with self.assertRaises(ValidationError):
                self.session()
        self.assertFalse(PracticeSession.objects.exists())
        self.assertFalse(PracticeQuestion.objects.exists())

    def test_answer_feedback_locks_and_is_idempotent(self):
        self.question()
        session = self.session()
        row = session.questions.get()
        result = submit_answer(self.user, session.pk, row.pk, "A")
        self.assertTrue(result.is_correct)
        answered_at = result.answered_at
        self.assertEqual(submit_answer(self.user, session.pk, row.pk, "A").answered_at, answered_at)
        with self.assertRaises(ValidationError):
            submit_answer(self.user, session.pk, row.pk, "B")
        row.refresh_from_db()
        self.assertEqual(row.selected_answer, "A")
        session.refresh_from_db()
        self.assertEqual(session.status, "completed")

    def test_progress_accuracy_and_completion(self):
        for _ in range(3):
            self.question()
        session = self.session()
        rows = list(session.questions.all())
        submit_answer(self.user, session.pk, rows[0].pk, "A")
        submit_answer(self.user, session.pk, rows[1].pk, "B")
        state = progress(session.questions.all())
        self.assertEqual((state["answered"], state["correct"], state["incorrect"], state["remaining"]), (2, 1, 1, 1))
        self.assertEqual(state["accuracy"], Decimal("50.00"))
        self.assertEqual(state["percent"], Decimal("66.67"))
        submit_answer(self.user, session.pk, rows[2].pk, "A")
        session.refresh_from_db()
        self.assertEqual(session.status, "completed")
        self.assertIsNotNone(session.completed_at)

    def test_abandon_is_idempotent_and_blocks_new_answers(self):
        self.question()
        session = self.session()
        first = abandon_session(self.user, session.pk)
        self.assertEqual(first.status, "abandoned")
        self.assertEqual(abandon_session(self.user, session.pk).completed_at, first.completed_at)
        with self.assertRaises(ValidationError):
            submit_answer(self.user, session.pk, session.questions.get().pk, "A")

    def test_revision_and_classification_snapshots_survive_edits(self):
        question = self.question()
        session = self.session(topic=self.topic)
        row = session.questions.get()
        original = row.question_revision_id
        create_revision(question, language="en", question_text="Later version", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="D", explanation="New explanation")
        publish_question(mark_reviewed(question))
        self.topic.name = "Changed topic"
        self.topic.save()
        # Renames preserve history; cross-subject moves now violate taxonomy integrity.
        self.topic.subject = self.other_subject
        with self.assertRaises(ValidationError):
            self.topic.save()
        self.topic.refresh_from_db()
        self.assertTrue(submit_answer(self.user, session.pk, row.pk, "A").is_correct)
        row.refresh_from_db()
        self.assertEqual(row.question_revision_id, original)
        self.assertEqual(performance([row], "topic")[0]["name"], "Arithmetic")

    def test_bad_answer_and_foreign_question_rejected(self):
        self.question()
        session = self.session()
        other = start_session(self.other_user, exam=self.exam, subject=self.subject, token=uuid4())
        with self.assertRaises(Http404):
            submit_answer(self.user, session.pk, other.questions.get().pk, "A")
        for value in (None, "", "E", "a"):
            with self.assertRaises(ValidationError):
                submit_answer(self.user, session.pk, session.questions.get().pk, value)

    def test_model_and_database_integrity(self):
        self.question()
        session = self.session()
        row = session.questions.get()
        with self.assertRaises(ValidationError):
            session.save()
        with self.assertRaises(ValidationError):
            PracticeQuestion.objects.all().update(selected_answer="B")
        with self.assertRaises(ValidationError):
            row.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE practice_practicequestion SET selected_answer = 'A' WHERE id = %s", [row.pk])
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO practice_practicequestion (session_id, question_id, question_revision_id, display_order, classification, selected_answer, is_correct, answered_at) SELECT session_id, question_id, question_revision_id, 2, classification, selected_answer, is_correct, answered_at FROM practice_practicequestion WHERE id = %s", [row.pk])

    def test_mock_and_previous_year_relationships_remain_separate(self):
        from mock_tests.models import ExamPattern, ExamPatternSection, MockAttempt
        from mock_tests.services import activate_pattern, start_attempt
        from previous_year.models import PaperQuestion, PreviousYearPaper
        question = self.question()
        paper = PreviousYearPaper.objects.create(exam=self.exam, year=2019, paper_name="Original")
        paper_row = PaperQuestion.objects.create(paper=paper, question_revision=question.published_revision, question_number="40", display_order=1)
        pattern = ExamPattern.objects.create(exam=self.exam, name="Mock", total_questions=1, duration_minutes=30, total_marks=1)
        ExamPatternSection.objects.create(pattern=pattern, name="Section", question_count=1, display_order=1, language_mode="en")
        activate_pattern(pattern)
        attempt = start_attempt(self.user, pattern)
        session = self.session()
        submit_answer(self.user, session.pk, session.questions.get().pk, "A")
        self.assertEqual(attempt.questions.get().selected_answer, "")
        self.assertEqual(MockAttempt.objects.count(), 1)
        paper_row.refresh_from_db()
        self.assertEqual(paper_row.question_revision_id, question.published_revision_id)


class PracticeViewTests(PracticeFixture):
    def test_embedded_bilingual_options_submit_and_lock(self):
        question = self.question()
        add_translation(question, language="bn", question_text="Bengali version", option_a="BN first", option_b="BN second", option_c="BN third", option_d="BN fourth", explanation="BN feedback")
        publish_question(mark_reviewed(question))
        session = self.session()
        self.client.force_login(self.user)
        response = self.client.get(self.session_url(session))
        self.assertContains(response, 'class="embedded-option"', count=8)
        self.assertContains(response, 'name="answer"', count=8)
        self.assertContains(response, 'class="embedded-option-text"')
        self.assertNotContains(response, 'Your answer for question')
        self.assertNotContains(response, 'BN feedback')
        row = session.questions.get()
        self.client.post(reverse("practice:answer", args=[session.pk, row.pk]), {"answer": "B"})
        row.refresh_from_db()
        self.assertEqual(row.selected_answer, "B")
        locked = self.client.get(self.session_url(session))
        self.assertNotContains(locked, 'class="embedded-option"')
        self.assertContains(locked, 'BN feedback')

    def test_bengali_only_feedback_and_single_translation_layout(self):
        self.question(language="bn", question_text="শুধু বাংলা প্রশ্ন", option_a="এক", option_b="দুই", option_c="তিন", option_d="চার", correct_answer="B")
        session = self.session()
        self.client.force_login(self.user)
        response = self.client.get(self.session_url(session))
        self.assertContains(response, "শুধু বাংলা প্রশ্ন")
        self.assertContains(response, 'class="question-content translation-panel"', count=1)
        self.assertNotContains(response, 'aria-label="English version"')
        row = session.questions.get()
        self.client.post(reverse("practice:answer", args=[session.pk, row.pk]), {"answer": "B"})
        self.assertContains(self.client.get(self.session_url(session)), "Correct answer: B")

    def test_navigation_eligible_subjects_topics_and_empty_state(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("practice:index")), "No eligible practice questions")
        self.question()
        self.question(subject=self.other_subject, published=False)
        for name, args, expected in (("index", [], "Authority"), ("exams", [self.authority.slug], "Exam"),
            ("subjects", [self.authority.slug, self.exam.slug], "Mathematics"),
            ("configure", [self.authority.slug, self.exam.slug, self.subject.slug], "Continue with this subject")):
            response = self.client.get(reverse(f"practice:{name}", args=args))
            self.assertContains(response, expected)
            self.assertNotContains(response, "Ancient")
        subjects_url = reverse("practice:subjects", args=[self.authority.slug, self.exam.slug])
        self.assertNotContains(self.client.get(subjects_url), "History")

    def test_start_get_does_not_create_and_repeated_post_resumes(self):
        self.question()
        self.client.force_login(self.user)
        response = self.client.get(self.configure_url())
        self.assertFalse(PracticeSession.objects.exists())
        difficulty_url = reverse("practice:difficulty", args=[self.authority.slug, self.exam.slug, self.subject.slug])
        response = self.client.get(difficulty_url)
        token = response.context["form"]["token"].value()
        data = {"token": token, "difficulty": "level:"}
        first = self.client.post(difficulty_url, data)
        session = PracticeSession.objects.get()
        self.assertRedirects(first, self.session_url(session))
        self.assertRedirects(self.client.post(difficulty_url, data), self.session_url(session))
        self.assertEqual(PracticeSession.objects.count(), 1)

    def test_one_question_no_solution_until_submission_then_locked_feedback(self):
        self.question(question_text="First unique stem")
        self.question(question_text="Second unique stem")
        session = self.session()
        rows = list(session.questions.select_related("question_revision"))
        self.client.force_login(self.user)
        response = self.client.get(self.session_url(session))
        self.assertContains(response, rows[0].question_revision.question_text)
        self.assertNotContains(response, rows[1].question_revision.question_text)
        self.assertNotContains(response, "VERIFIED SOLUTION")
        self.assertNotContains(response, "Correct answer:")
        url = reverse("practice:answer", args=[session.pk, rows[0].pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {"answer": "B"}).status_code, 302)
        feedback = self.client.get(self.session_url(session), {"question": 1})
        self.assertContains(feedback, 'data-feedback-correct="false"')
        self.assertContains(feedback, "Correct answer: A")
        self.assertContains(feedback, "VERIFIED SOLUTION")
        self.assertNotContains(feedback, 'type="radio"')
        self.assertEqual(self.client.post(url, {"answer": "A"}).status_code, 400)
        self.assertContains(self.client.get(self.session_url(session)), rows[1].question_revision.question_text)

    def test_skip_pause_resume_and_completion_summary(self):
        self.question()
        self.question()
        session = self.session()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.session_url(session), {"question": 2}).status_code, 200)
        self.assertFalse(session.questions.exclude(selected_answer="").exists())
        self.assertContains(self.client.get(reverse("practice:index")), self.session_url(session))
        self.assertContains(self.client.get(self.session_url(session)), "Question 1 of 2")
        for row in session.questions.all():
            self.client.post(reverse("practice:answer", args=[session.pk, row.pk]), {"answer": "A"})
        summary = self.client.get(reverse("practice:summary", args=[session.pk]))
        self.assertContains(summary, "Completed")
        self.assertContains(summary, "100.00%")
        self.assertContains(summary, "Arithmetic")
        self.assertContains(summary, "Mathematics")

    def test_bilingual_counts_once_and_missing_explanation(self):
        question = self.question(language="bn", question_text="????? ??????", explanation="")
        add_translation(question, language="en", question_text="English translation", option_a="A", option_b="B", option_c="C", option_d="D", explanation="")
        publish_question(mark_reviewed(question))
        session = self.session()
        self.assertEqual(session.questions.count(), 1)
        self.client.force_login(self.user)
        page = self.client.get(self.session_url(session))
        self.assertContains(page, "????? ??????")
        self.assertLess(page.content.index(b'lang="en"'), page.content.index(b'lang="bn"'))
        row = session.questions.get()
        self.client.post(reverse("practice:answer", args=[session.pk, row.pk]), {"answer": "A"})
        self.assertContains(self.client.get(self.session_url(session)), "Explanation unavailable.")

    def test_ownership_auth_csrf_invalid_positions_and_topics(self):
        self.question()
        session = self.session()
        self.assertEqual(self.client.get(self.session_url(session)).status_code, 302)
        self.client.force_login(self.other_user)
        for name in ("session", "summary", "abandon"):
            self.assertEqual(self.client.get(reverse(f"practice:{name}", args=[session.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("practice:answer", args=[session.pk, session.questions.get().pk]), {"answer": "A"}).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.session_url(session), {"question": "invalid"}).status_code, 404)
        self.assertEqual(self.client.get(self.session_url(session), {"question": 999}).status_code, 404)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(self.configure_url(), {"count": "available", "token": uuid4()}).status_code, 403)
        self.assertEqual(strict.post(reverse("practice:answer", args=[session.pk, session.questions.get().pk]), {"answer": "A"}).status_code, 403)
        self.assertEqual(strict.post(reverse("practice:abandon", args=[session.pk])).status_code, 403)
        self.assertEqual(self.client.post(self.configure_url(), {"count": "available", "token": uuid4(), "topic": self.other_topic.pk}).status_code, 400)

    def test_abandoned_unanswered_question_never_reveals_solution(self):
        self.question()
        session = self.session()
        self.client.force_login(self.user)
        url = reverse("practice:abandon", args=[session.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 302)
        response = self.client.get(self.session_url(session))
        self.assertNotContains(response, "VERIFIED SOLUTION")
        self.assertNotContains(response, "Correct answer:")
        self.assertNotContains(response, 'type="radio"')


class ConcurrentPracticeTests(TransactionTestCase):
    def setUp(self):
        PracticeFixture.setUpTestData.__func__(type(self))
        PracticeFixture.question(self)

    def run_concurrent(self, functions):
        barrier = Barrier(2)
        def run(function):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return function()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(run, functions))

    def test_duplicate_concurrent_starts_create_one_session(self):
        token = uuid4()
        def start():
            return start_session(self.user, exam=self.exam, subject=self.subject, token=token).pk
        result = self.run_concurrent([start, start])
        self.assertEqual(result[0], result[1])
        self.assertEqual(PracticeSession.objects.count(), 1)
        self.assertEqual(PracticeQuestion.objects.count(), 1)

    def test_different_concurrent_answers_lock_first_response(self):
        session = start_session(self.user, exam=self.exam, subject=self.subject, token=uuid4())
        row = session.questions.get()
        def answer(value):
            try:
                submit_answer(self.user, session.pk, row.pk, value)
                return "saved"
            except ValidationError:
                return "locked"
        results = self.run_concurrent([lambda: answer("A"), lambda: answer("B")])
        self.assertEqual(sorted(results), ["locked", "saved"])
        row.refresh_from_db()
        self.assertEqual(row.is_correct, row.selected_answer == "A")
        session.refresh_from_db()
        self.assertEqual(session.status, "completed")
