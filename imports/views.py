from collections import Counter
from functools import wraps
from hashlib import sha256

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from exams.models import Exam, ExamStage, Subject, Topic
from . import staging
from .forms import UploadForm, ImportSubjectForm, ImportTopicForm
from .models import ImportBatch
from .parsing import MAX_CELL, columns_for, preview_page_size, parse_upload
from .permissions import require_import_permission
from .services import confirm_import
from .validation import map_key, normalized, validate
from .context import exam_ids, mode


HIDDEN_UPLOAD_FIELDS = {"paper", "subject", "topic", "acknowledge_existing"}


def replacement_initial(data):
    selection = data["selection"]
    paper = selection.get("paper", {})
    return {
        "import_type": mode(data),
        "worksheet": data["worksheet"] if data["filename"].lower().endswith(".xlsx") else "",
        "authority": selection.get("authority_id"),
        "exam": selection.get("exam_id"),
        "exams": exam_ids(data) if mode(data) == "general" else [],
        "exam_mapping": selection.get("exam_mapping", "selected"),
        "year": paper.get("year"),
        "stage": paper.get("stage_id"),
        "paper": selection.get("paper_id"),
        "paper_name": paper.get("paper_name"),
        "part": paper.get("part"),
        "session": paper.get("session"),
        "subject": selection.get("subject_id"),
        "topic": selection.get("topic_id"),
        "language": selection.get("language", ""),
    }


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
    initial = {"import_type": request.GET.get("type", "")}
    posted = request.POST.copy() if request.method == "POST" else None
    replacement = request.GET.get("replace")
    if replacement:
        original = staging.load(replacement, request.user)
        require_import_permission(request.user, mode(original))
        initial = replacement_initial(original)
        if posted is not None:
            for field in ("subject", "topic"):
                if initial[field] is not None:
                    posted.setdefault(field, str(initial[field]))
            same_paper = all(
                posted.get(field, "").strip() == str(initial[field] or "").strip()
                for field in ("import_type", "exam", "year", "stage", "paper_name", "part", "session")
            )
            if same_paper and initial["paper"] is not None:
                posted.setdefault("paper", str(initial["paper"]))
    form = UploadForm(posted, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            parsed = parse_upload(form.cleaned_data["file"], form.cleaned_data["worksheet"].strip())
            require_import_permission(request.user, form.cleaned_data["import_type"])
            for row in parsed["rows"]:
                row.setdefault("original_values", dict(row["values"]))
            data = staging.create(request.user, {**parsed, "selection": form.selection(), "subject_map": {}, "topic_map": {}})
        except ValidationError as error:
            form.add_error(None, "; ".join(error.messages))
        else:
            return redirect("imports:preview", token=data["token"])
    catalogue = {
        "exams": list(Exam.objects.values("id", "authority_id")),
        "stages": list(ExamStage.objects.values("id", "exam_id")),
    }
    fields = [field for field in form if field.name not in HIDDEN_UPLOAD_FIELDS]
    hidden_errors = [(field.label, field.errors) for field in form if field.name in HIDDEN_UPLOAD_FIELDS and field.errors]
    return render(request, "imports/upload.html", {
        "form": form, "fields": fields, "catalogue": catalogue, "hidden_errors": hidden_errors,
    })


def edit_page(request, data):
    # Only the explicit server-selected page is editable; browser-supplied row
    # IDs cannot move/create rows or change source-row identity.
    page = Paginator(data["rows"], preview_page_size(data)).get_page(request.POST.get("page", "1"))
    data["selection"]["acknowledge_existing"] = request.POST.get("acknowledge_existing") == "on"
    start = page.start_index() - 1
    for index in range(start, start + len(page.object_list)):
        values = data["rows"][index]["values"]
        for column in columns_for(data):
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
    result = validate(data)
    for group in [*result["groups"], *result["skipped_groups"]]:
        if not any(start <= row["index"] < start + len(page.object_list) for row in group["rows"]):
            continue
        if group.get("requires_pairing"):
            if request.POST.get(f"pair_{group['key']}") == "on":
                data.setdefault("pairings", {})[group["number"]] = group["signature"]
            else:
                data.setdefault("pairings", {}).pop(group["number"], None)
        key = f"duplicate_{group['key']}"
        if key in request.POST:
            choice = request.POST[key]
            decisions = data.setdefault("duplicate_decisions", {})
            if choice:
                allowed = {f"reuse:{revision.pk}" for revision in group.get("reuse_candidates", ())}
                if "signature" in group:
                    allowed.add("separate")
                if group.get("can_skip"):
                    allowed.add("skip")
                if not group.get("has_duplicates") or choice not in allowed:
                    raise ValidationError("The duplicate choice is no longer available. Revalidate the preview.")
                if choice == "skip":
                    decisions[group["number"]] = {"choice": "skip", "input_signature": group["input_signature"],
                                                 "matched_question_ids": group["matched_question_ids"]}
                else:
                    decisions[group["number"]] = {"signature": group["signature"], "choice": choice}
            else:
                decisions.pop(group["number"], None)
    return data


def issue_key(severity, message):
    return f"{severity}-{sha256(message.encode()).hexdigest()}"


def preview_issues(rows):
    groups = []
    for severity, label in (("errors", "Errors"), ("warnings", "Warnings")):
        counts = Counter(message for row in rows for message in set(row[severity]))
        if counts:
            groups.append((label, [(issue_key(severity, message), message, count)
                                   for message, count in sorted(counts.items())]))
    return groups


@importer
@require_http_methods(["GET", "POST"])
def preview(request, token):
    completed = ImportBatch.objects.filter(staging_token=token, uploaded_by=request.user).first()
    if completed:
        return redirect("imports:complete", batch_id=completed.pk)
    subject_form = ImportSubjectForm(prefix="new_subject")
    topic_form = ImportTopicForm(prefix="new_topic")
    if request.method == "POST":
        with staging.locked(token):
            data = staging.load(token, request.user)
            if request.POST.get("version") != staging.digest(data):
                raise ValidationError("This preview changed in another tab. Reload and revalidate your edits.")
            require_import_permission(request.user, mode(data))
            action = request.POST.get("action", "edit")
            if action in {"add_subject", "add_topic"}:
                permission = "exams.add_subject" if action == "add_subject" else "exams.add_topic"
                if not request.user.has_perm(permission):
                    raise PermissionDenied
                if action == "add_subject":
                    subject_form = ImportSubjectForm(request.POST, prefix="new_subject")
                    taxonomy_form = subject_form
                else:
                    topic_form = ImportTopicForm(request.POST, prefix="new_topic")
                    taxonomy_form = topic_form
                if taxonomy_form.is_valid():
                    try:
                        with transaction.atomic():
                            taxonomy_form.save()
                    except IntegrityError:
                        taxonomy_form.add_error(None, "This code or slug was just used by another record. Correct it and try again.")
                    else:
                        messages.success(request, "Taxonomy record added. Preview revalidated; check the resolved mappings before confirming.")
                        return redirect("imports:preview", token=token)
            elif action == "edit":
                data = edit_page(request, data)
                staging.save(data)
            else:
                raise ValidationError("Unsupported preview action.")
    else:
        data = staging.load(token, request.user)
    require_import_permission(request.user, mode(data))
    result = validate(data)
    rows = result["rows"]
    query = request.GET.get("q", "").strip().casefold()
    status = request.GET.get("status", "")
    issue_groups = preview_issues(rows)
    issues = {key: (key.split("-", 1)[0], text) for _, options in issue_groups for key, text, _ in options}
    issue = request.GET.get("issue", "")
    selected_issue = issues.get(issue)
    filtered = [row for row in rows
                if (not query or query in " ".join(row["values"].values()).casefold())
                and (status not in {"errors", "warnings"} or row[status])
                and (not selected_issue or selected_issue[1] in row[selected_issue[0]])]
    page = Paginator(filtered, preview_page_size(data)).get_page(request.GET.get("page", request.POST.get("page", "1")))
    # Filtered pages are read-only to keep server page indexes unambiguous.
    editable = not query and not status and not selected_issue
    visible_indices = {row["index"] for row in page}
    pairing_groups = [group for group in result["groups"] if group["requires_pairing"] and any(row["index"] in visible_indices for row in group["rows"])]
    duplicate_groups = [group for group in [*result["groups"], *result["skipped_groups"]] if group.get("has_duplicates")
                        and any(row["index"] in visible_indices for row in group["rows"])]
    for row in page:
        row["cells"] = [{"name": column, "value": row["values"].get(column, "")} for column in columns_for(data)]
    subject_mappings, topic_mappings = {}, {}
    for row in page:
        if row.get("skipped"):
            continue
        values = row["values"]
        key = normalized(values["subject"])
        subject_mappings[key] = {"value": values["subject"], "key": map_key(values["subject"]), "selected": data["subject_map"].get(key)}
        if values["topic"].strip():
            value = values["subject"] + " / " + values["topic"]
            topic_mappings[normalized(value)] = {"value": value, "key": map_key(value), "selected": data["topic_map"].get(normalized(value))}
    return render(request, "imports/preview.html", {
        "data": data, "result": result, "page": page, "columns": columns_for(data), "version": staging.digest(data),
        "subject_mappings": subject_mappings.values(), "topic_mappings": topic_mappings.values(),
        "subjects": Subject.objects.all(), "topics": Topic.objects.select_related("subject"),
        "editable": editable, "query": query, "status": status,
        "pairing_groups": pairing_groups, "duplicate_groups": duplicate_groups,
        "issue_groups": issue_groups, "issue": issue,
        "subject_form": subject_form, "topic_form": topic_form,
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
