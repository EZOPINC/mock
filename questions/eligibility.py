"""Shared published-revision eligibility for mock tests and practice."""
from .services import published_questions


CONTENT_FIELDS = ("question_text", "option_a", "option_b", "option_c", "option_d")


def eligible_question_ids(exam_id, *, subject_id=None, topic_id=None, language_mode="mixed"):
    questions = published_questions().filter(exam_associations__exam_id=exam_id,
        exam_associations__exam__is_active=True, exam_associations__exam__authority__is_active=True).distinct()
    if subject_id:
        questions = questions.filter(subject_id=subject_id)
    if topic_id:
        questions = questions.filter(topic_id=topic_id)
    languages = {"en", "bn"} if language_mode == "mixed" else {language_mode}
    result = set()
    for question in questions:
        revision = question.published_revision
        if revision.correct_answer not in "ABCD" or len(revision.correct_answer) != 1:
            continue
        if not all(getattr(revision, field).strip() for field in CONTENT_FIELDS):
            continue
        translations = list(revision.translations.all())
        valid = [item for item in translations if item.question_id == question.pk and all(getattr(item, field).strip() for field in CONTENT_FIELDS)]
        primary = next((item for item in valid if item.language == revision.language), None)
        if not primary or any(getattr(primary, field) != getattr(revision, field) for field in CONTENT_FIELDS):
            continue
        if any(item.language in languages for item in valid):
            result.add(question.pk)
    return result

