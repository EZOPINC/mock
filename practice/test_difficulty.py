from uuid import uuid4
from django.core.exceptions import ValidationError
from django.urls import reverse
from exams.models import Module, Topic
from questions.services import add_translation, create_revision, mark_reviewed, publish_question
from .models import PracticeSession
from .tests import PracticeFixture


class DifficultyFlowTests(PracticeFixture):
    def test_selected_language_filters_pool_and_rendered_versions(self):
        english = self.question()
        bengali = self.question(language="bn")
        bilingual = self.question(published=False)
        add_translation(bilingual, language="bn", question_text="Bengali edition", option_a="BN A",
                        option_b="BN B", option_c="BN C", option_d="BN D")
        publish_question(mark_reviewed(bilingual))
        expected = {"en": {english.pk, bilingual.pk}, "bn": {bengali.pk, bilingual.pk},
                    "both": {english.pk, bengali.pk, bilingual.pk}}
        for language in ("en", "bn", "both"):
            with self.subTest(language=language):
                session = self.session(language=language)
                self.assertEqual(set(session.questions.values_list("question_id", flat=True)), expected[language])
                row = session.questions.get(question=bilingual)
                response = self.client.get(self.session_url(session) + f"?question={row.display_order}")
                for code in ("en", "bn"):
                    marker = f'lang="{code}" aria-label='
                    if language in (code, "both"):
                        self.assertContains(response, marker)
                    else:
                        self.assertNotContains(response, marker)

    def test_unavailable_or_invalid_language_creates_no_session(self):
        question = self.question()
        # A working translation must not make an English published revision Bengali-eligible.
        add_translation(question, language="bn", question_text="Unpublished Bengali", option_a="A",
                        option_b="B", option_c="C", option_d="D")
        for language in ("bn", "invalid"):
            with self.subTest(language=language), self.assertRaises(ValidationError):
                self.session(language=language)
        self.assertFalse(PracticeSession.objects.exists())

        url = reverse("practice:difficulty", args=[self.authority.slug, self.exam.slug, self.subject.slug])
        response = self.client.post(url, {"token": uuid4(), "difficulty": "level:", "language": "bn"})
        self.assertContains(response, "Insufficient eligible questions", status_code=400)
        self.assertFalse(PracticeSession.objects.exists())

    def test_language_preference_applies_to_question_and_feedback(self):
        question = self.question(published=False)
        add_translation(question, language="bn", question_text="Bengali version", option_a="BN first",
                        option_b="BN second", option_c="BN third", option_d="BN fourth", explanation="BN feedback")
        publish_question(mark_reviewed(question))
        url = reverse("practice:difficulty", args=[self.authority.slug, self.exam.slug, self.subject.slug])
        self.assertEqual(self.client.post(url, {"token": uuid4(), "difficulty": "level:", "language": "invalid"}).status_code, 400)
        self.assertFalse(PracticeSession.objects.exists())
        self.client.post(url, {"token": uuid4(), "difficulty": "level:", "language": "bn"})
        session = PracticeSession.objects.get()
        self.assertEqual(session.configuration["language"], "bn")
        self.client.logout()
        self.client.force_login(self.user)
        response = self.client.get(self.session_url(session))
        self.assertContains(response, "Bengali version")
        self.assertNotContains(response, "Original question")
        row = session.questions.get()
        response = self.client.post(reverse("practice:answer", args=[session.pk, row.pk]), {"answer": "A"}, follow=True)
        self.assertContains(response, "BN feedback")
        self.assertNotContains(response, "VERIFIED SOLUTION")
        self.assertRedirects(self.client.post(url, {"token": session.start_token, "difficulty": "level:", "language": "en"}), self.session_url(session))
        session.refresh_from_db()
        self.assertEqual(session.configuration["language"], "bn")

    def test_subject_links_to_modules_then_difficulty_and_language(self):
        first = self.leveled_question("Easy", topic=self.module_topic)
        self.leveled_question("Easy")
        self.leveled_question("Hard", topic=self.module_topic)
        url = self.url
        subjects = reverse("practice:subjects", args=[self.authority.slug, self.exam.slug])
        self.assertContains(self.client.get(subjects), self.configure_url())
        self.assertContains(self.client.get(self.configure_url()), url)
        response = self.client.get(url)
        self.assertContains(response, "Easy - 1 question")
        self.assertContains(response, 'name="language"')
        self.assertContains(response, "Back to modules")
        self.assertFalse(PracticeSession.objects.exists())
        self.client.post(url, {"token": uuid4(), "difficulty": "level:easy", "language": "en"})
        session = PracticeSession.objects.get()
        self.assertEqual(set(session.questions.values_list("question_id", flat=True)), {first.pk})
        self.assertEqual(session.configuration["language"], "en")
        self.assertContains(self.client.get(self.session_url(session)), "Difficulty question")

    def setUp(self):
        self.client.force_login(self.user)
        self.module = Module.objects.create(subject=self.subject, name="Foundations", slug="foundations")
        self.module_topic = Topic.objects.create(subject=self.subject, module=self.module, name="Basics", slug="basics")
        self.url = reverse("practice:module_difficulty", args=[self.authority.slug, self.exam.slug, self.subject.slug, self.module.pk])

    def leveled_question(self, level, **kwargs):
        question = self.question(**kwargs)
        create_revision(question, language="en", question_text="Difficulty question", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="A", difficulty_level=level)
        return publish_question(mark_reviewed(question))

    def test_module_then_difficulty_selects_only_matching_published_questions(self):
        easy = self.leveled_question("Easy", topic=self.module_topic)
        self.leveled_question("Hard", topic=self.module_topic)
        self.leveled_question("Easy")
        self.leveled_question("Easy", topic=self.module_topic, exam=self.other_exam)
        response = self.client.get(self.configure_url())
        self.assertContains(response, self.url)
        self.assertNotContains(response, 'id="id_topic"')
        response = self.client.get(self.url)
        self.assertContains(response, "Easy - 1 question")
        self.assertContains(response, "Hard - 1 question")
        self.assertFalse(PracticeSession.objects.exists())
        data = {"token": uuid4(), "difficulty": "level:easy"}
        response = self.client.post(self.url, data)
        session = PracticeSession.objects.get()
        self.assertRedirects(response, self.session_url(session))
        self.assertEqual(session.questions.get().question_id, easy.pk)
        self.assertEqual(session.configuration["difficulty"], "easy")
        self.assertRedirects(self.client.post(self.url, data), self.session_url(session))
        self.assertEqual(PracticeSession.objects.count(), 1)
        with self.assertRaises(ValidationError):
            self.session(module=self.module, token=data["token"], difficulty="hard")

    def test_invalid_difficulty_foreign_module_and_empty_module(self):
        self.leveled_question("Easy", topic=self.module_topic)
        for value in ("level:hard", "", "invented"):
            self.assertEqual(self.client.post(self.url, {"token": uuid4(), "difficulty": value}).status_code, 400)
        foreign = Module.objects.create(subject=self.other_subject, name="Foreign", slug="foreign")
        url = reverse("practice:module_difficulty", args=[self.authority.slug, self.exam.slug, self.subject.slug, foreign.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertFalse(PracticeSession.objects.exists())

    def test_unpublished_difficulty_does_not_change_the_available_level(self):
        question = self.leveled_question("Easy", topic=self.module_topic)
        create_revision(question, language="en", question_text="Draft", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="A", difficulty_level="Hard")
        response = self.client.get(self.url)
        self.assertContains(response, "Easy")
        self.assertNotContains(response, "Hard")
        session = self.session(module=self.module, difficulty="easy")
        self.assertEqual(session.questions.get().question_revision_id, question.published_revision_id)

    def test_no_modules_fallback_and_unspecified_difficulty(self):
        question = self.question()
        response = self.client.get(self.configure_url())
        self.assertContains(response, "Continue with this subject")
        url = reverse("practice:difficulty", args=[self.authority.slug, self.exam.slug, self.subject.slug])
        self.assertContains(self.client.get(url), "Unspecified difficulty")
        self.client.post(url, {"token": uuid4(), "difficulty": "level:"})
        self.assertEqual(PracticeSession.objects.get().questions.get().question_id, question.pk)
