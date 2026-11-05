from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .models import ExamPattern, ExamPatternSection
from .services import activate_pattern, deactivate_pattern, eligible_question_ids, validate_configuration


class SectionFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors) or self.instance.is_active:
            return
        sections = [form.instance for form in self.forms if form.cleaned_data and not form.cleaned_data.get("DELETE")]
        validate_configuration(self.instance, sections, check_availability=False)


class SectionInline(admin.TabularInline):
    model = ExamPatternSection
    formset = SectionFormSet
    extra = 0
    readonly_fields = ("eligible_count",)

    @admin.display(description="Eligible questions")
    def eligible_count(self, obj):
        return len(eligible_question_ids(obj)) if obj.pk else "Save to check"

    def has_add_permission(self, request, obj=None):
        return not (obj and (obj.is_active or obj.attempts.exists())) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return not (obj and (obj.is_active or obj.attempts.exists())) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not (obj and (obj.is_active or obj.attempts.exists())) and super().has_delete_permission(request, obj)


@admin.register(ExamPattern)
class ExamPatternAdmin(admin.ModelAdmin):
    list_display = ("name", "exam", "stage", "version", "duration_minutes", "total_questions", "total_marks", "status")
    list_filter = ("exam", "stage", "status")
    search_fields = ("name", "exam__name", "exam__code")
    list_select_related = ("exam", "stage")
    readonly_fields = ("status", "created_at", "configuration_status")
    inlines = (SectionInline,)
    actions = ("activate_selected", "deactivate_selected")

    def has_change_permission(self, request, obj=None):
        return not (obj and (obj.is_active or obj.attempts.exists())) and super().has_change_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return tuple(field.name for field in self.model._meta.fields) + ("configuration_status",) if obj and (obj.is_active or obj.attempts.exists()) else fields

    def has_delete_permission(self, request, obj=None):
        return not (obj and (obj.is_active or obj.attempts.exists())) and super().has_delete_permission(request, obj)

    @admin.display(description="Configuration status")
    def configuration_status(self, obj):
        if not obj.pk:
            return "Save the pattern and sections, then explicitly activate."
        try:
            validate_configuration(obj)
        except ValidationError as error:
            return "; ".join(error.messages)
        return "Valid configuration and sufficient distinct eligible questions."

    @admin.action(description="Activate validated patterns", permissions=["change"])
    def activate_selected(self, request, queryset):
        self.transition(request, queryset, activate_pattern)

    @admin.action(description="Deactivate patterns", permissions=["change"])
    def deactivate_selected(self, request, queryset):
        self.transition(request, queryset, deactivate_pattern)

    def transition(self, request, queryset, operation):
        for pattern in queryset:
            try:
                operation(pattern)
            except ValidationError as error:
                self.message_user(request, f"{pattern}: {'; '.join(error.messages)}", messages.ERROR)
            else:
                self.message_user(request, f"{pattern}: updated.", messages.SUCCESS)


@admin.register(ExamPatternSection)
class ExamPatternSectionAdmin(admin.ModelAdmin):
    list_display = ("name", "pattern", "display_order", "question_count", "subject", "topic", "language_mode", "eligible_count")
    list_filter = ("pattern", "subject", "language_mode")
    search_fields = ("name", "pattern__name")
    readonly_fields = ("eligible_count",)
    list_select_related = ("pattern__exam", "subject", "topic")

    def has_change_permission(self, request, obj=None):
        return not (obj and (obj.pattern.is_active or obj.pattern.attempts.exists())) and super().has_change_permission(request, obj)

    @admin.display(description="Eligible questions")
    def eligible_count(self, obj):
        return len(eligible_question_ids(obj)) if obj.pk else "Save to check"

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields) + ("eligible_count",) if obj and (obj.pattern.is_active or obj.pattern.attempts.exists()) else self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return not (obj and (obj.pattern.is_active or obj.pattern.attempts.exists())) and super().has_delete_permission(request, obj)
