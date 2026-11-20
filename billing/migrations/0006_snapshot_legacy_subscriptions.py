from django.db import migrations


def snapshot_legacy(apps, schema_editor):
    Subscription = apps.get_model("billing", "UserSubscription")
    alias = schema_editor.connection.alias
    for subscription in Subscription.objects.using(alias).filter(plan_snapshot={}).select_related("plan").iterator():
        plan = subscription.plan
        Subscription.objects.using(alias).filter(pk=subscription.pk).update(plan_snapshot={
            "code": plan.code, "name": plan.name, "tier": plan.tier, "price": str(plan.price),
            "currency": plan.currency, "duration_days": plan.duration_days,
            "source": "legacy_current_configuration",
        })


class Migration(migrations.Migration):
    dependencies = [("billing", "0005_subscriptionevent_alter_usersubscription_options_and_more")]
    # Original prices were not recorded before B3. Mark these as inferred current
    # configuration; do not invent historical prices or administrative actors.
    operations = [migrations.RunPython(snapshot_legacy, migrations.RunPython.noop)]
