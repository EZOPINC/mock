"""Mock-only language eligibility; Practice keeps its existing mixed-language behavior."""
from questions.eligibility import eligible_question_ids as published_eligible_ids


def eligible_question_ids(exam_id, *, language_mode="mixed", **filters):
    if language_mode != "mixed":
        return published_eligible_ids(exam_id, language_mode=language_mode, **filters)
    english = published_eligible_ids(exam_id, language_mode="en", **filters)
    return english & published_eligible_ids(exam_id, language_mode="bn", **filters)
