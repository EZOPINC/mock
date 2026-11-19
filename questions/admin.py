from datetime import timedelta

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone

from . import services
from .tagging import set_question_topics
from .forms import CONTENT_FIELDS, NewQuestionAdminForm, QuestionAdminForm, RevisionForm, TranslationForm
from .models import Question, QuestionExam, QuestionKind, QuestionRevision, QuestionSource, QuestionSourceReference, QuestionTranslation, TRANSLATED_FIELDS


def label_parent_paths(model):
    """All FKs used by taxonomy/Exam __str__, including skipped parent levels."""
    parents = list(getattr(model, "parent_fields", ()))
    if any(field.name == "subject" for field in model._meta.fields):
        parents.insert(0, "subject")
    if model._meta.label == "exams.Exam":
        parents.append("authority")
    paths = []
    for parent in parents:
        paths.append(parent)
        parent_model = model._meta.get_field(parent).remote_field.model
        paths.extend(parent + "__" + path for path in label_parent_paths(parent_model))
    return tuple(paths)


class LabelLoadedRelatedFilter(admin.RelatedFieldListFilter):
    """Keep Django's FK filter semantics without per-choice parent lookups."""
    related_only = False

    def field_choices(self, field, request, model_admin):
        queryset = field.remote_field.model._default_manager.complex_filter(field.get_limit_choices_to())
        if self.related_only:
            referenced = model_admin.get_queryset(request).distinct().values_list(self.field_path + "__pk", flat=True)
            queryset = queryset.filter(pk__in=referenced)
        ordering = self.field_admin_ordering(field, request, model_admin)
        if ordering:
            queryset = queryset.order_by(*ordering)
        paths = label_parent_paths(field.remote_field.model)
        if paths:
            queryset = queryset.select_related(*paths)
        return [(getattr(node, field.target_field.attname), str(node)) for node in queryset]


class LabelLoadedRelatedOnlyFilter(LabelLoadedRelatedFilter):
    related_only = True


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
    fields = ("revision_number", "language", "primary_text", "published_at")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("translations")

    @admin.display(description="Question text")
    def primary_text(self, revision):
        edition = revision.primary_translation
        return edition.question_text if edition else ""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class TranslationInline(admin.TabularInline):
    model = QuestionTranslation
    fk_name = "revision"
    fields = ("language", "question_text", "option_a",
              "option_b", "option_c", "option_d", "explanation")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class QuestionTranslationInline(TranslationInline):
    fk_name = "question"
    fields = ("revision", *TranslationInline.fields)
    readonly_fields = fields
    ordering = ("-revision__revision_number", "language")


class QuestionExpiryFilter(admin.SimpleListFilter):
    title = "Selection expiry"
    parameter_name = "selection_expiry"

    def lookups(self, request, model_admin):
        return (
            ("current", "Current"), ("soon", "Expiring within 30 days"),
            ("expired", "Expired"), ("missing", "Missing expiry"),
        )

    def queryset(self, request, queryset):
        today = timezone.localdate()
        conditions = {
            "current": {"expires_on__gt": today},
            "soon": {"expires_on__gt": today, "expires_on__lte": today + timedelta(days=30)},
            "expired": {"expires_on__lte": today},
            "missing": {"expires_on__isnull": True},
        }
        if self.value() in conditions:
            return queryset.filter(subject__question_freshness_years__isnull=False, **conditions[self.value()])
        return queryset


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    form = QuestionAdminForm
    change_form_template = "admin/questions/question/change_form.html"
    change_list_template = "admin/questions/question/change_list.html"
    list_display = ("id", "subject", "topic", "language",
                    "question_kind", "expires_on", "publication_status", "review_status", "revision_number")
    list_filter = (
        *((field, LabelLoadedRelatedFilter) for field in (
            "subject", "topic__chapter__module__part", "topic__chapter__module", "topic__chapter__submodule",
            "topic__chapter", "topic")),
        ("topic_associations__topic", LabelLoadedRelatedOnlyFilter),
        "current_revision__translations__language", "question_kind", QuestionExpiryFilter, "review_status", "publication_status",
        ("exam_associations__exam", LabelLoadedRelatedFilter),
    )
    search_fields = ("current_revision__translations__question_text", "published_revision__translations__question_text", "source_question_id",
                     "source_references__source__source_name", "source_references__source__source_document", "source_references__source_question_number")
    readonly_fields = ("publication_status", "review_status",
                       "current_revision", "published_revision", "created_at", "updated_at")
    list_select_related = ("subject", "current_revision", "topic", *(
        "topic__" + path for path in label_parent_paths(Question._meta.get_field("topic").remote_field.model)))
    inlines = (RevisionInline, QuestionExamInline,
               QuestionSourceReferenceInline, QuestionTranslationInline)
    actions = ("review_questions", "publish_questions", "classify_logical", "classify_static", "fill_missing_expiry")

    class Media:
        js = ("js/admin-question-topics.js",)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        primary = form.cleaned_data.get("topic")
        topics = [topic.pk for topic in form.cleaned_data.get(
            "additional_topics", [])]
        if primary:
            topics.append(primary.pk)
        set_question_topics(form.instance, topics,
                            primary_topic_id=primary.pk if primary else None)

    @admin.display(description="Language")
    def language(self, obj):
        return ", ".join(item.get_language_display() for item in obj.current_revision.translations.all()) if obj.current_revision_id else "—"

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("current_revision__translations")

    @admin.display(description="Working revision")
    def revision_number(self, obj):
        return obj.current_revision.revision_number if obj.current_revision_id else "—"

    def get_form(self, request, obj=None, **kwargs):
        kwargs["form"] = QuestionAdminForm if obj else NewQuestionAdminForm
        return super().get_form(request, obj, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return fields + ("correct_answer", "difficulty_level") if obj else fields

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
        else:
            question = services.create_question(
                subject=obj.subject, topic=obj.topic, source_question_id=obj.source_question_id,
                revision={field: form.cleaned_data[field]
                          for field in CONTENT_FIELDS},
                difficulty_level=form.cleaned_data.get("difficulty_level", ""),
                question_kind=obj.question_kind, current_as_of=obj.current_as_of, expires_on=obj.expires_on,
            )
            obj.__dict__.update(question.__dict__)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Set missing expiry from current-as-of or question creation date", permissions=["change"])
    def fill_missing_expiry(self, request, queryset):
        questions = queryset.filter(expires_on__isnull=True, subject__question_freshness_years__isnull=False)
        count = 0
        for question in questions.select_related(None).prefetch_related(None).iterator():
            if self.has_change_permission(request, question):
                count += services.set_missing_expiry(question)
        self.message_user(request, f"Set expiry for {count} questions.", messages.SUCCESS)

    @admin.action(description="Classify as Logical", permissions=["change"])
    def classify_logical(self, request, queryset):
        self._classify(request, queryset, QuestionKind.LOGICAL)

    @admin.action(description="Classify as Static", permissions=["change"])
    def classify_static(self, request, queryset):
        self._classify(request, queryset, QuestionKind.STATIC)

    def _classify(self, request, queryset, kind):
        count = 0
        for question in queryset.select_related(None).prefetch_related(None).iterator():
            if not self.has_change_permission(request, question):
                raise PermissionDenied
            services.set_question_kind(question, kind)
            count += 1
        self.message_user(request, f"Classified {count} questions as {kind.label}.", messages.SUCCESS)

    @admin.action(description="Mark working revisions as reviewed", permissions=["change"])
    def review_questions(self, request, queryset):
        self._transition(request, queryset, services.mark_reviewed, "reviewed")

    @admin.action(description="Publish reviewed working revisions", permissions=["change"])
    def publish_questions(self, request, queryset):
        self._transition(request, queryset,
                         services.publish_question, "published")

    def _transition(self, request, queryset, operation, label):
        for question in queryset:
            if not self.has_change_permission(request, question):
                raise PermissionDenied
            try:
                operation(question, revision_id=question.current_revision_id)
            except ValidationError as error:
                self.message_user(
                    request, f"{question}: {'; '.join(error.messages)}", messages.ERROR)
            else:
                self.message_user(
                    request, f"{question}: {label}.", messages.SUCCESS)

    def get_urls(self):
        return [path("<int:object_id>/new-revision/", self.admin_site.admin_view(self.new_revision), name="questions_question_new_revision"),
                path("<int:object_id>/translation/", self.admin_site.admin_view(self.new_translation), name="questions_question_translation")] + super().get_urls()

    def new_translation(self, request, object_id):
        obj = self.get_object(request, str(object_id))
        if obj is None:
            raise Http404
        if not self.has_change_permission(request, obj):
            raise PermissionDenied
        form = TranslationForm(
            request.POST if request.method == "POST" else None)
        if request.method == "POST" and form.is_valid():
            try:
                services.add_translation(obj, **form.cleaned_data)
            except ValidationError as error:
                form.add_error(None, "; ".join(error.messages))
            else:
                self.message_user(
                    request, "Translation added in a new pending-review revision. Existing live content is unchanged.")
                return redirect("admin:questions_question_change", object_id=obj.pk)
        return render(request, "admin/questions/question/new_revision.html", {
            **self.admin_site.each_context(request), "title": f"Add/update translation for {obj}",
            "opts": self.model._meta, "original": obj, "form": form,
        })

    def new_revision(self, request, object_id):
        obj = self.get_object(request, str(object_id))
        if obj is None:
            raise Http404
        if not self.has_change_permission(request, obj):
            raise PermissionDenied
        initial = {}
        if obj.current_revision_id:
            revision = obj.current_revision
            initial.update(language=revision.language, correct_answer=revision.correct_answer,
                           difficulty_level=revision.difficulty_level)
            if edition := revision.primary_translation:
                initial.update({field: getattr(edition, field) for field in TRANSLATED_FIELDS})
        form = RevisionForm(request.POST if request.method ==
                            "POST" else None, initial=initial)
        if request.method == "POST" and form.is_valid():
            try:
                services.create_revision(obj, **form.cleaned_data)
            except ValidationError as error:
                form.add_error(None, "; ".join(error.messages))
            else:
                self.message_user(
                    request, "Draft revision created. Review and publish it explicitly.")
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
    search_fields = ("translations__question_text",)
    fields = ("question", "revision_number", "language", "correct_answer", "difficulty_level", "created_at", "published_at")
    readonly_fields = fields
    inlines = (TranslationInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(QuestionSource)
class QuestionSourceAdmin(admin.ModelAdmin):
    list_display = ("source_code", "source_name", "source_document", "publisher", "created_at")
    search_fields = ("source_code", "source_name", "source_document", "publisher")
    readonly_fields = ("created_at",)


@admin.register(QuestionExam)
class QuestionExamAdmin(admin.ModelAdmin):
    list_display = ("question", "exam")
    list_filter = ("exam",)
    autocomplete_fields = ("question", "exam")


@admin.register(QuestionSourceReference)
class QuestionSourceReferenceAdmin(admin.ModelAdmin):
    list_display = ("question", "source", "source_page",
                    "source_question_number")
    search_fields = ("source__source_code", "source__source_name",
                     "source__source_document", "source_question_number")
    autocomplete_fields = ("question", "source")


@admin.register(QuestionTranslation)
class QuestionTranslationAdmin(admin.ModelAdmin):
    list_display = ("revision", "language", "question_text")
    list_filter = ("language",)
    search_fields = ("question_text",)
    autocomplete_fields = ("revision",)
