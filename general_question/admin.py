from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import redirect

from .models import GeneralQuestionBatch
from .services import batch_questions, fingerprint, require_batch_permission, transition_batch


@admin.register(GeneralQuestionBatch)
class GeneralQuestionBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "filename", "row_count", "reviewed_count", "published_count", "confirmed_at")
    list_display_links = ("id", "filename")
    search_fields = ("filename",)
    ordering = ("-confirmed_at", "-pk")
    actions = ("review_selected_batches", "publish_selected_batches")

    def has_batch_permission(self, request):
        return self.has_module_permission(request)

    @admin.action(description="Mark all questions in selected batches as reviewed", permissions=["batch"])
    def review_selected_batches(self, request, queryset):
        self._transition_selected(request, queryset, "review")

    @admin.action(description="Publish all reviewed questions in selected batches", permissions=["batch"])
    def publish_selected_batches(self, request, queryset):
        self._transition_selected(request, queryset, "publish")

    def _transition_selected(self, request, queryset, action):
        require_batch_permission(request.user)
        for batch in queryset.order_by("pk"):
            expected = fingerprint(list(batch_questions(batch)))
            try:
                count = transition_batch(batch.pk, request.user, action, expected)
            except ValidationError as error:
                self.message_user(request, f"Batch #{batch.pk}: {'; '.join(error.messages)}", messages.ERROR)
            else:
                label = "marked reviewed" if action == "review" else "published"
                self.message_user(request, f"Batch #{batch.pk}: {count} questions {label}.", messages.SUCCESS)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            reviewed_total=Count("imported_questions__question", filter=Q(imported_questions__question__review_status="reviewed"), distinct=True),
            published_total=Count("imported_questions__question", filter=Q(imported_questions__question__publication_status="published"), distinct=True),
        )

    @admin.display(description="Working revisions reviewed", ordering="reviewed_total")
    def reviewed_count(self, obj):
        return obj.reviewed_total

    @admin.display(description="Questions with live content", ordering="published_total")
    def published_count(self, obj):
        return obj.published_total

    def has_module_permission(self, request):
        try:
            require_batch_permission(request.user)
        except PermissionDenied:
            return False
        return True

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def change_view(self, request, object_id, form_url="", extra_context=None):
        require_batch_permission(request.user)
        obj = self.get_object(request, object_id)
        if obj is None:
            raise Http404
        return redirect("general_questions:manage_batch", batch_id=obj.pk)
