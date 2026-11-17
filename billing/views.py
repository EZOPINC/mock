from uuid import uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_safe
from django.utils import timezone

from .models import PaymentOrder, RefundApproval, SubscriptionPlan
from .payments import create_order, replay_payment_event, simulate_payment
from .providers import require_simulator, simulation_enabled


def can_simulate(user):
    return (simulation_enabled() and user.is_authenticated and user.is_active and user.is_staff
            and user.has_perm("billing.run_simulated_payments") and user.has_perm("billing.manage_subscriptions"))


@never_cache
@require_safe
def pricing(request):
    return render(request, "billing/pricing.html", {
        "plans": SubscriptionPlan.objects.filter(is_active=True).prefetch_related("entitlements").order_by("tier", "duration_days"),
        "checkout_available": simulation_enabled(), "checkout_key": uuid4(),
        "orders": PaymentOrder.objects.filter(user=request.user).order_by("-created_at", "-pk")[:10]
                  if request.user.is_authenticated else []})


@login_required
@require_POST
def checkout(request, plan_id):
    plan = get_object_or_404(SubscriptionPlan, pk=plan_id)
    try:
        order = create_order(user=request.user, plan=plan, checkout_key=request.POST.get("checkout_key"))
    except ValidationError as error:
        return render(request, "billing/checkout_error.html", {"error": "; ".join(error.messages)}, status=400)
    return redirect("billing:status", reference=order.reference)


def owned_order(request, reference):
    return get_object_or_404(PaymentOrder.objects.select_related("subscription"), reference=reference, user=request.user)


@login_required
@never_cache
@require_safe
def status(request, reference):
    order = owned_order(request, reference)
    return render(request, "billing/status.html", {"order": order, "can_simulate": can_simulate(request.user),
        "simulation_key": uuid4(), "can_refund": request.user.has_perm("billing.approve_refunds")
            or RefundApproval.objects.filter(order=order).exists()})


@login_required
@never_cache
@require_safe
def confirmation(request, reference):
    order = owned_order(request, reference)
    if order.status != "paid" or not order.subscription_id:
        return redirect("billing:status", reference=order.reference)
    now = timezone.now()
    subscription = order.subscription
    if subscription.status != "active":
        term_state = subscription.get_status_display()
    elif subscription.ends_at <= now:
        term_state = "Expired"
    elif subscription.starts_at > now:
        term_state = "Scheduled"
    else:
        term_state = "Active"
    return render(request, "billing/confirmation.html", {"order": order, "term_state": term_state})


@login_required
@never_cache
@require_POST
def simulate(request, reference):
    if not simulation_enabled():
        raise Http404
    require_simulator(request.user)
    # Authorized test operators can confirm student orders; status/confirmation
    # pages themselves remain strictly owner-scoped.
    order = get_object_or_404(PaymentOrder, reference=reference)
    try:
        if request.POST.get("outcome") == "duplicate":
            replay_payment_event(actor=request.user, order=order)
        else:
            simulate_payment(actor=request.user, order=order, outcome=request.POST.get("outcome"),
                             event_key=request.POST.get("event_key"))
    except ValidationError as error:
        return render(request, "billing/checkout_error.html", {"error": "; ".join(error.messages)}, status=400)
    if order.user_id == request.user.pk:
        return redirect("billing:status", reference=order.reference)
    return render(request, "billing/simulation_result.html", {"reference": order.reference})
