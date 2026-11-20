from django.contrib import admin, messages
from django import forms
from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS, PermissionDenied, ValidationError
from django.db.models import Count, F, Q
from django.forms.models import BaseInlineFormSet
from django.http import Http404
from django.shortcuts import render
from django.urls import path, reverse
from urllib.parse import urlencode

from questions.models import QuestionRevision
from .models import PaperQuestion, PreviousYearPaper, QuestionAppearance
from .services import publish_paper, unpublish_paper


def selectable_revisions(paper=None):
    valid = Q(published_at__isnull=False, pk=F(
        "question__published_revision_id"), question__publication_status="published")
    if paper:
        valid &= Q(question__exam_associations__exam_id=paper.exam_id)
        valid |= Q(pk__in=paper.paper_questions.values("question_revision_id"))
    return QuestionRevision.objects.filter(valid).distinct()


class PaperQuestionFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        identities = set()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            row = form.instance
            row.paper = self.instance
            try:
                row.validate_association(
                    require_current=not row.pk or "question_revision" in form.changed_data)
            except ValidationError as error:
                raise ValidationError(error.messages) from error
            identity = row.question_revision.question_id
            if identity in identities:
                raise ValidationError(
                    "A question cannot appear more than once in a paper.")
            identities.add(identity)
        if self.instance.expected_question_count is not None and len(identities) > self.instance.expected_question_count:
            raise ValidationError(
                f"The paper declares {self.instance.expected_question_count} questions but the inline contains {len(identities)}.")


class PaperQuestionInline(admin.TabularInline):
    model = PaperQuestion
    formset = PaperQuestionFormSet
    fields = ("question_revision", "question_number", "display_order")
    extra = 0
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return not (obj and obj.is_published) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return not (obj and obj.is_published) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not (obj and obj.is_published) and super().has_delete_permission(request, obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "question_revision":
            object_id = request.resolver_match.kwargs.get(
                "object_id") if request.resolver_match else None
            paper = PreviousYearPaper.objects.filter(pk=object_id).first(
            ) if object_id and str(object_id).isdigit() else None
            kwargs["queryset"] = selectable_revisions(paper)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(PreviousYearPaper)
class PreviousYearPaperAdmin(admin.ModelAdmin):
    list_display = ("paper_name", "exam", "stage", "year",
                    "subject", "question_count_status", "is_published")
    list_filter = ("exam__authority", "exam", "stage",
                   "year", "subject", "is_published")
    search_fields = ("paper_name", "exam__name",
                     "exam__code", "part", "session")
    list_select_related = ("exam__authority", "stage", "subject")
    ordering = ("-year", "paper_name")
    readonly_fields = ("is_published", "created_at", "question_count_status")
    inlines = (PaperQuestionInline,)
    actions = ("publish_selected", "unpublish_selected")
    change_form_template = "admin/previous_year/previousyearpaper/change_form.html"
    fieldsets = (
        ("Paper identity", {"fields": ("exam", "stage",
         "year", "paper_name", "part", "session")}),
        ("Optional paper configuration", {"fields": (
            "subject", "duration_minutes", "total_marks", "instructions", "expected_question_count", "question_count_status")}),
        ("Publication", {"fields": ("is_published", "created_at")}),
    )

    def get_inline_instances(self, request, obj=None):
        instances = super().get_inline_instances(request, obj)
        request.paper_question_overflow = None
        limit = settings.DATA_UPLOAD_MAX_NUMBER_FIELDS
        if obj is None or limit is None:
            return instances
        visible = []
        for inline in instances:
            formset = inline.get_formset(request, obj)
            count = inline.get_queryset(request).filter(
                **{formset.fk.name: obj.pk}).count()
            # Parent/CSRF/save controls reserve 64 fields. Include hidden ID/FK/
            # deletion fields, the add-row template and management inputs.
            needed = (count + inline.get_extra(request, obj) + 1) * \
                (len(formset.form.base_fields) + 3) + 4
            if needed <= max(0, limit - 64):
                visible.append(inline)
            else:
                request.paper_question_overflow = {
                    "count": count,
                    "url": reverse("admin:previous_year_paperquestion_changelist") + "?" + urlencode({"paper__id__exact": obj.pk}),
                }
        return visible

    def render_change_form(self, request, context, *args, **kwargs):
        context["paper_question_overflow"] = getattr(
            request, "paper_question_overflow", None)
        return super().render_change_form(request, context, *args, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return fields + ("exam", "stage", "year", "paper_name", "part", "session", "duration_minutes", "total_marks", "instructions", "subject", "expected_question_count") if obj and obj.is_published else fields

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(linked_question_count=Count("paper_questions", distinct=True))

    @admin.display(description="Questions (actual / expected)")
    def question_count_status(self, obj):
        if not obj or not obj.pk:
            return "0 / not specified"
        actual = getattr(obj, "linked_question_count", None)
        if actual is None:
            actual = obj.paper_questions.count()
        expected = obj.expected_question_count
        return f"{actual} / {expected if expected is not None else 'not specified'}" + (" (incomplete)" if expected is not None and actual != expected else "")

    def has_delete_permission(self, request, obj=None):
        return not (obj and obj.is_published) and super().has_delete_permission(request, obj)

    @admin.action(description="Publish validated papers", permissions=["change"])
    def publish_selected(self, request, queryset):
        self.transition(request, queryset, publish_paper, "published")

    @admin.action(description="Unpublish papers", permissions=["change"])
    def unpublish_selected(self, request, queryset):
        self.transition(request, queryset, unpublish_paper, "unpublished")

    def transition(self, request, queryset, operation, label):
        for paper in queryset:
            if not self.has_change_permission(request, paper):
                raise PermissionDenied
            try:
                operation(paper)
            except ValidationError as error:
                self.message_user(
                    request, f"{paper}: {'; '.join(error.messages)}", messages.ERROR)
            else:
                self.message_user(
                    request, f"{paper}: {label}.", messages.SUCCESS)

    def get_urls(self):
        return [path("<int:object_id>/preview/", self.admin_site.admin_view(self.preview), name="previous_year_previousyearpaper_preview")] + super().get_urls()

    def preview(self, request, object_id):
        paper = self.get_object(request, str(object_id))
        if paper is None:
            raise Http404
        if not self.has_view_or_change_permission(request, paper):
            raise PermissionDenied
        return render(request, "previous_year/paper_detail.html", {"paper": paper, "exam": paper.exam, "is_preview": True})


class PaperQuestionAdminForm(forms.ModelForm):
    class Meta:
        model = PaperQuestion
        fields = ("paper", "question_revision",
                  "question_number", "display_order")

    def _update_errors(self, errors):
        # Paper-level validators can name expected_question_count, which is not
        # an association field. Keep that validation visible as a form error.
        if hasattr(errors, "error_dict"):
            mapped = {}
            for field, messages in errors.error_dict.items():
                target = field if field in self.fields else NON_FIELD_ERRORS
                mapped.setdefault(target, []).extend(messages)
            errors = ValidationError(mapped)
        super()._update_errors(errors)


@admin.register(PaperQuestion)
class PaperQuestionAdmin(admin.ModelAdmin):
    form = PaperQuestionAdminForm
    list_display = ("question_number", "paper", "question",
                    "question_revision", "display_order")
    list_filter = ("paper",)
    list_select_related = ("paper__exam__authority",
                           "question", "question_revision")
    search_fields = ("question_number", "paper__paper_name",
                     "question_revision__translations__question_text")
    fields = ("paper", "question_revision", "question",
              "question_number", "display_order")
    readonly_fields = ("question",)
    list_per_page = 25
    actions = None

    def parent_admin(self):
        return self.admin_site.get_model_admin(PreviousYearPaper)

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and self.parent_admin().has_view_or_change_permission(request, obj.paper if obj else None)

    def has_add_permission(self, request):
        return super().has_add_permission(request) and self.parent_admin().has_change_permission(request)

    def has_change_permission(self, request, obj=None):
        return (super().has_change_permission(request, obj) and not (obj and obj.paper.is_published)
                and self.parent_admin().has_change_permission(request, obj.paper if obj else None))

    def has_delete_permission(self, request, obj=None):
        return (super().has_delete_permission(request, obj) and not (obj and obj.paper.is_published)
                and self.parent_admin().has_change_permission(request, obj.paper if obj else None))

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return (*fields, "paper") if obj else fields

    def get_form(self, request, obj=None, **kwargs):
        paper_id = request.POST.get(
            "paper") if request.method == "POST" else request.GET.get("paper")
        request.paper_question_parent = obj.paper if obj else (
            PreviousYearPaper.objects.filter(pk=paper_id).first() if paper_id and str(paper_id).isdigit() else None)
        return super().get_form(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "question_revision":
            kwargs["queryset"] = selectable_revisions(
                getattr(request, "paper_question_parent", None))
        elif db_field.name == "paper":
            kwargs["queryset"] = PreviousYearPaper.objects.filter(
                is_published=False).select_related("exam__authority")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(QuestionAppearance)
class QuestionAppearanceAdmin(admin.ModelAdmin):
    list_display = ("question", "exam_name", "authority_name", "year",
                    "stage", "session", "question_number", "verified_at", "verified_by")
    list_filter = ("exam_name", "authority_name", "year", "stage", "session")
    search_fields = ("question__translations__question_text", "exam_name",
                     "authority_name", "stage", "session", "question_number")
    ordering = ("-year", "exam_name")
    readonly_fields = ("identity", "updated_at")
    fieldsets = (
        (None, {"fields": ("question",)}),
        ("Appearance details", {"fields": (
            "exam_name", "authority_name", "year", "stage", "session", "question_number")}),
        ("Verification details", {"fields": ("verified_at", "verified_by")}),
        ("System fields (read-only)", {"fields": ("identity", "updated_at")}),
    )
