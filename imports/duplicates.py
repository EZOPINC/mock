"""Require a decision before importing text already in the question bank."""
from collections import Counter, defaultdict
from hashlib import sha256
import json

from django.core.exceptions import ValidationError
from django.db.models.functions import Lower, Trim

from questions.models import Question, QuestionTranslation, TRANSLATED_FIELDS
from .taxonomy import normalized

DUPLICATE_ERROR = "Possible duplicate question in the bank. Choose an existing question or confirm a separate question."


def input_signature(rows):
    state = [(row["source_row"], row["values"]) for row in rows]
    return sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def split_skipped_rows(data, *, allow_skip):
    if not allow_skip:
        return list(enumerate(data["rows"])), []
    decisions = data.get("duplicate_decisions", {})
    numbered_rows = defaultdict(list)
    for index, row in enumerate(data["rows"]):
        numbered_rows[row["values"]["question_number"].strip()].append((index, row))
    skipped_groups = []
    skipped_indices = set()
    for number, members in numbered_rows.items():
        decision = decisions.get(number, {})
        if decision.get("choice") != "skip":
            continue
        signature = input_signature([row for _, row in members])
        if decision.get("input_signature") != signature:
            continue
        rows = [{"index": index, "source_row": row["source_row"], "values": row["values"],
                 "errors": [], "warnings": [], "skipped": True} for index, row in members]
        skipped_groups.append({
            "number": number, "key": sha256(number.encode()).hexdigest()[:16], "rows": rows,
            "input_signature": signature, "has_duplicates": True, "duplicate_choice": "skip",
            "matched_question_ids": decision.get("matched_question_ids", []), "can_skip": True,
        })
        skipped_indices.update(index for index, _ in members)
    return [(index, row) for index, row in enumerate(data["rows"]) if index not in skipped_indices], skipped_groups


def edition_text(value):
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def eligible_match(question, group, existing_ids):
    primary = group["rows"][0]
    revision = question.published_revision
    if (question.pk in existing_ids or not revision or not revision.published_at
            or revision.question_id != question.pk or question.publication_status != Question.PublicationStatus.PUBLISHED
            or not primary["subject"] or question.subject_id != primary["subject"].pk
            or revision.correct_answer != primary["revision"]["correct_answer"]):
        return False
    editions = {edition.language: edition for edition in revision.translations.all()
                if edition.question_id == question.pk}
    if revision.language not in editions:
        return False
    return all(
        (edition := editions.get(incoming["language"])) is not None
        and all(edition_text(getattr(edition, field)) == edition_text(incoming[field])
                for field in TRANSLATED_FIELDS if field != "explanation")
        for row in group["rows"] for incoming in row["translations"]
    )


def resolve_duplicates(groups, decisions, paper, *, allow_skip):
    keys = {edition["question_text"].strip().lower()
            for group in groups for row in group["rows"] for edition in row["translations"]
            if edition["question_text"].strip()}
    matches = defaultdict(set)
    if keys:
        translations = QuestionTranslation.objects.annotate(stem=Lower(Trim("question_text"))).filter(stem__in=keys)
        for pk, stem in translations.order_by().values_list("question_id", "question_text").iterator(chunk_size=500):
            matches[normalized(stem)].add(pk)
    ids = set().union(*matches.values())
    questions = (Question.objects.filter(pk__in=ids).select_related("published_revision")
        .prefetch_related("published_revision__translations").in_bulk() if paper and ids else {})
    existing_ids = set(paper.paper_questions.values_list("question_id", flat=True)) if paper and paper.pk else set()
    for group in groups:
        candidate_ids = set().union(*(matches.get(normalized(edition["question_text"]), set())
            for row in group["rows"] for edition in row["translations"]))
        if not candidate_ids:
            continue
        group["has_duplicates"] = True
        group["matched_question_ids"] = sorted(candidate_ids)
        group["can_skip"] = allow_skip
        group["input_signature"] = input_signature(group["rows"])
        group["reuse_candidates"] = [
            question.published_revision for pk in sorted(candidate_ids) if (question := questions.get(pk))
            and eligible_match(question, group, existing_ids)
        ]
        decision = decisions.get(group["number"], {})
        if decision.get("signature") == group["signature"]:
            choice = decision.get("choice")
            if choice == "separate":
                group["duplicate_choice"] = choice
                continue
            for revision in group["reuse_candidates"]:
                if choice == f"reuse:{revision.pk}":
                    group["duplicate_choice"] = choice
                    group["reuse_revision"] = revision
                    break
            if "reuse_revision" in group:
                continue
        for row in group["rows"]:
            row["errors"].append(
                "Possible duplicate question in the bank. Skip it or confirm a separate question."
                if allow_skip else DUPLICATE_ERROR
            )

    reused = Counter(group["reuse_revision"].question_id for group in groups if "reuse_revision" in group)
    for group in groups:
        if "reuse_revision" in group and reused[group["reuse_revision"].question_id] > 1:
            for row in group["rows"]:
                row["errors"].append("The same question cannot be reused twice in one paper.")


def lock_reused_questions(groups, paper):
    planned = [group for group in groups if "reuse_revision" in group]
    if not planned:
        return {}
    ids = [group["reuse_revision"].question_id for group in planned]
    # The import already holds the destination paper lock. Lock masters in PK order.
    locked = list(Question.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    questions = {question.pk: question for question in locked}
    existing_ids = set(paper.paper_questions.values_list("question_id", flat=True)) if paper.pk else set()
    for group in planned:
        revision = group["reuse_revision"]
        question = questions.get(revision.question_id)
        if (not question or question.published_revision_id != revision.pk
                or not eligible_match(question, group, existing_ids)):
            raise ValidationError("An existing question changed after review. Revalidate the reuse choice.")
    return questions
