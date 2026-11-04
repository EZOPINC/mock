from functools import wraps

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from exams.models import Exam, ExamStage, Subject, Topic
from previous_year.models import PreviousYearPaper
from . import staging
from .forms import UploadForm
from .models import ImportBatch
from .parsing import COLUMNS, MAX_CELL, parse_upload
from .permissions import require_import_permission
from .services import confirm_import
from .validation import map_key, normalized, validate
from .context import mode


def importer(view):
    @staff_member_required
    @never_cache
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        require_import_permission(request.user)
        try:
            return view(request, *args, **kwargs)
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
            return redirect("imports:upload")
    return wrapped


@importer
@require_http_methods(["GET", "POST"])
def upload(request):
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            parsed = parse_upload(form.cleaned_data["file"], form.cleaned_data["worksheet"].strip())
            require_import_permission(request.user, form.cleaned_data["import_type"])
            for row in parsed["rows"]:
                row["original_values"] = dict(row["values"])
            data = staging.create(request.user, {**parsed, "selection": form.selection(), "subject_map": {}, "topic_map": {}})
        except ValidationError as error:
            form.add_error(None, "; ".join(error.messages))
        else:
            return redirect("imports:preview", token=data["token"])
    catalogue = {
        "exams": list(Exam.objects.values("id", "authority_id")),
        "stages": list(ExamStage.objects.values("id", "exam_id")),
        "papers": list(PreviousYearPaper.objects.filter(is_published=False).values("id", "exam_id")),
        "topics": list(Topic.objects.values("id", "subject_id")),
    }
    return render(request, "imports/upload.html", {"form": form, "catalogue": catalogue})


def edit_page(request, data):
    # Only the explicit server-selected page is editable; browser-supplied row
    # IDs cannot move/create rows or change source-row identity.
    page = Paginator(data["rows"], 25).get_page(request.POST.get("page", "1"))
    data["selection"]["acknowledge_existing"] = request.POST.get("acknowledge_existing") == "on"
    start = page.start_index() - 1
    for index in range(start, start + len(page.object_list)):
        values = data["rows"][index]["values"]
        for column in COLUMNS:
            key = f"row_{index}_{column}"
            if key in request.POST:
                value = request.POST[key]
                if len(value) > MAX_CELL:
                    raise ValidationError("Edited cell exceeds the maximum length.")
                values[column] = value
    for field in ("exam_aliases", "paper_aliases"):
        if field in request.POST:
            if len(request.POST[field]) > 4000:
                raise ValidationError("Alias lists must not exceed 4000 characters.")
            data["selection"][field] = request.POST[field]
    for row in data["rows"]:
        values = row["values"]
        for kind, value in (("subject", values["subject"]), ("topic", values["subject"] + " / " + values["topic"])):
            posted = request.POST.get(f"{kind}map_{map_key(value)}")
            if posted is not None:
                if not posted:
                    data[f"{kind}_map"].pop(normalized(value), None)
                    continue
                if not posted.isdigit():
                    raise ValidationError("Invalid taxonomy mapping.")
                data[f"{kind}_map"][normalized(value)] = int(posted)
    return data


@importer
@require_http_methods(["GET", "POST"])
def preview(request, token):
    completed = ImportBatch.objects.filter(staging_token=token, uploaded_by=request.user).first()
    if completed:
        return redirect("imports:complete", batch_id=completed.pk)
    if request.method == "POST":
        with staging.locked(token):
            data = staging.load(token, request.user)
            if request.POST.get("version") != staging.digest(data):
                raise ValidationError("This preview changed in another tab. Reload and revalidate your edits.")
            data = edit_page(request, data)
            staging.save(data)
    else:
        data = staging.load(token, request.user)
    require_import_permission(request.user, mode(data))
    result = validate(data)
    rows = result["rows"]
    query = request.GET.get("q", "").strip().casefold()
    status = request.GET.get("status", "")
    filtered = [row for row in rows if (not query or query in " ".join(row["values"].values()).casefold()) and (status != "errors" or row["errors"]) and (status != "warnings" or row["warnings"])]
    page = Paginator(filtered, 25).get_page(request.GET.get("page", request.POST.get("page", "1")))
    # Filtered pages are read-only to keep server page indexes unambiguous.
    editable = not query and not status
    for row in page:
        row["cells"] = [{"name": column, "value": row["values"][column]} for column in COLUMNS]
    subject_mappings, topic_mappings = {}, {}
    for row in page:
        values = row["values"]
        key = normalized(values["subject"])
        subject_mappings[key] = {"value": values["subject"], "key": map_key(values["subject"]), "selected": data["subject_map"].get(key)}
        if values["topic"].strip():
            value = values["subject"] + " / " + values["topic"]
            topic_mappings[normalized(value)] = {"value": value, "key": map_key(value), "selected": data["topic_map"].get(normalized(value))}
    return render(request, "imports/preview.html", {
        "data": data, "result": result, "page": page, "columns": COLUMNS, "version": staging.digest(data),
        "subject_mappings": subject_mappings.values(), "topic_mappings": topic_mappings.values(),
        "subjects": Subject.objects.all(), "topics": Topic.objects.select_related("subject"),
        "editable": editable, "query": query, "status": status,
    })


@importer
@require_POST
def confirm(request, token):
    completed = ImportBatch.objects.filter(staging_token=token, uploaded_by=request.user).first()
    if completed:
        return redirect("imports:complete", batch_id=completed.pk)
    with staging.locked(token):
        data = staging.load(token, request.user)
        if request.POST.get("version") != staging.digest(data):
            messages.error(request, "This preview changed. Revalidate before confirming.")
            return redirect("imports:preview", token=token)
        try:
            batch = confirm_import(data, request.user)
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
            return redirect("imports:preview", token=token)
        staging.path_for(token).unlink(missing_ok=True)
    return redirect("imports:complete", batch_id=batch.pk)


@importer
@require_POST
def cancel(request, token):
    with staging.locked(token):
        staging.load(token, request.user)
        staging.path_for(token).unlink(missing_ok=True)
    messages.success(request, "Import preview cancelled. No questions were inserted.")
    return redirect("imports:upload")


@importer
@require_http_methods(["GET"])
def complete(request, batch_id):
    batch = get_object_or_404(ImportBatch.objects.select_related("paper__exam__authority"), pk=batch_id, uploaded_by=request.user)
    return render(request, "imports/complete.html", {"batch": batch, "records": batch.imported_questions.select_related("question")})
