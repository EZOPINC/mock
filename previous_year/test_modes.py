from django.test import Client
from django.urls import reverse

from questions.services import add_translation, create_revision, mark_reviewed, publish_question
from .models import PaperQuestion, PreviousYearPaper
from .services import publish_paper, unpublish_paper
from .tests import PaperFixture


class PaperModesTests(PaperFixture):
    def test_options_embedded_in_paper_form_and_removed_after_feedback(self):
        response = self.client.get(self.detail_url(), {"mode": "practice"})
        self.assertContains(response, 'class="embedded-option"', count=8)
        self.assertNotContains(response, 'Your answer for question')
        feedback = self.client.post(self.answer_url(), {"answer": "B"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(feedback, 'Correct.')
        self.assertNotContains(feedback, 'class="embedded-option"')

    def test_mode_and_subject_filter_survive_navigation(self):
        response = self.client.get(self.detail_url(), {"mode": "practice", "subject": self.subject.pk})
        self.assertContains(response, 'name="mode" value="practice"')
        self.assertContains(response, f'mode=practice&amp;subject={self.subject.pk}')
        self.assertNotContains(response, "FIRST VERIFIED EXPLANATION")

    def test_feedback_uses_historical_paper_revision_and_rechecks_publication(self):
        create_revision(self.first, language="en", question_text="New revision", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="A", explanation="NEW EXPLANATION")
        publish_question(mark_reviewed(self.first))
        response = self.client.post(self.answer_url(), {"answer": "B"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(response, "Correct.")
        self.assertContains(response, "FIRST VERIFIED EXPLANATION")
        self.assertNotContains(response, "NEW EXPLANATION")
        self.authority.is_active = False
        self.authority.save()
        self.assertEqual(self.client.post(self.answer_url(), {"answer": "B"}).status_code, 404)

    def setUp(self):
        super().setUp()
        self.first = self.question(question_text="First pinned question", explanation="FIRST VERIFIED EXPLANATION")
        self.second = self.question(question_text="Second pinned question", explanation="SECOND VERIFIED EXPLANATION")
        self.first_row = self.row(question=self.first)
        self.second_row = PaperQuestion.objects.create(paper=self.paper, question_revision=self.second.published_revision, question_number="40", display_order=2)
        publish_paper(self.paper)

    def year_url(self):
        return reverse("previous_year:paper_year", args=[self.authority.slug, self.exam.slug, self.paper.year])

    def answer_url(self, row=None):
        row = row or self.first_row
        return reverse("previous_year:paper_answer", args=[self.authority.slug, self.exam.slug, self.paper.year, self.paper.pk, row.pk]) + "?mode=practice"

    def test_year_offers_modes_and_preserves_paper_selection(self):
        response = self.client.get(self.year_url(), {"paper": self.paper.pk})
        self.assertContains(response, "Direct Answers")
        self.assertContains(response, "Practice Paper")
        self.assertContains(response, f"paper={self.paper.pk}&amp;mode=practice")
        for mode in ("direct", "practice"):
            self.assertRedirects(self.client.get(self.year_url(), {"mode": mode}), self.detail_url() + f"?mode={mode}")

    def test_direct_all_questions_highlights_and_open_solutions(self):
        response = self.client.get(self.detail_url(), {"mode": "direct"})
        self.assertContains(response, "FIRST VERIFIED EXPLANATION")
        self.assertContains(response, "SECOND VERIFIED EXPLANATION")
        self.assertContains(response, 'class="correct-option"', count=2)
        self.assertContains(response, '<details class="solution" open>', count=2)
        self.assertLess(response.content.index(b"First pinned question"), response.content.index(b"Second pinned question"))
        self.assertNotContains(response, 'class="paper-practice-form')

    def test_practice_has_all_questions_but_no_answer_keys(self):
        response = self.client.get(self.detail_url(), {"mode": "practice"})
        for stem in ("First pinned question", "Second pinned question", "Question 40"):
            self.assertContains(response, stem)
        for secret in ("FIRST VERIFIED EXPLANATION", "SECOND VERIFIED EXPLANATION", "Correct answer:", 'class="correct-option"'):
            self.assertNotContains(response, secret)
        self.assertContains(response, 'type="radio"', count=8)
        self.assertContains(response, 'name="mode" value="practice"')
        self.assertContains(response, "paper-practice.js")

    def test_selection_reveals_only_selected_question_with_correct_feedback(self):
        for answer, feedback in (("A", "Incorrect."), ("B", "Correct.")):
            response = self.client.post(self.answer_url(), {"answer": answer}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertContains(response, feedback)
            if answer == "A":
                self.assertContains(response, 'ui-feedback-incorrect')
                self.assertContains(response, 'data-incorrect-answer="A"')
            else:
                self.assertNotContains(response, 'ui-feedback-incorrect')
                self.assertNotContains(response, 'data-incorrect-answer=')
            self.assertContains(response, "Correct answer: B")
            self.assertContains(response, "FIRST VERIFIED EXPLANATION")
            self.assertNotContains(response, "SECOND VERIFIED EXPLANATION")
            self.assertContains(response, 'class="correct-option"')
        self.first_row.refresh_from_db()
        self.assertEqual(self.first_row.question_revision_id, self.first.published_revision_id)

    def test_no_javascript_post_returns_paper_with_one_feedback(self):
        response = self.client.post(self.answer_url(), {"answer": "B"})
        self.assertContains(response, "FIRST VERIFIED EXPLANATION")
        self.assertNotContains(response, "SECOND VERIFIED EXPLANATION")
        self.assertContains(response, "Question 40")
        self.assertContains(response, 'type="radio"', count=4)

    def test_invalid_answers_csrf_and_methods(self):
        self.assertEqual(self.client.get(self.answer_url()).status_code, 405)
        for value in ("", "Z", "b"):
            response = self.client.post(self.answer_url(), {"answer": value}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(response.status_code, 400)
            self.assertNotContains(response, "FIRST VERIFIED EXPLANATION", status_code=400)
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post(self.answer_url(), {"answer": "B"}).status_code, 403)
        strict.get(self.detail_url(), {"mode": "practice"})
        self.assertEqual(strict.post(self.answer_url(), {"answer": "B"}, HTTP_X_CSRFTOKEN=strict.cookies["csrftoken"].value).status_code, 200)

    def test_draft_inactive_foreign_rows_and_invalid_modes_are_hidden(self):
        foreign = PreviousYearPaper.objects.create(exam=self.exam, year=2022, paper_name="Other")
        row = self.row(paper=foreign)
        self.assertEqual(self.client.post(self.answer_url(row), {"answer": "B"}).status_code, 404)
        for url in (self.year_url(), self.detail_url()):
            self.assertEqual(self.client.get(url, {"mode": "invalid"}).status_code, 404)
        unpublish_paper(self.paper)
        self.assertEqual(self.client.post(self.answer_url(), {"answer": "B"}).status_code, 404)

    def test_bilingual_feedback_and_missing_explanation(self):
        unpublish_paper(self.paper)
        question = self.question(language="bn", question_text="????? ??????", explanation="")
        add_translation(question, language="en", question_text="English question", option_a="A", option_b="B", option_c="C", option_d="D", explanation="")
        question = publish_question(mark_reviewed(question))
        row = PaperQuestion.objects.create(paper=self.paper, question_revision=question.published_revision, question_number="99", display_order=3)
        publish_paper(self.paper)
        response = self.client.post(self.answer_url(row), {"answer": "A"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(response, "????? ??????")
        self.assertLess(response.content.index(b'lang="en"'), response.content.index(b'lang="bn"'))
        self.assertContains(response, "Explanation unavailable.")
