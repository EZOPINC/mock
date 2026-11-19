"""Resolve private source references in preview and persist them on confirmation."""
from collections import defaultdict
import re

from django.core.exceptions import ValidationError

from questions.models import QuestionSource, QuestionSourceReference, SOURCE_CODE_PATTERN


def resolve_sources(rows):
    coded_rows = defaultdict(list)
    for row in rows:
        values = row["values"]
        code = values.get("source_code", "").strip().upper()
        document = values["source_document"].strip()
        publisher = values.get("source_publisher", "").strip()
        page = values["source_page"].strip()
        number = values.get("source_question_number", "").strip()
        errors = row["errors"]
        row["source_reference"] = {"code": code, "document": document, "publisher": publisher,
                                   "page": page or None, "number": number or None}
        if len(page) > 50 or any(ord(char) < 32 for char in page):
            errors.append("source_page must be a printable page reference of at most 50 characters.")
        elif page.lstrip("-").isdecimal() and int(page) < 1:
            errors.append("Numeric source pages must be positive.")
        if page and not (code or document):
            errors.append("source_page requires source_code or source_document.")
        if len(document) > 500:
            errors.append("source_document must not exceed 500 characters.")
        if len(publisher) > 200:
            errors.append("source_publisher must not exceed 200 characters.")
        if (code or document) and (len(number) > 100 or any(ord(char) < 32 for char in number)):
            errors.append("source_question_number must be printable and at most 100 characters.")
        if code:
            if re.fullmatch(SOURCE_CODE_PATTERN, code):
                coded_rows[code].append(row)
            else:
                errors.append("source_code must start with a letter or digit and contain at most 64 letters, digits, dots, underscores or hyphens.")
        elif publisher:
            row["warnings"].append("source_publisher is retained as import metadata. Supply source_code to register a publisher.")

    existing = QuestionSource.objects.in_bulk(coded_rows, field_name="source_code") if coded_rows else {}
    plans = {}
    for code, members in coded_rows.items():
        source = existing.get(code)
        documents = {row["source_reference"]["document"] for row in members if row["source_reference"]["document"]}
        publishers = {row["source_reference"]["publisher"] for row in members if row["source_reference"]["publisher"]}
        if source:
            documents.add(source.source_document)
            if source.publisher:
                publishers.add(source.publisher)
        if len(documents) > 1 or len(publishers) > 1:
            for row in members:
                row["errors"].append(f"Source code {code} has conflicting documents or publishers.")
        elif not documents or documents == {""}:
            for row in members:
                row["errors"].append(f"Supply source_document on at least one row for source code {code}.")
        else:
            plan = {"document": documents.pop(), "publisher": next(iter(publishers), ""), "new": source is None}
            plans[code] = plan
            for row in members:
                row["source_reference"].update(plan)
    return plans


def persist_coded_sources(plans):
    sources = {}
    for code, plan in sorted(plans.items()):
        source, _ = QuestionSource.objects.get_or_create(
            source_code=code,
            defaults={"source_name": plan["document"][:200], "source_document": plan["document"],
                      "publisher": plan["publisher"]},
        )
        source = QuestionSource.objects.select_for_update().get(pk=source.pk)
        publisher = plan["publisher"]
        if source.source_document != plan["document"] or (source.publisher and publisher and source.publisher != publisher):
            raise ValidationError(f"Source code {code} changed during confirmation. Revalidate and try again.")
        if publisher and not source.publisher:
            source.publisher = publisher
            source.save(update_fields=["publisher"])
        sources[code] = source
    return sources


def save_reference(question, reference, coded_sources, legacy_sources):
    code, document = reference["code"], reference["document"]
    if code:
        source = coded_sources[code]
    elif document:
        if document not in legacy_sources:
            legacy_sources[document] = (
                QuestionSource.objects.filter(source_document=document).order_by("pk").first()
                or QuestionSource.objects.create(source_name=document[:200], source_document=document)
            )
        source = legacy_sources[document]
    else:
        return None
    QuestionSourceReference.objects.get_or_create(question=question, source=source,
        source_page=reference["page"], source_question_number=reference["number"])
    return source.pk
