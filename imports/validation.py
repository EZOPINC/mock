from collections import Counter
from hashlib import sha256
import json
import re

from django.core.exceptions import ValidationError
from django.db.models import Q, Value
from django.db.models.functions import Coalesce, Lower, Trim

from exams.models import Exam, Subject, Topic
from previous_year.models import PreviousYearPaper
from questions.models import QuestionRevision, QuestionTranslation
from .models import ImportBatch, ImportedQuestion
from .parsing import COLUMNS, MAX_CELL, REQUIRED
from .context import context_hash, exam_ids, mode
from .translation_input import normalize_translations
from .taxonomy import unidentified_subject
from .pairing import groups_for

CONTENT = ("language", "question_text", "option_a", "option_b", "option_c", "option_d", "correct_answer", "explanation")


def normalized(value):
    return " ".join(str(value).split()).casefold()


def map_key(value):
    return sha256(normalized(value).encode()).hexdigest()[:16]


def resolve_taxonomy(value, records, aliases):
    key = normalized(value)
    if key in aliases:
        return next((record for record in records if record.pk == int(aliases[key])), None)
    if not key:
        return None
    matches = [record for record in records if normalized(record.name) == key]
    return matches[0] if len(matches) == 1 else None


def selection(data, *, locked=False):
    selected = data["selection"]
    if mode(data) not in {"previous_year", "general"}:
        raise ValidationError("Select a supported import type.")
    ids = exam_ids(data)
    exams = list(Exam.objects.select_related("authority").filter(pk__in=ids).order_by("pk"))
    if not ids or len(exams) != len(ids):
        raise ValidationError("Resolve missing or invalid selected exams.")
    if mode(data) == "general":
        if selected.get("exam_mapping", "selected") not in {"selected", "rows"}:
            raise ValidationError("Select a supported exam mapping strategy.")
        return exams, None
    if len(exams) != 1:
        raise ValidationError("Previous Year import requires exactly one exam.")
    exam = exams[0]
    if selected.get("authority_id") and selected["authority_id"] != exam.authority_id:
        raise ValidationError("Selected exam no longer belongs to the chosen authority.")
    if selected.get("paper_id"):
        queryset = PreviousYearPaper.objects.select_for_update() if locked else PreviousYearPaper.objects
        try:
            paper = queryset.get(pk=selected["paper_id"], exam=exam)
        except PreviousYearPaper.DoesNotExist:
            raise ValidationError("Selected paper no longer belongs to the exam.")
        if selected.get("import_type") and context_hash(data, paper) != context_hash(data):
            raise ValidationError("Paper identity changed since upload. Select the paper again.")
    else:
        config = dict(selected.get("paper", {}))
        config["paper_name"] = config.get("paper_name") or "Previous Year Paper"
        paper = PreviousYearPaper(exam=exam, **config)
        paper.full_clean(validate_constraints=False)
        queryset = PreviousYearPaper.objects.select_for_update() if locked else PreviousYearPaper.objects
        match = queryset.annotate(_name=Lower(Trim("paper_name")),
            _part=Lower(Trim(Coalesce("part", Value("")))),
            _session=Lower(Trim(Coalesce("session", Value(""))))).filter(
                exam=exam, stage_id=paper.stage_id, year=paper.year,
                _name=paper.paper_name.strip().lower(), _part=(paper.part or "").strip().lower(),
                _session=(paper.session or "").strip().lower()).first()
        if match:
            paper = match
    if paper.is_published:
        raise ValidationError("Unpublish the selected paper before importing.")
    paper.full_clean()
    return exams, paper


def row_exams(raw, exams, strategy, catalogue=None):
    if strategy == "selected" or not raw.strip():
        return exams, []
    def matches(label):
        key = normalized(label)
        return [exam for exam in exams if key in {normalized(exam.name), normalized(exam.code),
            normalized(f"{exam.authority.name} / {exam.name}"), normalized(f"{exam.authority.code} / {exam.code}")}]
    # Resolve against the complete taxonomy, not just selected batch defaults.
    # Qualified authority/exam labels disambiguate names and codes.
    all_exams = catalogue if catalogue is not None else list(Exam.objects.select_related("authority").all())
    exams = all_exams
    exact = matches(raw)
    labels = [raw] if exact else [label for label in re.split(r"[;|]", raw) if label.strip()]
    resolved = {}
    for label in labels:
        candidates = matches(label)
        if len(candidates) != 1:
            return [], [f"Unknown or ambiguous exam category: {label}. Use an exact name/code or Authority / Exam label."]
        resolved[candidates[0].pk] = candidates[0]
    if not resolved:
        return [], ["Resolve exam_categories or leave it blank to use selected exams."]
    return list(resolved.values()), []


def validate(data, *, locked=False):
    errors = []
    if not data["rows"]:
        errors.append("At least one data row is required.")
    try:
        exams, paper = selection(data, locked=locked)
        if ImportBatch.objects.filter(file_sha256=data["file_sha256"], context_sha256=context_hash(data, paper)).exists():
            errors.append("This file has already been imported in this import context. No records will be overwritten.")
    except ValidationError as error:
        errors.extend(error.messages)
        exams, paper = [], None
    subjects = list(Subject.objects.all())
    exam_catalogue = list(Exam.objects.select_related("authority").all()) if mode(data) == "general" and data["selection"].get("exam_mapping") == "rows" else []
    topics = list(Topic.objects.select_related("subject"))
    subject_map, topic_map = data.get("subject_map", {}), data.get("topic_map", {})
    numbers = Counter(row["values"]["question_number"].strip() for row in data["rows"])
    existing_numbers = set(paper.paper_questions.values_list("question_number", flat=True)) if paper and paper.pk else set()
    existing_imports = ImportedQuestion.objects.filter(batch__paper=paper).count() if paper and paper.pk else 0
    if existing_imports and not data["selection"].get("acknowledge_existing"):
        errors.append("This paper already contains imported questions. Inspect its existing rows, resolve conflicts, and explicitly acknowledge appending before proceeding.")
    # Possible content duplication is advisory and never merges records.
    normalized_inputs = [normalize_translations(row["values"], data["selection"]) for row in data["rows"]]
    candidate_texts = {normalized(item[0]["question_text"]) for item in normalized_inputs}
    existing_texts = set()
    if candidate_texts:
        raw_keys = {item[0]["question_text"].strip().lower() for item in normalized_inputs}
        for value in QuestionRevision.objects.annotate(_content_key=Lower(Trim("question_text"))).filter(_content_key__in=raw_keys).values_list("question_text", flat=True).iterator(chunk_size=500):
            key = normalized(value)
            if key in candidate_texts:
                existing_texts.add(key)
    seen = set()
    result = []
    fallback_subject = None
    for index, row in enumerate(data["rows"]):
        values = row["values"]
        revision, translations, translation_errors, translation_warnings = normalized_inputs[index]
        row_errors, warnings = list(translation_errors), list(translation_warnings)
        if not values["question_number"].strip():
            row_errors.append("question_number: a value is required.")
        if any(not isinstance(value, str) or len(value) > MAX_CELL for value in values.values()):
            row_errors.append("All cell values must be bounded text.")
        number = values["question_number"].strip()
        if len(number) > 100:
            row_errors.append("question_number must not exceed 100 characters.")
        if number in existing_numbers:
            row_errors.append("Question number already exists in the selected paper. Resolve the conflict; nothing will be overwritten.")
        selected = data["selection"]
        if values["subject"].strip():
            subject = resolve_taxonomy(values["subject"], subjects, subject_map)
        else:
            subject = resolve_taxonomy("", subjects, subject_map) or next((item for item in subjects if item.pk == selected.get("subject_id")), None)
            if subject is None:
                try:
                    if fallback_subject is None:
                        fallback_subject = unidentified_subject(subjects)
                    subject = fallback_subject
                    warnings.append("Blank subject defaults to UnIdentified. It will be created or reused only when the import is confirmed.")
                except ValidationError as error:
                    row_errors.extend(error.messages)
        if subject is None:
            row_errors.append("Subject is unresolved or ambiguous. Select an existing subject mapping.")
        elif paper is not None and paper.subject_id and subject.pk != paper.subject_id:
            row_errors.append("Resolved subject must match the selected paper's subject.")
        topic = None
        if values["topic"].strip() and subject:
            scoped = [topic for topic in topics if topic.subject_id == subject.pk]
            aliases = {normalized(values["topic"]): topic_map.get(normalized(values["subject"] + " / " + values["topic"]))} if normalized(values["subject"] + " / " + values["topic"]) in topic_map else {}
            topic = resolve_taxonomy(values["topic"], scoped, aliases)
            if topic is None:
                row_errors.append("Topic is unresolved or does not belong to the selected subject.")
        if not values["topic"].strip() and selected.get("topic_id"):
            topic = next((item for item in topics if item.pk == selected["topic_id"]), None)
            if topic is None or subject is None or topic.subject_id != subject.pk:
                row_errors.append("Default topic must belong to the resolved subject.")
        strategy = selected.get("exam_mapping", "selected") if mode(data) == "general" else "selected"
        resolved_exams, exam_errors = row_exams(values["exam_categories"], exams, strategy, exam_catalogue)
        row_errors.extend(exam_errors)
        if strategy == "selected" and values["exam_categories"].strip():
            warnings.append("Form-selected exams are authoritative; source exam_categories is retained as metadata.")
        if values["previous_year_tags"].strip():
            warnings.append("Source previous_year_tags is retained as metadata; it does not override this import's paper selection.")
        page = values["source_page"].strip()
        if len(page) > 50 or any(ord(char) < 32 for char in page):
            row_errors.append("source_page must be a printable page reference of at most 50 characters.")
        if page.lstrip("-").isdigit() and int(page) < 1:
            row_errors.append("Numeric source pages must be positive.")
        if page and not values["source_document"].strip():
            row_errors.append("source_page requires source_document.")
        if len(values["source_document"].strip()) > 500:
            row_errors.append("source_document must not exceed 500 characters.")
        if len(values["difficulty_level"].strip()) > 100:
            row_errors.append("difficulty_level must not exceed 100 characters.")
        if len(json.dumps(values, ensure_ascii=False).encode()) > 128 * 1024:
            row_errors.append("Row metadata exceeds 128 KB.")
        if len(json.dumps(row.get("original_values", values), ensure_ascii=False).encode()) > 128 * 1024:
            row_errors.append("Original row metadata exceeds 128 KB; replace the file with a smaller source row.")
        if not revision["correct_answer"]:
            row_errors.append("Correct answer is missing. The Question Bank requires A/B/C/D; correct this row before confirming. Handwritten marks are unverified metadata only.")
        try:
            QuestionRevision(**revision).full_clean(exclude=["question", "revision_number"])
        except ValidationError as error:
            row_errors.extend(error.messages)
        for translated in translations:
            if translated["language"] != revision["language"]:
                try:
                    QuestionTranslation(**translated).full_clean(exclude=["question", "revision"])
                except ValidationError as error:
                    row_errors.extend(error.messages)
        key = normalized(revision["question_text"])
        if key in existing_texts or key in seen:
            warnings.append("Possible duplicate question text. This row will create a separate question; no merge is performed.")
        seen.add(key)
        if values["review_status"].strip() or values["verification_notes"].strip():
            warnings.append("Legacy review/verification values are audit metadata only. The question will be pending review.")
        result.append({"index": index, "source_row": row["source_row"], "values": values,
                       "errors": row_errors, "warnings": warnings, "subject": subject, "topic": topic, "revision": revision, "translations": translations, "translation_languages": [item["language"] for item in translations], "exams": resolved_exams})
    groups = groups_for(result, data.get("pairings", {}))
    if paper is not None and paper.expected_question_count is not None:
        try:
            paper.validate_question_count(actual_count=len(existing_numbers) + len(groups))
        except ValidationError as error:
            errors.extend(error.messages)
    return {"rows": result, "groups": groups, "master_count": len(groups), "errors": errors, "exam": exams[0] if len(exams) == 1 else None, "exams": exams, "import_type": mode(data), "paper": paper, "existing_count": len(existing_numbers), "existing_imports": existing_imports,
            "total": len(result), "valid": sum(not row["errors"] for row in result),
            "error_count": sum(len(row["errors"]) for row in result) + len(errors),
            "warning_count": sum(len(row["warnings"]) for row in result)}
