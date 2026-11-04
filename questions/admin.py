from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import path, reverse

from . import services
from .forms import CONTENT_FIELDS, NewQuestionAdminForm, QuestionAdminForm, RevisionForm
from .models import Question, QuestionExam, QuestionRevision, QuestionSource, QuestionSourceReference


class QuestionExamInline(admin.TabularInline):
    model = QuestionExam
    extra = 0
    autocomplete_fields = ("exam",)


class QuestionSourceReferenceInline(admin.TabularInline):
    model = QuestionSourceReference
    extra = 0
    autocomplete_fields = ("source",)


class RevisionInline(admin.TabularInline):
    model = QuestionRevision
    fk_name = "question"
    fields = ("revision_number", "language", "question_text", "published_at")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    form = QuestionAdminForm
    change_form_template = "admin/questions/question/change_form.html"
    change_list_template = "admin/questions/question/change_list.html"
    list_display = ("id", "subject", "topic", "language", "publication_status", "review_status", "revision_number")
    list_filter = ("subject", "current_revision__language", "review_status", "publication_status", "exam_associations__exam")
    search_fields = ("current_revision__question_text", "published_revision__question_text", "source_question_id", "source_references__source__source_name", "source_references__source__source_document", "source_references__source_question_number")
    readonly_fields = ("publication_status", "review_status", "current_revision", "published_revision", "created_at", "updated_at")
    list_select_related = ("subject", "topic", "current_revision")
    inlines = (RevisionInline, QuestionExamInline, QuestionSourceReferenceInline)
    actions = ("review_questions", "publish_questions")

    @admin.display(description="Language")
    def language(self, obj):
        return obj.current_revision.get_language_display() if obj.current_revision_id else "—"

    @admin.display(description="Working revision")
    def revision_number(self, obj):
        return obj.current_revision.revision_number if obj.current_revision_id else "—"

    def get_form(self, request, obj=None, **kwargs):
        kwargs["form"] = QuestionAdminForm if obj else NewQuestionAdminForm
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
        else:
            question = services.create_question(
                subject=obj.subject, topic=obj.topic, source_question_id=obj.source_question_id,
                revision={field: form.cleaned_data[field] for field in CONTENT_FIELDS},
            )
            obj.__dict__.update(question.__dict__)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Mark working revisions as reviewed", permissions=["change"])
    def review_questions(self, request, queryset):
        self._transition(request, queryset, services.mark_reviewed, "reviewed")

    @admin.action(description="Publish reviewed working revisions", permissions=["change"])
    def publish_questions(self, request, queryset):
        self._transition(request, queryset, services.publish_question, "published")

    def _transition(self, request, queryset, operation, label):
        for question in queryset:
            if not self.has_change_permission(request, question):
                raise PermissionDenied
            try:
                operation(question, revision_id=question.current_revision_id)
            except ValidationError as error:
                self.message_user(request, f"{question}: {'; '.join(error.messages)}", messages.ERROR)
            else:
                self.message_user(request, f"{question}: {label}.", messages.SUCCESS)

    def get_urls(self):
        return [path("<int:object_id>/new-revision/", self.admin_site.admin_view(self.new_revision), name="questions_question_new_revision")] + super().get_urls()

    def new_revision(self, request, object_id):
        obj = self.get_object(request, str(object_id))
        if obj is None:
            raise Http404
        if not self.has_change_permission(request, obj):
            raise PermissionDenied
        initial = {field: getattr(obj.current_revision, field) for field in CONTENT_FIELDS} if obj.current_revision_id else {}
        form = RevisionForm(request.POST if request.method == "POST" else None, initial=initial)
        if request.method == "POST" and form.is_valid():
            try:
                services.create_revision(obj, **form.cleaned_data)
            except ValidationError as error:
                form.add_error(None, "; ".join(error.messages))
            else:
                self.message_user(request, "Draft revision created. Review and publish it explicitly.")
                return redirect(reverse("admin:questions_question_change", args=[obj.pk]))
        context = {
            **self.admin_site.each_context(request), "title": f"New revision for {obj}",
            "opts": self.model._meta, "original": obj, "form": form,
        }
        return render(request, "admin/questions/question/new_revision.html", context)


@admin.register(QuestionRevision)
class QuestionRevisionAdmin(admin.ModelAdmin):
    list_display = ("question", "revision_number", "language", "published_at")
    list_filter = ("language",)
    search_fields = ("question_text",)
    readonly_fields = tuple(field.name for field in QuestionRevision._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(QuestionSource)
class QuestionSourceAdmin(admin.ModelAdmin):
    list_display = ("source_name", "source_document", "created_at")
    search_fields = ("source_name", "source_document")
    readonly_fields = ("created_at",)


@admin.register(QuestionExam)
class QuestionExamAdmin(admin.ModelAdmin):
    list_display = ("question", "exam")
    list_filter = ("exam",)
    autocomplete_fields = ("question", "exam")


@admin.register(QuestionSourceReference)
class QuestionSourceReferenceAdmin(admin.ModelAdmin):
    list_display = ("question", "source", "source_page", "source_question_number")
    search_fields = ("source__source_name", "source__source_document", "source_question_number")
    autocomplete_fields = ("question", "source")
