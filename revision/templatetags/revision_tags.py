from urllib.parse import urlencode
from django import template
from django.urls import reverse

register = template.Library()


@register.inclusion_tag("revision/bookmark.html", takes_context=True)
def bookmark_control(context, row, anchor):
    request = context["request"]
    target = request.get_full_path() + "#" + str(anchor)
    return {"question_id": getattr(row, "question_id", row.pk), "is_saved": getattr(row, "is_saved", False),
            "authenticated": request.user.is_authenticated, "csrf_token": context.get("csrf_token"),
            "next": target, "login_url": reverse("accounts:login") + "?" + urlencode({"next": target})}


@register.inclusion_tag("revision/explore_control.html", takes_context=True)
def explore_control(context, question_id, anchor=""):
    request = context["request"]
    target = request.get_full_path() + ("#" + str(anchor) if anchor else "")
    return {"authenticated": request.user.is_authenticated,
            "explore_url": reverse("revision:question_topics", args=[question_id]),
            "login_url": reverse("accounts:login") + "?" + urlencode({"next": target})}
