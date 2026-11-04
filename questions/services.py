"""The write boundary for question revisions, review, and publication.

Every transition locks the parent Question first. Review applies to its working
revision; a new revision resets review without replacing the live pointer.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from .models import Question, QuestionRevision, QuestionTranslation, TRANSLATED_FIELDS


def _locked(question):
    return Question.objects.select_for_update().get(pk=question.pk if isinstance(question, Question) else question)


def _check_expected(question, revision_id):
    if revision_id is not None and question.current_revision_id != revision_id:
        raise ValidationError("The working revision changed. Reload and review it before continuing.")


@transaction.atomic
def create_question(*, subject, revision, topic=None, source_question_id=None, translations=None, difficulty_level=""):
    question = Question.objects.create(subject=subject, topic=topic, source_question_id=source_question_id)
    create_revision(question, translations=translations, difficulty_level=difficulty_level, **revision)
    question.refresh_from_db()
    return question


@transaction.atomic
def create_revision(question, *, translations=None, difficulty_level=None, **content):
    question = _locked(question)
    allowed = {"language", "question_text", "option_a", "option_b", "option_c", "option_d", "correct_answer", "explanation"}
    if set(content) - allowed:
        raise ValidationError("Only revision content fields may be supplied.")
    number = (question.revisions.aggregate(number=Max("revision_number"))["number"] or 0) + 1
    if difficulty_level is None:
        difficulty_level = question.difficulty_level
    revision = QuestionRevision.objects.create(question=question, revision_number=number, difficulty_level=difficulty_level, **content)
    if translations is None and question.current_revision_id:
        translations = [dict(language=item.language, **{field: getattr(item, field) for field in TRANSLATED_FIELDS}) for item in question.current_revision.translations.all() if item.language != revision.language]
    languages = set()
    for translated in translations or []:
        translated = dict(translated)
        language = translated.pop("language")
        if language in languages:
            raise ValidationError("Only one translation per language is allowed in a revision.")
        languages.add(language)
        if language == revision.language:
            if any(translated.get(field, "") != getattr(revision, field) for field in TRANSLATED_FIELDS):
                raise ValidationError("Primary translation does not match the revision content.")
            continue
        QuestionTranslation(question=question, revision=revision, language=language, **translated).save(_assembly=True)
    question.current_revision = revision
    question.correct_answer = revision.correct_answer
    question.difficulty_level = revision.difficulty_level
    question.review_status = Question.ReviewStatus.PENDING
    question.save(_workflow=True)
    return revision


@transaction.atomic
def add_translation(question, *, language, **content):
    question = _locked(question)
    if not question.current_revision_id:
        raise ValidationError("Create the initial revision first.")
    current = question.current_revision
    translations = {item.language: dict(language=item.language, **{field: getattr(item, field) for field in TRANSLATED_FIELDS}) for item in current.translations.all()}
    if set(content) - set(TRANSLATED_FIELDS):
        raise ValidationError("Answer, difficulty and classifications are shared master attributes.")
    translations[language] = {"language": language, "explanation": "", **content}
    primary = translations[current.language]
    return create_revision(question, correct_answer=current.correct_answer, translations=list(translations.values()), **primary)


def validate_translations(revision):
    translations = list(revision.translations.all())
    if not translations or not any(item.language == revision.language for item in translations):
        raise ValidationError("A valid primary translation is required.")
    for translated in translations:
        translated.full_clean()


@transaction.atomic
def mark_reviewed(question, *, revision_id=None):
    question = _locked(question)
    _check_expected(question, revision_id)
    if not question.current_revision_id:
        raise ValidationError("A valid current revision is required for review.")
    question.current_revision.full_clean()
    validate_translations(question.current_revision)
    question.review_status = Question.ReviewStatus.REVIEWED
    question.save(_workflow=True)
    return question


@transaction.atomic
def publish_question(question, *, revision_id=None):
    question = _locked(question)
    _check_expected(question, revision_id)
    if question.review_status != Question.ReviewStatus.REVIEWED or not question.current_revision_id:
        raise ValidationError("Review the current revision before publishing.")
    revision = question.current_revision
    revision.full_clean()
    validate_translations(revision)
    if revision.published_at is None:
        revision.published_at = timezone.now()
        revision.save(_publishing=True, update_fields=["published_at"])
    question.published_revision = revision
    question.publication_status = Question.PublicationStatus.PUBLISHED
    question.save(_workflow=True)
    return question


def published_questions():
    """Safe reusable public queryset; never read current_revision for live content."""
    return Question.objects.filter(
        publication_status=Question.PublicationStatus.PUBLISHED,
        published_revision__published_at__isnull=False,
        published_revision__question_id=F("pk"),
    ).select_related("published_revision", "subject", "topic").prefetch_related("published_revision__translations")


def get_published_revision(question):
    pk = question.pk if isinstance(question, Question) else question
    result = published_questions().filter(pk=pk).first()
    return result.published_revision if result else None
