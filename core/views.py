from django.db import DatabaseError, connection
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from exams.models import Exam, ExamAuthority


@require_safe
def home(request):
    authorities = ExamAuthority.objects.filter(is_active=True).prefetch_related(
        Prefetch("exams", queryset=Exam.objects.filter(is_active=True), to_attr="available_exams"),
    )
    return render(request, "core/home.html", {"authorities": authorities})


@never_cache
@require_safe
def health(request):
    """Readiness probe: return 503 when PostgreSQL is unavailable."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
