from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q

from questions.models import Question, QuestionExam
from .models import PaperQuestion, PreviousYearPaper


@transaction.atomic
def publish_paper(paper):
    paper = PreviousYearPaper.objects.select_for_update().get(pk=getattr(paper, "pk", paper))
    paper.full_clean()
    rows = list(paper.paper_questions.select_related("question_revision__question"))
    if not rows:
        raise ValidationError("An empty paper cannot be published.")
    # Lock all referenced question identities in a stable order.
    list(Question.objects.select_for_update().filter(pk__in=[row.question_id for row in rows]).order_by("pk"))
    for row in rows:
        row.question_revision.refresh_from_db()
        row.validate_association(require_current=False)
        row.full_clean()
    paper.is_published = True
    paper.save(_publication=True)
    return paper


@transaction.atomic
def unpublish_paper(paper):
    paper = PreviousYearPaper.objects.select_for_update().get(pk=getattr(paper, "pk", paper))
    paper.is_published = False
    paper.save(_publication=True)
    return paper


def published_papers():
    """Fail closed if a paper becomes invalid after publication; retain its history."""
    exam_match = QuestionExam.objects.filter(question_id=OuterRef("question_id"), exam_id=OuterRef("paper__exam_id"))
    rows = PaperQuestion.objects.filter(paper_id=OuterRef("pk"))
    invalid = rows.annotate(_exam_match=Exists(exam_match)).filter(
        Q(question_revision__published_at__isnull=True)
        | ~Q(question_revision__question_id=F("question_id"))
        | ~Q(question__publication_status="published")
        | Q(_exam_match=False)
    )
    return PreviousYearPaper.objects.filter(
        is_published=True, exam__is_active=True, exam__authority__is_active=True,
    ).filter(Q(stage__isnull=True) | Q(stage__exam_id=F("exam_id"))).annotate(
        _has_questions=Exists(rows), _has_invalid=Exists(invalid),
    ).filter(_has_questions=True, _has_invalid=False).select_related("exam__authority", "stage")
