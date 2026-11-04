from django.template.loader import render_to_string
from django.urls import reverse

from questions.models import QuestionRevision, QuestionTranslation
from questions.services import add_translation, mark_reviewed, publish_question
from .services import publish_paper
from .tests import PaperFixture


class PublicPaperSolutionsTests(PaperFixture):
    def test_missing_all_translation_content_hides_paper_and_exam_entry(self):
        row = self.row()
        publish_paper(self.paper)
        # Simulate incomplete legacy data outside the guarded application APIs.
        QuestionTranslation._base_manager.filter(revision=row.question_revision).delete()
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)
        response = self.client.get(reverse("previous_year:index"))
        self.assertContains(response, "No published papers are available yet.")

    def test_unapproved_revision_is_never_public_even_if_paper_flag_is_set(self):
        row = self.row()
        publish_paper(self.paper)
        QuestionRevision._base_manager.filter(pk=row.question_revision_id).update(published_at=None)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)
        self.assertNotContains(self.client.get(reverse("previous_year:index")), self.exam.name)

    def test_missing_optional_language_uses_available_single_column_content(self):
        question = self.question(question_text="English survives")
        add_translation(question, language="bn", question_text="বাংলা", option_a="এক", option_b="দুই", option_c="তিন", option_d="চার")
        question = publish_question(mark_reviewed(question))
        self.row(question=question)
        publish_paper(self.paper)
        QuestionTranslation._base_manager.filter(revision=question.published_revision, language="bn").delete()
        response = self.client.get(self.detail_url())
        self.assertContains(response, "English survives")
        self.assertEqual(response.content.count(b'class="question-content translation-panel"'), 1)
        self.assertNotContains(response, 'lang="bn"')

    def test_unverified_solution_has_no_answer_control_or_answer_key(self):
        question = self.question(published=False)
        html = render_to_string("questions/translations.html", {
            "revision": question.current_revision, "show_solutions": True,
            "hide_answers": True, "verified_only": True,
        })
        self.assertIn("Verified solution unavailable.", html)
        self.assertNotIn("Show Answer/Explanation", html)
        self.assertNotIn("Correct answer:", html)

    def test_page_title_and_breadcrumbs_follow_public_hierarchy(self):
        self.row()
        publish_paper(self.paper)
        response = self.client.get(self.detail_url())
        html = response.content.decode()
        title = html.split("<title>", 1)[1].split("</title>", 1)[0]
        self.assertIn(self.exam.name, title)
        self.assertIn(self.paper.paper_name, title)
        self.assertIn(str(self.paper.year), title)
        crumb = html.split('aria-label="Breadcrumb"', 1)[1].split("</nav>", 1)[0]
        links = [reverse("previous_year:index"),
                 reverse("previous_year:paper_list", args=[self.authority.slug, self.exam.slug]),
                 reverse("previous_year:paper_year", args=[self.authority.slug, self.exam.slug, self.paper.year])]
        positions = [crumb.index(f'href="{link}"') for link in links]
        self.assertEqual(positions, sorted(positions))

    def test_unverified_answers_are_not_highlighted_even_without_disclosure_mode(self):
        question = self.question(published=False)
        html = render_to_string("questions/translations.html", {
            "revision": question.current_revision, "show_solutions": True,
            "verified_only": True, "hide_answers": False,
        })
        self.assertNotIn('class="correct-option"', html)
        self.assertNotIn("Correct answer:", html)
        self.assertIn("Verified solution unavailable.", html)

    def test_paper_subject_drift_excludes_invalid_association(self):
        from exams.models import Subject
        row = self.row()
        self.paper.subject = self.subject
        self.paper.save()
        publish_paper(self.paper)
        other = Subject.objects.create(name="Other subject", code="OTHER", slug="other")
        question = row.question
        question.subject = other
        question.save()
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)
