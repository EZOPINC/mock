from django.db import migrations


def seed_plans(apps, schema_editor):
    Plan = apps.get_model("billing", "SubscriptionPlan")
    Entitlement = apps.get_model("billing", "PlanEntitlement")
    alias = schema_editor.connection.alias
    free, _ = Plan.objects.using(alias).get_or_create(code="free", defaults={
        "name": "Free", "tier": "free", "price": 0, "currency": "INR", "is_active": True})
    plans = [free]
    for days in (30, 90, 365):
        plan, _ = Plan.objects.using(alias).get_or_create(code=f"premium-{days}", defaults={
            "name": f"Premium {days} days", "tier": "premium", "price": 0,
            "currency": "INR", "duration_days": days, "is_active": False})
        plans.append(plan)
    for plan in plans:
        for feature in ("mock", "practice", "revision"):
            Entitlement.objects.using(alias).get_or_create(plan=plan, feature=feature, defaults={
                "is_enabled": True, "usage_limit": None, "usage_period": "lifetime"})


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]
    # Retain staff configuration on reversal; schema reversal drops these tables.
    operations = [migrations.RunPython(seed_plans, migrations.RunPython.noop)]
