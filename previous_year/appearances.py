"""Learner-facing paper provenance with private evidence left in staff review."""
from django.urls import reverse

from mock_tests.models import AttemptQuestion, MockAttempt
from .appearance_input import normalized_label
from .models import PaperQuestion, QuestionAppearance
from .services import published_papers


def same_occurrence(appearance, row):
    paper = row.paper
    if appearance.year != paper.year:
        return False
    if appearance.exam_id:
        if appearance.exam_id != paper.exam_id:
            return False
    else:
        exam_names = {normalized_label(value) for value in (paper.exam.name, paper.exam.code)}
        authority_names = {normalized_label(value) for value in (paper.exam.authority.name, paper.exam.authority.code)}
        if normalized_label(appearance.exam_name) not in exam_names:
            return False
        if appearance.authority_name and normalized_label(appearance.authority_name) not in authority_names:
            return False
    return all(not specified or normalized_label(specified) == normalized_label(actual or "") for specified, actual in (
        (appearance.stage, paper.stage.name if paper.stage_id else ""),
        (appearance.session, paper.session),
        (appearance.question_number, row.question_number),
    ))


def practice_appearances(question_id, user_id, *, answered):
    papers = list(PaperQuestion.objects.filter(question_id=question_id, paper__in=published_papers())
                  .select_related("paper__exam__authority", "paper__stage").order_by("-paper__year", "paper_id"))
    verified = list(QuestionAppearance.objects.filter(question_id=question_id, verified_at__isnull=False)
                    .select_related("exam"))
    if not papers and not verified:
        return []
    if AttemptQuestion.objects.filter(question_id=question_id, attempt__user_id=user_id,
                                     attempt__status__in=[MockAttempt.Status.CREATED, MockAttempt.Status.IN_PROGRESS]).exists():
        return []
    results = []
    for row in papers:
        paper = row.paper
        details = " ".join(part for part in (paper.stage.name if paper.stage_id else "", paper.session, paper.part) if part)
        label = f"{paper.exam.name} {paper.year}" + (f" ({details})" if details else "")
        url = ""
        if answered:
            url = reverse("previous_year:paper_detail", args=[paper.exam.authority.slug, paper.exam.slug, paper.year, paper.pk])
            url += f"#question-{row.pk}"
        results.append({"label": label, "url": url, "year": paper.year})
    for appearance in verified:
        if any(same_occurrence(appearance, row) for row in papers):
            continue
        details = " ".join(part for part in (appearance.stage, appearance.session) if part)
        exam = appearance.exam.name if appearance.exam_id else appearance.exam_name
        if not appearance.exam_id and appearance.authority_name:
            exam = f"{appearance.authority_name} / {exam}"
        label = f"{exam} {appearance.year}" + (f" ({details})" if details else "")
        results.append({"label": label, "url": "", "year": appearance.year})
    occurrences = {}
    for result in results:
        occurrences.setdefault(normalized_label(result["label"]), result)
    return sorted(occurrences.values(), key=lambda result: (-result["year"], result["label"]))
