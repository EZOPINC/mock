from django.core.exceptions import ValidationError
from django.db import transaction

from imports.models import ImportedQuestion
from previous_year.models import PaperQuestion, PreviousYearPaper
from questions.models import Question, QuestionExam, TRANSLATED_FIELDS
from questions.services import create_revision, mark_reviewed, publish_question
from questions.tagging import set_question_topics
from .services import require_batch_permission


def imported_questions():
    return Question.objects.filter(pk__in=ImportedQuestion.objects.order_by().values("question_id"))


def question_state(question):
    return [
        question.current_revision_id, question.published_revision_id, question.review_status,
        question.updated_at.isoformat(),
        question.topic_id,
        list(question.topic_associations.order_by("topic_id").values_list("topic_id", flat=True)),
        list(question.exams.order_by("pk").values_list("pk", flat=True)),
    ]


@transaction.atomic
def save_review_question(user, question_id, expected, cleaned):
    require_batch_permission(user)
    question = imported_questions().select_for_update().get(pk=question_id)
    if question_state(question) != expected:
        raise ValidationError("This question changed after you opened it. Reload and inspect it again.")
    subject = cleaned["subject"]
    if subject.pk != question.subject_id and PaperQuestion.objects.filter(
        question=question, paper__subject__isnull=False,
    ).exclude(paper__subject=subject).exists():
        raise ValidationError("The question is linked to a paper that requires its current subject.")
    exam_ids = {exam.pk for exam in cleaned["exams"]}
    old_exam_ids = set(question.exams.values_list("pk", flat=True))
    if old_exam_ids - exam_ids and PaperQuestion.objects.filter(question=question).exclude(paper__exam_id__in=exam_ids).exists():
        raise ValidationError("Keep the exam associations required by linked previous-year papers.")
    primary = cleaned["topic"]
    primary_id = primary.pk if primary else None
    topic_ids = {topic.pk for topic in cleaned["additional_topics"]}
    if primary_id:
        topic_ids.add(primary_id)
    existing_topics = set(question.topic_associations.values_list("topic_id", flat=True))
    if subject.pk != question.subject_id:
        set_question_topics(question, [])
        question.subject = subject
        existing_topics.clear()
    metadata = ("question_kind", "current_as_of", "expires_on")
    for field in metadata:
        setattr(question, field, cleaned[field])
    question.save(update_fields=[*metadata, "subject", "updated_at"])
    if primary_id != question.topic_id or topic_ids != existing_topics:
        set_question_topics(question, sorted(topic_ids), primary_topic_id=primary_id)

    if old_exam_ids != exam_ids:
        question.exam_associations.exclude(exam_id__in=exam_ids).delete()
        for exam_id in sorted(exam_ids - old_exam_ids):
            QuestionExam.objects.create(question=question, exam_id=exam_id)

    revision = question.current_revision
    editions = list(revision.translations.all())
    versions = []
    for edition in editions:
        version = {"language": edition.language}
        for field in TRANSLATED_FIELDS:
            stored = getattr(edition, field)
            submitted = cleaned[f"{field}_{edition.language}"].replace("\r\n", "\n").replace("\r", "\n")
            # Browser textarea submission normalizes line breaks. Keep unchanged source text.
            version[field] = stored if stored.replace("\r\n", "\n").replace("\r", "\n") == submitted else submitted
        versions.append(version)
    changed = any(getattr(edition, field) != version[field]
        for edition, version in zip(editions, versions) for field in TRANSLATED_FIELDS)
    if changed or revision.correct_answer != cleaned["correct_answer"] or revision.difficulty_level != cleaned["difficulty_level"]:
        primary_text = next(version for version in versions if version["language"] == revision.language)
        create_revision(question, translations=versions, difficulty_level=cleaned["difficulty_level"],
            correct_answer=cleaned["correct_answer"], **primary_text)


@transaction.atomic
def transition_selection(user, selected, action):
    require_batch_permission(user)
    if action not in {"review", "publish"} or not selected:
        raise ValidationError("Select questions and choose review or publish.")
    draft_rows = PaperQuestion.objects.none()
    if action == "publish":
        # Use the same paper-before-question lock order as PaperQuestion.save().
        draft_rows = PaperQuestion.objects.filter(question_id__in=selected, paper__is_published=False,
            question_revision__published_at__isnull=True)
        paper_ids = draft_rows.order_by().values("paper_id")
        locked_papers = list(PreviousYearPaper.objects.select_for_update().filter(
            pk__in=paper_ids).order_by("pk").values_list("pk", flat=True))
        draft_rows = draft_rows.filter(paper_id__in=locked_papers)
    questions = list(imported_questions().select_for_update().filter(pk__in=selected).order_by("pk"))
    if len(questions) != len(selected) or any(question_state(q) != selected[str(q.pk)] for q in questions):
        raise ValidationError("A selected question changed. Inspect it again before retrying.")
    operation = mark_reviewed if action == "review" else publish_question
    result = {}
    for question in questions:
        if not question.current_revision_id:
            raise ValidationError(f"Question {question.pk} has no working revision.")
        updated = operation(question, revision_id=question.current_revision_id)
        result[str(question.pk)] = question_state(updated)
    if action == "publish":
        revisions = {question.pk: question.current_revision_id for question in questions}
        for row in draft_rows.order_by("paper_id", "pk"):
            row.question_revision_id = revisions[row.question_id]
            row.save(update_fields=["question_revision"])
    return result
