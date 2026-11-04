from django.urls import reverse

from questions.services import add_translation, mark_reviewed, publish_question
from .models import PaperQuestion, PreviousYearPaper
from .services import publish_paper
from .tests import PaperFixture


class PaperViewerTests(PaperFixture):
    def year_url(self, year=None):
        return reverse("previous_year:paper_year", args=[self.authority.slug, self.exam.slug, year or self.paper.year])

    def test_exam_then_year_then_single_paper_navigation(self):
        self.row()
        publish_paper(self.paper)
        response = self.client.get(reverse("previous_year:index"))
        self.assertContains(response, self.exam.name)
        self.assertContains(response, reverse("previous_year:paper_list", args=[self.authority.slug, self.exam.slug]))
        self.assertNotContains(response, self.other_exam.name)
        response = self.client.get(reverse("previous_year:paper_list", args=[self.authority.slug, self.exam.slug]))
        self.assertContains(response, self.year_url())
        self.assertRedirects(self.client.get(self.year_url()), self.detail_url())

    def test_multiple_papers_offer_scoped_selector_and_stage_session_labels(self):
        question = self.question()
        self.row(question=question)
        publish_paper(self.paper)
        second = PreviousYearPaper.objects.create(exam=self.exam, stage=self.stage, year=2023, paper_name="Second paper", session="Shift II")
        self.row(question=question, paper=second)
        publish_paper(second)
        response = self.client.get(self.year_url())
        self.assertEqual(response.status_code, 200)
        for label in ("Second paper", "Preliminary", "Shift II", 'name="paper"'):
            self.assertContains(response, label)
        self.assertRedirects(self.client.get(self.year_url(), {"paper": second.pk}), self.detail_url(paper=second))
        self.assertContains(self.client.get(self.detail_url()), 'name="paper"')

    def test_invalid_year_or_foreign_paper_is_not_exposed(self):
        self.row()
        publish_paper(self.paper)
        self.assertEqual(self.client.get(self.year_url(2000)).status_code, 404)
        foreign = PreviousYearPaper.objects.create(exam=self.other_exam, year=2023, paper_name="Private foreign paper")
        for value in (foreign.pk, "invalid", "999999"):
            response = self.client.get(self.year_url(), {"paper": value})
            self.assertEqual(response.status_code, 400)
            self.assertNotContains(response, foreign.paper_name, status_code=400)

    def test_draft_papers_do_not_appear_in_exam_year_or_selector(self):
        self.row()
        publish_paper(self.paper)
        PreviousYearPaper.objects.create(exam=self.exam, year=2022, paper_name="Hidden draft")
        for url in (reverse("previous_year:index"), reverse("previous_year:paper_list", args=[self.authority.slug, self.exam.slug]), self.detail_url()):
            self.assertNotContains(self.client.get(url), "Hidden draft")
        self.assertEqual(self.client.get(self.year_url(2022)).status_code, 404)

    def test_english_left_bengali_right_and_original_numbering_order(self):
        question = self.question(language="bn", question_text="বাংলা মূল প্রশ্ন", explanation="মূল ব্যাখ্যা")
        add_translation(question, language="en", question_text="English translation ∑ x²", option_a="First", option_b="Second", option_c="Third", option_d="Fourth", explanation="English solution")
        question = publish_question(mark_reviewed(question))
        PaperQuestion.objects.create(paper=self.paper, question_revision=question.published_revision, question_number="12(b)", display_order=1)
        other = self.question(question_text="Later original question")
        PaperQuestion.objects.create(paper=self.paper, question_revision=other.published_revision, question_number="3(a)", display_order=2)
        publish_paper(self.paper)
        response = self.client.get(self.detail_url())
        html = response.content.decode()
        self.assertLess(html.index("English translation ∑ x²"), html.index("বাংলা মূল প্রশ্ন"))
        self.assertLess(html.index("English translation ∑ x²"), html.index("Later original question"))
        self.assertContains(response, "Question 12(b)")
        self.assertContains(response, "Question 3(a)")
        self.assertContains(response, 'lang="en"')
        self.assertContains(response, 'lang="bn"')

    def test_monolingual_available_version_and_collapsed_answer_control(self):
        self.row(question=self.question(language="bn", question_text="শুধু বাংলা", explanation=""))
        publish_paper(self.paper)
        response = self.client.get(self.detail_url())
        self.assertEqual(response.content.count(b'class="question-content translation-panel"'), 1)
        self.assertContains(response, "Show Answer/Explanation")
        self.assertContains(response, '<details class="solution answer-disclosure">')
        self.assertNotContains(response, 'class="correct-option"')
        self.assertContains(response, "Explanation unavailable.")

    def test_pinned_revision_unchanged_when_new_translation_published(self):
        question = self.question(question_text="Pinned original")
        self.row(question=question)
        publish_paper(self.paper)
        add_translation(question, language="bn", question_text="New Bengali version", option_a="A", option_b="B", option_c="C", option_d="D")
        publish_question(mark_reviewed(question))
        response = self.client.get(self.detail_url())
        self.assertContains(response, "Pinned original")
        self.assertNotContains(response, "New Bengali version")
