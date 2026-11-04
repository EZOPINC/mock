from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import F, Q
from django.forms.models import BaseInlineFormSet
from django.http import Http404
from django.shortcuts import render
from django.urls import path

from questions.models import QuestionRevision
from .models import PaperQuestion, PreviousYearPaper
from .services import publish_paper, unpublish_paper


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
                row.validate_association(require_current=not row.pk or "question_revision" in form.changed_data)
            except ValidationError as error:
                raise ValidationError(error.messages) from error
            identity = row.question_revision.question_id
            if identity in identities:
                raise ValidationError("A question cannot appear more than once in a paper.")
            identities.add(identity)


class PaperQuestionInline(admin.TabularInline):
    model = PaperQuestion
    formset = PaperQuestionFormSet
    fields = ("question_revision", "question_number", "display_order")
    extra = 0

    def has_add_permission(self, request, obj=None):
        return not (obj and obj.is_published) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return not (obj and obj.is_published) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not (obj and obj.is_published) and super().has_delete_permission(request, obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "question_revision":
            valid = Q(published_at__isnull=False, pk=F("question__published_revision_id"), question__publication_status="published")
            object_id = request.resolver_match.kwargs.get("object_id") if request.resolver_match else None
            paper = PreviousYearPaper.objects.filter(pk=object_id).first() if object_id and str(object_id).isdigit() else None
            if paper:
                valid &= Q(question__exam_associations__exam_id=paper.exam_id)
                valid |= Q(pk__in=paper.paper_questions.values("question_revision_id"))
            kwargs["queryset"] = QuestionRevision.objects.filter(valid).distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(PreviousYearPaper)
class PreviousYearPaperAdmin(admin.ModelAdmin):
    list_display = ("paper_name", "exam", "stage", "year", "part", "session", "is_published")
    list_filter = ("exam__authority", "exam", "stage", "year", "is_published")
    search_fields = ("paper_name", "exam__name", "exam__code", "part", "session")
    list_select_related = ("exam__authority", "stage")
    ordering = ("-year", "paper_name")
    readonly_fields = ("is_published", "created_at")
    inlines = (PaperQuestionInline,)
    actions = ("publish_selected", "unpublish_selected")
    change_form_template = "admin/previous_year/previousyearpaper/change_form.html"

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return fields + ("exam", "stage", "year", "paper_name", "part", "session") if obj and obj.is_published else fields

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
                self.message_user(request, f"{paper}: {'; '.join(error.messages)}", messages.ERROR)
            else:
                self.message_user(request, f"{paper}: {label}.", messages.SUCCESS)

    def get_urls(self):
        return [path("<int:object_id>/preview/", self.admin_site.admin_view(self.preview), name="previous_year_previousyearpaper_preview")] + super().get_urls()

    def preview(self, request, object_id):
        paper = self.get_object(request, str(object_id))
        if paper is None:
            raise Http404
        if not self.has_view_or_change_permission(request, paper):
            raise PermissionDenied
        return render(request, "previous_year/paper_detail.html", {"paper": paper, "exam": paper.exam, "is_preview": True})
