from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Max

from exams.models import Exam
from previous_year.models import PaperQuestion
from questions.models import QuestionExam
from questions.services import create_question
from .models import ImportBatch, ImportedQuestion
from .permissions import require_import_permission
from .validation import validate
from .sources import persist_coded_sources, save_reference
from .context import context_hash, exam_ids, mode
from questions.tagging import set_question_topics


def confirm_import(data, user):
    user = get_user_model().objects.get(pk=user.pk)
    require_import_permission(user, mode(data))
    if data["owner"] != user.pk:
        raise PermissionDenied
    try:
        with transaction.atomic():
            existing = ImportBatch.objects.filter(staging_token=data["token"], uploaded_by=user).first()
            if existing:
                return existing
            # Serialize imports targeting the same exam, including new-paper creation.
            list(Exam.objects.select_for_update().filter(pk__in=exam_ids(data)).order_by("pk"))
            existing = ImportBatch.objects.filter(staging_token=data["token"], uploaded_by=user).first()
            if existing:
                return existing
            result = validate(data, locked=True)
            if result["error_count"]:
                raise ValidationError(result["errors"] or ["Resolve all row errors and revalidate before confirming."])
            result["taxonomy_catalogue"].persist()
            paper = result["paper"]
            if paper is not None and paper.pk is None:
                paper.save()
            batch = ImportBatch.objects.create(
                uploaded_by=user, filename=data["filename"], file_sha256=data["file_sha256"],
                context_sha256=context_hash(data, paper),
                staging_token=data["token"], paper=paper, row_count=result["total"],
                mapping_metadata={"selection": data["selection"], "worksheet": data["worksheet"],
                                  "header_aliases": data.get("header_aliases", {}),
                                  "source_headers": data.get("source_headers", []), "input_format": data.get("input_format", "long"),
                                  "master_question_count": len(result["groups"]), "pairings": data.get("pairings", {}),
                                  "resolved_exams": [{"id": exam.pk, "label": str(exam)} for exam in {exam.pk: exam for row in result["rows"] for exam in row["exams"]}.values()],
                                  "subject_map": data.get("subject_map", {}), "topic_map": data.get("topic_map", {})},
            )
            next_order = (paper.paper_questions.aggregate(value=Max("display_order"))["value"] or 0) + 1 if paper else None
            coded_sources = persist_coded_sources(result["source_plans"])
            legacy_sources = {}
            for offset, group in enumerate(result["groups"]):
                primary = group["rows"][0]
                translations = [translation for row in group["rows"] for translation in row["translations"]]
                question = create_question(subject=primary["subject"], topic=primary["topic"], revision={field: primary["revision"][field] for field in ("language", "correct_answer")},
                    translations=translations, difficulty_level=primary["difficulty"],
                    question_kind=group["question_kind"], **group.get("freshness", {}))
                topics = ([primary["topic"]] if primary["topic"] else []) + primary["secondary_topics"]
                set_question_topics(question, [topic.pk for topic in topics], primary_topic_id=question.topic_id)
                for exam in primary["exams"]:
                    QuestionExam.objects.create(question=question, exam=exam)
                if paper is not None:
                    association = PaperQuestion(paper=paper, question_revision=question.current_revision,
                        question_number=group["number"], display_order=next_order + offset)
                    association.save(_import_draft=True)
                for row in group["rows"]:
                    values = row["values"]
                    source_id = save_reference(question, row["source_reference"], coded_sources, legacy_sources)
                    ImportedQuestion.objects.create(batch=batch, source_row_number=row["source_row"], question=question,
                        source_metadata={"original": data["rows"][row["index"]].get("original_values", values), "corrected": values,
                            "resolved": {"source_id": source_id, "subject_id": question.subject_id, "topic_id": question.topic_id,
                                         "topic_ids": [topic.pk for topic in topics], "taxonomy_path": row["taxonomy_path"],
                                         "secondary_paths": row["secondary_paths"], "language": row["revision"]["language"], "languages": row["translation_languages"], "correct_answer": question.correct_answer,
                                         "exam_ids": [exam.pk for exam in row["exams"]], "paper_id": paper.pk if paper else None,
                                         "translation_pairing": group["signature"] if group["requires_pairing"] else None}})
            return batch
    except IntegrityError as error:
        existing = ImportBatch.objects.filter(staging_token=data["token"], uploaded_by=user).first()
        if existing:
            return existing
        raise ValidationError("A file or paper conflict was detected. Revalidate or choose the existing draft paper; no partial import was saved.") from error
