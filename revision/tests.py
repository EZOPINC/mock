from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse

from mock_tests.test_execution import ExecutionFixture
from practice.services import start_session
from practice.tests import PracticeFixture
from previous_year.models import PaperQuestion, PreviousYearPaper
from previous_year.services import publish_paper
from questions.models import Question
from .models import SavedQuestion
from .services import attach_saved_state


class BookmarkEndpointTests(PracticeFixture):
    def setUp(self):
        self.question_record = self.question()
        self.save_url = reverse("revision:save", args=[self.question_record.pk])
        self.unsave_url = reverse("revision:unsave", args=[self.question_record.pk])
        self.client.force_login(self.user)

    def post(self, url, **data):
        return self.client.post(url, data, HTTP_ACCEPT="application/json")

    def test_authentication_post_only_and_csrf(self):
        for url in (self.save_url, self.unsave_url):
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(self.client.put(url).status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(self.save_url, HTTP_ACCEPT="application/json").status_code, 403)
        self.assertEqual(strict.post(self.unsave_url, HTTP_ACCEPT="application/json").status_code, 403)
        session = self.session()
        strict.get(self.session_url(session))
        csrf = strict.cookies["csrftoken"].value
        self.assertEqual(strict.post(self.save_url, HTTP_X_CSRFTOKEN=csrf, HTTP_ACCEPT="application/json").status_code, 200)
        self.client.logout()
        self.assertEqual(self.post(self.unsave_url).status_code, 401)
        self.assertEqual(SavedQuestion.objects.count(), 1)
        response = self.client.post(self.save_url, {"next": "/practice/?question=2#practice-question"})
        self.assertEqual(parse_qs(urlsplit(response.url).query)["next"], ["/practice/?question=2#practice-question"])

    def test_explicit_save_unsave_are_idempotent_and_minimal(self):
        self.assertEqual(self.post(self.save_url).json(), {"question_id": self.question_record.pk, "saved": True})
        first = SavedQuestion.objects.get()
        self.post(self.save_url)
        self.assertEqual(SavedQuestion.objects.count(), 1)
        self.assertEqual(SavedQuestion.objects.get().saved_at, first.saved_at)
        self.assertEqual(self.post(self.unsave_url).json(), {"question_id": self.question_record.pk, "saved": False})
        self.assertEqual(self.post(self.unsave_url).status_code, 200)
        self.assertFalse(SavedQuestion.objects.exists())

    def test_database_unique_constraint(self):
        SavedQuestion.objects.create(user=self.user, question=self.question_record)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SavedQuestion.objects.create(user=self.user, question=self.question_record)

    def test_user_input_cannot_change_another_users_bookmark(self):
        other = SavedQuestion.objects.create(user=self.other_user, question=self.question_record)
        self.post(self.save_url, user=self.other_user.pk, user_id=self.other_user.pk)
        self.assertEqual(SavedQuestion.objects.count(), 2)
        self.post(self.unsave_url, user=self.other_user.pk)
        self.assertTrue(SavedQuestion.objects.filter(pk=other.pk).exists())
        self.assertFalse(SavedQuestion.objects.filter(user=self.user).exists())

    def test_inaccessible_drafts_and_unknown_ids_cannot_be_saved(self):
        draft = self.question(published=False)
        for pk in (draft.pk, 999999):
            response = self.post(reverse("revision:save", args=[pk]))
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"error": "question_not_found"})
        self.assertFalse(SavedQuestion.objects.exists())

    def test_frozen_practice_question_is_accessible_only_to_its_owner(self):
        session = self.session()
        with transaction.atomic():
            # Simulate subsequent unpublication while preserving frozen history.
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("UPDATE questions_question SET publication_status = 'draft', published_revision_id = NULL WHERE id = %s", [self.question_record.pk])
        self.assertEqual(self.post(self.save_url).status_code, 200)
        self.client.force_login(self.other_user)
        self.assertEqual(self.post(self.save_url).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.post(self.unsave_url).status_code, 200)
        self.assertEqual(self.post(self.unsave_url).status_code, 200)
        self.assertEqual(session.questions.get().question_id, self.question_record.pk)

    def test_redirects_are_local_and_bookmark_state_is_private(self):
        response = self.client.post(self.save_url, {"next": "https://evil.example/"})
        self.assertEqual(response.url, reverse("accounts:learning_space"))
        self.assertIn("no-store", response.headers["Cache-Control"])
        target = "/practice/?question=2#practice-question"
        self.assertEqual(self.client.post(self.unsave_url, {"next": target}).url, target)

    def test_batched_saved_state_is_per_user(self):
        session = self.session()
        rows = list(session.questions.all())
        SavedQuestion.objects.create(user=self.user, question=self.question_record)
        with self.assertNumQueries(1):
            attach_saved_state(self.user.pk, rows)
        self.assertTrue(rows[0].is_saved)
        attach_saved_state(self.other_user.pk, rows)
        self.assertFalse(rows[0].is_saved)
        with self.assertNumQueries(0):
            attach_saved_state(None, rows)


class CrossModuleBookmarkTests(ExecutionFixture):
    def question(self, **kwargs):
        from questions.services import create_revision, mark_reviewed, publish_question
        question = super().question(**kwargs)
        create_revision(question, language="en", question_text="Revision source question", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="A", explanation="PRIVATE EXPLANATION SENTINEL")
        return publish_question(mark_reviewed(question))

    def setUp(self):
        super().setUp()
        self.attempt = self.ready_attempt()
        self.row = self.attempt.questions.get()
        self.question_record = self.row.question
        self.paper = PreviousYearPaper.objects.create(exam=self.exam, year=2025, paper_name="Revision source")
        self.paper_row = PaperQuestion.objects.create(paper=self.paper, question_revision=self.row.question_revision,
                                                    question_number="1", display_order=1)
        publish_paper(self.paper)
        self.practice = start_session(self.user, exam=self.exam, subject=self.subject, token=uuid4())
        self.paper_url = reverse("previous_year:paper_detail", args=[self.exam.authority.slug, self.exam.slug, 2025, self.paper.pk])
        self.practice_url = reverse("practice:session", args=[self.practice.pk])
        self.bookmark_url = reverse("revision:save", args=[self.question_record.pk])
        self.remove_url = reverse("revision:unsave", args=[self.question_record.pk])
        self.client.force_login(self.user)

    def test_one_master_bookmark_shared_across_all_three_interfaces(self):
        for url in (self.paper_url, self.detail_url(self.attempt), self.practice_url):
            self.assertContains(self.client.get(url), "Save for revision")
        self.client.post(self.bookmark_url, HTTP_ACCEPT="application/json")
        for url in (self.paper_url, self.detail_url(self.attempt), self.practice_url):
            response = self.client.get(url)
            self.assertContains(response, "Saved for revision")
            self.assertContains(response, self.remove_url)
            self.assertContains(response, 'aria-pressed="true"')
        saved = SavedQuestion.objects.get()
        self.assertEqual(saved.question_id, self.question_record.pk)
        self.client.post(self.remove_url, HTTP_ACCEPT="application/json")
        self.assertContains(self.client.get(self.paper_url), "Save for revision")
        self.assertFalse(SavedQuestion.objects.exists())

    def test_guest_login_preserves_paper_mode_filter_and_question_anchor(self):
        self.client.logout()
        url = self.paper_url + f"?mode=practice&subject={self.subject.pk}"
        response = self.client.get(url)
        self.assertContains(response, "Sign in to save for revision")
        from html.parser import HTMLParser
        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links = []
            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    self.links.append(dict(attrs).get("href", ""))
        parser = Links()
        parser.feed(response.content.decode())
        target = url + f"#question-{self.paper_row.pk}"
        self.assertTrue(any(parse_qs(urlsplit(link).query).get("next") == [target] for link in parser.links))
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_bookmark_does_not_modify_attempt_revision_answers_or_scoring(self):
        self.client.get(self.detail_url(self.attempt))
        before_attempt = type(self.attempt).objects.filter(pk=self.attempt.pk).values().get()
        before_row = type(self.row).objects.filter(pk=self.row.pk).values().get()
        before_question = Question.objects.filter(pk=self.question_record.pk).values().get()
        for url in (self.bookmark_url, self.bookmark_url, self.remove_url):
            response = self.client.post(url, HTTP_ACCEPT="application/json")
            self.assertEqual(set(response.json()), {"question_id", "saved"})
        self.assertEqual(before_attempt, type(self.attempt).objects.filter(pk=self.attempt.pk).values().get())
        self.assertEqual(before_row, type(self.row).objects.filter(pk=self.row.pk).values().get())
        self.assertEqual(before_question, Question.objects.filter(pk=self.question_record.pk).values().get())
        response = self.client.get(self.detail_url(self.attempt))
        self.assertNotContains(response, self.row.question_revision.explanation)
        self.assertNotContains(response, "Correct answer:")
        # Existing autosave still accepts the original version/token protocol.
        import json
        self.attempt.refresh_from_db()
        response = self.client.post(self.save_url(self.attempt), json.dumps(self.payload(self.attempt)), content_type="application/json")
        self.assertTrue(response.json()["ok"])
