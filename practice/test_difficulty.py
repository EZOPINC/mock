from uuid import uuid4
from django.core.exceptions import ValidationError
from django.urls import reverse
from exams.models import Module, Topic
from questions.services import create_revision, mark_reviewed, publish_question
from .models import PracticeSession
from .tests import PracticeFixture


class DifficultyFlowTests(PracticeFixture):
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
