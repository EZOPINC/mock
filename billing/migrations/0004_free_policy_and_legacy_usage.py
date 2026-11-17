from django.db import migrations
from django.db.models import Exists, OuterRef


def configure_and_backfill(apps, schema_editor):
    alias = schema_editor.connection.alias
    Plan = apps.get_model("billing", "SubscriptionPlan")
    Entitlement = apps.get_model("billing", "PlanEntitlement")
    Subscription = apps.get_model("billing", "UserSubscription")
    ExamSelection = apps.get_model("billing", "FreeExamSelection")
    MockSelection = apps.get_model("billing", "FreeMockSelection")
    Usage = apps.get_model("billing", "FreeQuestionUsage")
    Session = apps.get_model("practice", "PracticeSession")
    Row = apps.get_model("practice", "PracticeQuestion")
    Attempt = apps.get_model("mock_tests", "MockAttempt")

    for feature, limit in (("mock", 1), ("practice", 50)):
        for plan in Plan.objects.using(alias).filter(tier="free"):
            Entitlement.objects.using(alias).update_or_create(plan=plan, feature=feature,
                defaults={"is_enabled": True, "usage_limit": limit, "usage_period": "lifetime"})

    # Current status/plan activity cannot reconstruct past access. Treat recorded
    # Premium terms as paid at delivery time even if cancelled/deactivated later.
    def free_history(model, time_field):
        premium = Subscription.objects.using(alias).filter(
            user_id=OuterRef("user_id"), plan__tier="premium",
            starts_at__lte=OuterRef(time_field), ends_at__gt=OuterRef(time_field))
        return model.objects.using(alias).annotate(was_premium=Exists(premium)).filter(was_premium=False)

    sessions = free_history(Session, "started_at").filter(kind="practice")
    attempts = free_history(Attempt, "created_at")
    user_ids = sessions.order_by().values_list("user_id", flat=True).union(attempts.order_by().values_list("user_id", flat=True))
    for user_id in user_ids.iterator():
        practice = sessions.filter(user_id=user_id)
        mocks = attempts.filter(user_id=user_id)
        first_practice = practice.order_by("started_at", "pk").first()
        first_mock = mocks.order_by("created_at", "pk").first()
        choices = []
        if first_practice:
            choices.append((first_practice.started_at, first_practice.exam_id))
        if first_mock:
            choices.append((first_mock.created_at, first_mock.pattern.exam_id))
        exam_id = min(choices)[1]
        ExamSelection.objects.using(alias).get_or_create(user_id=user_id, defaults={"exam_id": exam_id})
        mock = mocks.filter(pattern__exam_id=exam_id).order_by("created_at", "pk").first()
        if mock:
            MockSelection.objects.using(alias).get_or_create(user_id=user_id, defaults={"pattern_id": mock.pattern_id})
        question_ids = Row.objects.using(alias).filter(session_id__in=practice.values("pk")).order_by().values_list("question_id", flat=True).distinct()
        Usage.objects.using(alias).bulk_create([
            Usage(user_id=user_id, question_id=pk) for pk in question_ids
        ], batch_size=1000, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0003_freeexamselection_freemockselection_and_more"),
        ("practice", "0002_practicesession_kind_alter_practicesession_exam_and_more"),
    ]
    # Preserve lifetime allocations and staff configuration when unapplying this
    # data migration. Reapplying is idempotent; reversing the schema drops them.
    operations = [migrations.RunPython(configure_and_backfill, migrations.RunPython.noop)]
