from django.urls import reverse

from questions.services import add_translation, mark_reviewed, publish_question
from .models import PaperQuestion, PreviousYearPaper
from .services import publish_paper
from .tests import PaperFixture


class PaperViewerTests(PaperFixture):
    def test_subject_filter_preserves_numbering_order_and_full_summary(self):
        from exams.models import Subject
        other_subject = Subject.objects.create(name="Science", code="SCI", slug="science")
        first = self.question(question_text="First English question")
        self.row(question=first)
        other = self.question(question_text="Hidden science question")
        other.subject = other_subject
        other.save()
        PaperQuestion.objects.create(paper=self.paper, question_revision=other.published_revision, question_number="20", display_order=2)
        last = self.question(question_text="Last English question")
        PaperQuestion.objects.create(paper=self.paper, question_revision=last.published_revision, question_number="40", display_order=3)
        publish_paper(self.paper)
        response = self.client.get(self.detail_url(), {"subject": self.subject.pk})
        self.assertContains(response, "Showing 2 of 3 questions.")
        self.assertContains(response, "Total questions: 3")
        self.assertContains(response, "Question 40")
        self.assertContains(response, "Science: 1")
        self.assertNotContains(response, "Hidden science question")
        self.assertLess(response.content.index(b"First English question"), response.content.index(b"Last English question"))
        self.assertContains(response, "Clear filter")
        self.assertContains(self.client.get(self.detail_url(), {"subject": ""}), "Hidden science question")
        for invalid in ("invalid", "999999"):
            self.assertEqual(self.client.get(self.detail_url(), {"subject": invalid}).status_code, 404)

    def test_stage_and_session_selection_scopes_years_and_papers(self):
        self.row()
        publish_paper(self.paper)
        second = PreviousYearPaper.objects.create(exam=self.exam, stage=self.stage, year=2024, paper_name="Morning", session="Morning")
        third = PreviousYearPaper.objects.create(exam=self.exam, stage=self.stage, year=2024, paper_name="Evening", session="Evening")
        for paper in (second, third):
            self.row(paper=paper)
            publish_paper(paper)
        url = reverse("previous_year:paper_list", args=[self.authority.slug, self.exam.slug])
        response = self.client.get(url)
        self.assertContains(response, "Choose stage")
        response = self.client.get(url, {"stage": self.stage.pk})
        self.assertContains(response, "2024")
        self.assertNotContains(response, "2023")
        response = self.client.get(self.year_url(2024), {"stage": self.stage.pk, "mode": "practice"})
        self.assertContains(response, "Choose session")
        self.assertRedirects(self.client.get(self.year_url(2024), {"stage": self.stage.pk, "session": "Evening", "mode": "practice"}), self.detail_url(paper=third) + "?mode=practice")
        for params in ({"stage": "999999"}, {"stage": self.stage.pk, "session": "Invalid"}):
            self.assertEqual(self.client.get(self.year_url(2024), params).status_code, 404)
        self.assertEqual(self.client.get(self.year_url(2024), {"stage": self.stage.pk, "session": "Evening", "paper": second.pk}).status_code, 400)

    def test_summary_counts_master_questions_not_translations(self):
        question = self.question()
        add_translation(question, language="bn", question_text="Bengali version", option_a="A", option_b="B", option_c="C", option_d="D")
        question = publish_question(mark_reviewed(question))
        self.row(question=question)
        from exams.models import Subject
        other_subject = Subject.objects.create(name="Mathematics", code="MATH", slug="mathematics")
        other = self.question()
        other.subject = other_subject
        other.save()
        PaperQuestion.objects.create(paper=self.paper, question_revision=other.published_revision, question_number="40", display_order=2)
        self.paper.duration_minutes = 90
        self.paper.expected_question_count = 2
        self.paper.save()
        publish_paper(self.paper)
        response = self.client.get(self.detail_url())
        self.assertContains(response, "Total questions: 2")
        self.assertContains(response, "90 minutes")
        self.assertContains(response, "English: 1")
        self.assertContains(response, "Mathematics: 1")

    def test_missing_duration_is_explicit(self):
        self.row()
        publish_paper(self.paper)
        self.assertContains(self.client.get(self.detail_url()), "Duration: Not specified")

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
        self.assertContains(self.client.get(self.year_url()), "Direct Answers")
        self.assertContains(self.client.get(self.year_url()), "Practice Paper")
        self.assertRedirects(self.client.get(self.year_url(), {"mode": "direct"}), self.detail_url() + "?mode=direct")

    def test_multiple_papers_offer_scoped_selector_and_stage_session_labels(self):
        question = self.question()
        self.row(question=question)
        publish_paper(self.paper)
        second = PreviousYearPaper.objects.create(exam=self.exam, stage=self.stage, year=2023, paper_name="Second paper", session="Shift II")
        self.row(question=question, paper=second)
        publish_paper(second)
        response = self.client.get(self.year_url(), {"mode": "practice"})
        self.assertEqual(response.status_code, 200)
        for label in ("Second paper", "Preliminary", "Shift II", 'name="paper"'):
            self.assertContains(response, label)
        self.assertRedirects(self.client.get(self.year_url(), {"paper": second.pk, "mode": "practice"}), self.detail_url(paper=second) + "?mode=practice")
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

    def test_monolingual_direct_answers_are_highlighted_and_open(self):
        self.row(question=self.question(language="bn", question_text="শুধু বাংলা", explanation=""))
        publish_paper(self.paper)
        response = self.client.get(self.detail_url())
        self.assertEqual(response.content.count(b'class="question-content translation-panel"'), 1)
        self.assertContains(response, '<details class="solution" open>')
        self.assertContains(response, 'class="correct-option"')
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
