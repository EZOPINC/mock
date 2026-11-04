from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Max

from exams.models import Exam
from previous_year.models import PaperQuestion
from questions.models import QuestionExam, QuestionSource, QuestionSourceReference
from questions.services import create_question
from .models import ImportBatch, ImportedQuestion
from .permissions import require_import_permission
from .validation import validate


def confirm_import(data, user):
    user = get_user_model().objects.get(pk=user.pk)
    require_import_permission(user)
    if data["owner"] != user.pk:
        raise PermissionDenied
    try:
        with transaction.atomic():
            existing = ImportBatch.objects.filter(staging_token=data["token"], uploaded_by=user).first()
            if existing:
                return existing
            # Serialize imports targeting the same exam, including new-paper creation.
            Exam.objects.select_for_update().get(pk=data["selection"]["exam_id"])
            result = validate(data, locked=True)
            if result["error_count"]:
                raise ValidationError(result["errors"] or ["Resolve all row errors and revalidate before confirming."])
            paper = result["paper"]
            if paper.pk is None:
                paper.save()
            batch = ImportBatch.objects.create(
                uploaded_by=user, filename=data["filename"], file_sha256=data["file_sha256"],
                staging_token=data["token"], paper=paper, row_count=result["total"],
                mapping_metadata={"selection": data["selection"], "worksheet": data["worksheet"],
                                  "subject_map": data.get("subject_map", {}), "topic_map": data.get("topic_map", {})},
            )
            next_order = (paper.paper_questions.aggregate(value=Max("display_order"))["value"] or 0) + 1
            sources = {}
            for offset, row in enumerate(result["rows"]):
                question = create_question(subject=row["subject"], topic=row["topic"], revision=row["revision"])
                QuestionExam.objects.create(question=question, exam=result["exam"])
                values = row["values"]
                document = values["source_document"].strip()
                if document:
                    if document not in sources:
                        sources[document] = QuestionSource.objects.filter(source_document=document).order_by("pk").first() or QuestionSource.objects.create(source_name=document[:200], source_document=document)
                    QuestionSourceReference.objects.create(question=question, source=sources[document], source_page=values["source_page"].strip() or None)
                association = PaperQuestion(paper=paper, question_revision=question.current_revision,
                                            question_number=values["question_number"].strip(), display_order=next_order + offset)
                association.save(_import_draft=True)
                ImportedQuestion.objects.create(batch=batch, source_row_number=row["source_row"], question=question,
                    source_metadata={"original": data["rows"][row["index"]].get("original_values", values), "corrected": values})
            return batch
    except IntegrityError as error:
        existing = ImportBatch.objects.filter(staging_token=data["token"], uploaded_by=user).first()
        if existing:
            return existing
        raise ValidationError("A file or paper conflict was detected. Revalidate or choose the existing draft paper; no partial import was saved.") from error
