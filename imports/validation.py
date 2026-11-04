from collections import Counter
from hashlib import sha256
import json
import re

from django.core.exceptions import ValidationError

from exams.models import Exam, Subject, Topic
from previous_year.models import PreviousYearPaper
from questions.models import QuestionRevision
from .models import ImportBatch
from .parsing import COLUMNS, MAX_CELL, REQUIRED

CONTENT = ("language", "question_text", "option_a", "option_b", "option_c", "option_d", "correct_answer", "explanation")


def normalized(value):
    return " ".join(str(value).split()).casefold()


def map_key(value):
    return sha256(normalized(value).encode()).hexdigest()[:16]


def resolve_taxonomy(value, records, aliases):
    key = normalized(value)
    if not key:
        return None
    if key in aliases:
        return next((record for record in records if record.pk == int(aliases[key])), None)
    matches = [record for record in records if normalized(record.name) == key]
    return matches[0] if len(matches) == 1 else None


def selection(data, *, locked=False):
    selected = data["selection"]
    try:
        exam = Exam.objects.select_related("authority").get(pk=selected["exam_id"], authority_id=selected["authority_id"])
        if selected["paper_id"]:
            queryset = PreviousYearPaper.objects.select_for_update() if locked else PreviousYearPaper.objects
            paper = queryset.get(pk=selected["paper_id"], exam=exam)
        else:
            paper = PreviousYearPaper(exam=exam, **selected["paper"])
        if paper.is_published:
            raise ValidationError("Unpublish the selected paper before importing.")
        paper.full_clean()
        return exam, paper
    except (Exam.DoesNotExist, PreviousYearPaper.DoesNotExist):
        raise ValidationError("Selected exam/paper no longer exists or its parent mapping changed.")


def validate(data, *, locked=False):
    errors = []
    if ImportBatch.objects.filter(file_sha256=data["file_sha256"]).exists():
        errors.append("This file has already been imported. No records will be overwritten.")
    try:
        exam, paper = selection(data, locked=locked)
    except ValidationError as error:
        errors.extend(error.messages)
        exam, paper = None, None
    subjects = list(Subject.objects.all())
    topics = list(Topic.objects.select_related("subject"))
    subject_map, topic_map = data.get("subject_map", {}), data.get("topic_map", {})
    numbers = Counter(row["values"]["question_number"].strip() for row in data["rows"])
    existing_numbers = set(paper.paper_questions.values_list("question_number", flat=True)) if paper and paper.pk else set()
    tags = {normalized(row["values"]["previous_year_tags"]) for row in data["rows"] if row["values"]["previous_year_tags"].strip()}
    if len(tags) > 1:
        errors.append("Multiple distinct paper tags found. Split files containing multiple papers, or explicitly correct synonymous labels to one paper tag.")
    exam_aliases = {normalized(value) for value in data["selection"].get("exam_aliases", "").splitlines() if value.strip()}
    paper_aliases = {normalized(value) for value in data["selection"].get("paper_aliases", "").splitlines() if value.strip()}
    if exam:
        exam_aliases |= {normalized(exam.name), normalized(exam.code), normalized(f"{exam.authority.name} / {exam.name}")}
    if paper:
        paper_aliases.add(normalized(f"{paper.year} / {paper.paper_name}"))
    # Possible content duplication is advisory and never merges records.
    candidate_texts = {normalized(row["values"]["question_text"]) for row in data["rows"]}
    existing_texts = set()
    if candidate_texts:
        for value in QuestionRevision.objects.values_list("question_text", flat=True).iterator(chunk_size=500):
            key = normalized(value)
            if key in candidate_texts:
                existing_texts.add(key)
    seen = set()
    result = []
    for index, row in enumerate(data["rows"]):
        values = row["values"]
        row_errors, warnings = [], []
        for field in REQUIRED:
            if not values[field].strip():
                row_errors.append(f"{field}: a value is required.")
        if any(not isinstance(value, str) or len(value) > MAX_CELL for value in values.values()):
            row_errors.append("All cell values must be bounded text.")
        number = values["question_number"].strip()
        if len(number) > 100:
            row_errors.append("question_number must not exceed 100 characters.")
        if numbers[number] > 1:
            row_errors.append("Duplicate question number in this file.")
        if number in existing_numbers:
            row_errors.append("Question number already exists in the selected paper. Resolve the conflict; nothing will be overwritten.")
        subject = resolve_taxonomy(values["subject"], subjects, subject_map)
        if subject is None:
            row_errors.append("Subject is unresolved or ambiguous. Select an existing subject mapping.")
        topic = None
        if values["topic"].strip() and subject:
            scoped = [topic for topic in topics if topic.subject_id == subject.pk]
            aliases = {normalized(values["topic"]): topic_map.get(normalized(values["subject"] + " / " + values["topic"]))} if normalized(values["subject"] + " / " + values["topic"]) in topic_map else {}
            topic = resolve_taxonomy(values["topic"], scoped, aliases)
            if topic is None:
                row_errors.append("Topic is unresolved or does not belong to the selected subject.")
        categories = values["exam_categories"].strip()
        if categories:
            category_keys = {normalized(categories)} if normalized(categories) in exam_aliases else {normalized(value) for value in re.split(r"[;|]", categories) if value.strip()}
            if not category_keys.issubset(exam_aliases):
                row_errors.append("exam_categories does not match an explicitly approved alias for the selected exam.")
        if values["previous_year_tags"].strip() and normalized(values["previous_year_tags"]) not in paper_aliases:
            row_errors.append("previous_year_tags needs an explicit alias confirming the selected paper.")
        page = values["source_page"].strip()
        if len(page) > 50 or any(ord(char) < 32 for char in page):
            row_errors.append("source_page must be a printable page reference of at most 50 characters.")
        if page and not values["source_document"].strip():
            row_errors.append("source_page requires source_document.")
        if len(values["source_document"].strip()) > 500:
            row_errors.append("source_document must not exceed 500 characters.")
        if len(json.dumps(values, ensure_ascii=False).encode()) > 128 * 1024:
            row_errors.append("Row metadata exceeds 128 KB.")
        revision = {field: values[field] for field in CONTENT}
        revision["language"] = revision["language"].strip().lower()
        revision["correct_answer"] = revision["correct_answer"].strip().upper()
        try:
            QuestionRevision(**revision).full_clean(exclude=["question", "revision_number"])
        except ValidationError as error:
            row_errors.extend(error.messages)
        key = normalized(values["question_text"])
        if key in existing_texts or key in seen:
            warnings.append("Possible duplicate question text. This row will create a separate question; no merge is performed.")
        seen.add(key)
        if values["review_status"].strip() or values["verification_notes"].strip():
            warnings.append("Legacy review/verification values are audit metadata only. The question will be pending review.")
        result.append({"index": index, "source_row": row["source_row"], "values": values,
                       "errors": row_errors, "warnings": warnings, "subject": subject, "topic": topic, "revision": revision})
    return {"rows": result, "errors": errors, "exam": exam, "paper": paper,
            "total": len(result), "valid": sum(not row["errors"] for row in result),
            "error_count": sum(len(row["errors"]) for row in result) + len(errors),
            "warning_count": sum(len(row["warnings"]) for row in result)}
