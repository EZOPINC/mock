from django.db import migrations


def backfill(apps, schema_editor):
    Revision = apps.get_model("questions", "QuestionRevision")
    Translation = apps.get_model("questions", "QuestionTranslation")
    Question = apps.get_model("questions", "Question")
    alias = schema_editor.connection.alias
    fields = ("question_text", "option_a", "option_b", "option_c", "option_d", "explanation")
    pending = []
    for revision in Revision.objects.using(alias).iterator(chunk_size=500):
        pending.append(Translation(revision_id=revision.pk, question_id=revision.question_id, language=revision.language,
            **{field: getattr(revision, field) for field in fields}))
        if len(pending) == 500:
            Translation.objects.using(alias).bulk_create(pending, ignore_conflicts=True)
            pending = []
    if pending:
        Translation.objects.using(alias).bulk_create(pending, ignore_conflicts=True)
    pending = []
    for question in Question.objects.using(alias).select_related("current_revision").iterator(chunk_size=500):
        if question.current_revision_id:
            question.correct_answer = question.current_revision.correct_answer
            question.difficulty_level = question.current_revision.difficulty_level
            pending.append(question)
        if len(pending) == 500:
            Question.objects.using(alias).bulk_update(pending, ["correct_answer", "difficulty_level"])
            pending = []
    if pending:
        Question.objects.using(alias).bulk_update(pending, ["correct_answer", "difficulty_level"])


class Migration(migrations.Migration):
    dependencies = [("questions", "0002_questiontranslation_and_more")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
