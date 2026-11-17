from django.contrib.auth.models import Group, Permission

ROLE_PERMISSIONS = {
    "Billing financial viewer": ["view_financial_records"],
    "Billing plan manager": ["manage_plans"],
    "Billing refund approver": ["view_financial_records", "approve_refunds"],
    "Billing Premium granter": ["grant_premium", "view_usersubscription", "view_subscriptionplan"],
    "Billing finance operator": ["view_financial_records", "issue_billing_documents", "reconcile_financial_records", "export_financial_records"],
    "Billing configuration reviewer": ["view_financial_records", "manage_financial_configuration"],
}


def configure_roles():
    """Explicitly managed groups; never enroll users or grant simulator access."""
    for name, codes in ROLE_PERMISSIONS.items():
        permissions = list(Permission.objects.filter(content_type__app_label="billing", codename__in=codes))
        if len(permissions) != len(codes):
            raise ValueError("Apply billing migrations before configuring roles.")
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set(permissions)
