"""Mock-only language eligibility; Practice keeps its existing mixed-language behavior."""
from django.core.exceptions import ValidationError

from questions.eligibility import eligible_question_ids as published_eligible_ids


def eligible_question_ids(exam_id, *, language_mode="mixed", **filters):
    if language_mode != "mixed":
        return published_eligible_ids(exam_id, language_mode=language_mode, **filters)
    english = published_eligible_ids(exam_id, language_mode="en", **filters)
    return english & published_eligible_ids(exam_id, language_mode="bn", **filters)


def reading_language_options(sections):
    modes = {section.language_mode for section in sections}
    if modes == {"mixed"}:
        return (("en", "English"), ("bn", "Bengali"), ("both", "English and Bengali"))
    if modes and modes <= {"en", "mixed"}:
        return (("en", "English"),)
    if modes and modes <= {"bn", "mixed"}:
        return (("bn", "Bengali"),)
    return (("both", "As configured by section"),)


def default_reading_language(exam, options):
    preferred = exam.preferred_mock_language
    if preferred and any(code == preferred for code, _ in options):
        return preferred
    return options[-1][0]


def validate_default_reading_language(exam, sections):
    preferred = exam.preferred_mock_language
    options = reading_language_options(sections)
    if preferred and all(code != preferred for code, _ in options):
        label = dict(exam._meta.get_field("default_mock_language").choices)[preferred]
        raise ValidationError(f"Every section must support the exam's default mock language ({label}).")
