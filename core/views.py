from django.db import DatabaseError, connection
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from exams.models import Exam, ExamAuthority


@require_safe
def home(request):
    catalogue = ExamAuthority.objects.filter(is_active=True).prefetch_related(
        Prefetch("exams", queryset=Exam.objects.filter(is_active=True), to_attr="available_exams"),
    )
    # Homepage editorial order only; database names and other discovery pages stay unchanged.
    layout = (
        ("WBPSC", (("WBCS", ()), ("Miscellaneous", ()), ("Clerkship", ()),
                   ("IDO", ()), ("ICDS", ()), ("School SI", ()), ("Panchayat", ()))),
        ("WBP/KP", (("WB SI", ("WBPSI",)), ("WB Constable", ("WBP Constable",)),
                    ("KP SI", ("KPSI",)), ("KP Constable", ()), ("Lady Constable", ()))),
        ("SSC", (("Primary TET", ()), ("Upper Primary TET", ()), ("SLST", ()))),
    )

    def key(value):
        return "".join(char for char in value.casefold() if char.isalnum())

    authorities = []
    for label, exam_order in layout:
        authority = next((item for item in catalogue
                          if key(label) in {key(item.name), key(item.code), key(item.slug)}), None)
        if authority is None:
            continue
        exams = []
        for exam_label, aliases in exam_order:
            names = {key(value) for value in (exam_label, *aliases)}
            matches = [exam for exam in authority.available_exams
                       if names & {key(exam.name), key(exam.code), key(exam.slug)}]
            if len(matches) == 1:
                exam = matches[0]
                exam.homepage_label = exam_label
                exams.append(exam)
        authority.available_exams = exams
        authorities.append(authority)
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
