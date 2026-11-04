from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.urls import reverse

from .models import QuestionTranslation
from .services import add_translation, get_published_revision, published_questions
from .tests import QuestionFixture, content


def bengali(**overrides):
    return dict(question_text="সঠিক উত্তর কোনটি?", option_a="এক", option_b="দুই", option_c="তিন", option_d="চার", explanation="ব্যাখ্যা") | overrides


class MultilingualQuestionTests(QuestionFixture):
    def test_existing_single_language_creation_has_translation_snapshot(self):
        question = self.make_question()
        self.assertEqual(question.correct_answer, "A")
        translation = question.current_revision.translations.get()
        self.assertEqual(translation.question_id, question.pk)
        self.assertEqual(translation.language, "en")
        self.assertEqual(translation.question_text, question.current_revision.question_text)

    def test_adding_translation_creates_new_revision_without_changing_live_paper_content(self):
        question = self.publish(self.make_question())
        old = question.published_revision
        new = add_translation(question, language="bn", **bengali())
        question.refresh_from_db()
        self.assertEqual(question.review_status, "pending_review")
        self.assertEqual(get_published_revision(question), old)
        self.assertEqual(list(new.translations.values_list("language", flat=True)), ["bn", "en"])
        self.assertEqual(old.translations.count(), 1)
        self.publish(question)
        self.assertEqual(get_published_revision(question), new)

    def test_translation_updates_preserve_all_old_snapshots_and_shared_answer(self):
        question = self.make_question()
        first = add_translation(question, language="bn", **bengali())
        second = add_translation(question, language="bn", **bengali(question_text="নতুন প্রশ্ন"))
        self.assertEqual(first.translations.get(language="bn").question_text, bengali()["question_text"])
        self.assertEqual(second.translations.get(language="bn").question_text, "নতুন প্রশ্ন")
        self.assertEqual(second.translations.count(), 2)
        self.assertEqual(second.correct_answer, "A")
        with self.assertRaises(ValidationError):
            add_translation(question, language="bn", correct_answer="B", **bengali())

    def test_translation_mutation_and_deletion_are_blocked(self):
        question = self.publish(self.make_question())
        translation = question.published_revision.translations.get()
        translation.question_text = "Changed"
        with self.assertRaises(ValidationError):
            translation.save()
        with self.assertRaises(ValidationError):
            QuestionTranslation.objects.filter(pk=translation.pk).update(question_text="Changed")
        with self.assertRaises(ProtectedError):
            translation.delete()
        with self.assertRaises(ValidationError):
            QuestionTranslation(question=question, revision=question.published_revision, language="bn", **bengali()).save(_assembly=True)

    def test_translations_are_unique_per_revision_and_owned_by_master(self):
        question = self.make_question()
        other = self.make_question()
        translated = QuestionTranslation(question=other, revision=question.current_revision, language="bn", **bengali())
        with self.assertRaises(ValidationError):
            translated.full_clean()
        translated = QuestionTranslation(question=question, revision=question.current_revision, language="en", **{field: getattr(question.current_revision, field) for field in ("question_text", "option_a", "option_b", "option_c", "option_d", "explanation")})
        with self.assertRaises(ValidationError):
            translated.full_clean()

    def test_translation_admin_requires_change_permission_and_new_review(self):
        from django.contrib.auth import get_user_model
        question = self.publish(self.make_question())
        url = reverse("admin:questions_question_translation", args=[question.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        staff = get_user_model().objects.create_user(username="no_permission", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.post(url, {"language": "bn", **bengali()}).status_code, 403)
        admin = get_user_model().objects.create_superuser(username="translation_admin", email="admin@example.test")
        self.client.force_login(admin)
        response = self.client.post(url, {"language": "bn", **bengali()})
        self.assertEqual(response.status_code, 302)
        question.refresh_from_db()
        self.assertEqual(question.current_revision.translations.count(), 2)
        self.assertEqual(question.review_status, "pending_review")

    def test_shared_answer_is_snapshotted_and_cannot_be_edited_directly(self):
        question = self.make_question()
        question.correct_answer = "D"
        with self.assertRaises(ValidationError):
            question.save()

    def test_published_translation_prefetch_does_not_query_per_language(self):
        question = self.make_question()
        add_translation(question, language="bn", **bengali())
        self.publish(question)
        with self.assertNumQueries(2):
            question = published_questions().get(pk=question.pk)
            languages = [translation.language for translation in question.published_revision.translations.all()]
        self.assertEqual(languages, ["bn", "en"])
