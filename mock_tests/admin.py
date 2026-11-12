from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django import forms
from questions.models import Question

from .models import ExamPattern, ExamPatternSection, SectionSelectionRule, ManualRuleQuestion
from .services import activate_pattern, deactivate_pattern, eligible_question_ids, validate_configuration
from .rules import eligible_for_rule, selection_tasks, validate_rule_layout


def rules_locked(obj):
    if isinstance(obj, ExamPatternSection) and not obj.pattern_id:
        return False
    if isinstance(obj, SectionSelectionRule) and not obj.section_id:
        return False
    pattern = obj.pattern if isinstance(obj, ExamPatternSection) else obj.section.pattern
    return pattern.is_active or pattern.attempts.exists()


class RuleFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors) or rules_locked(self.instance):
            return
        rules = [form.instance for form in self.forms if form.cleaned_data and not form.cleaned_data.get("DELETE")]
        validate_rule_layout(self.instance, rules)


class RuleInline(admin.StackedInline):
    model = SectionSelectionRule
    formset = RuleFormSet
    extra = 0
    show_change_link = True
    autocomplete_fields = ("subject", "part", "module", "chapter", "topic")
    readonly_fields = ("eligible_count",)
    fields = (("display_order", "question_count", "selection_mode", "difficulty"),
              "subject", "part", "module", "chapter", "topic", "eligible_count")

    @admin.display(description="Eligible questions")
    def eligible_count(self, obj):
        if not obj.pk:
            return "Save to check; open the rule to choose manual questions."
        try:
            return len(eligible_for_rule(obj))
        except ValidationError as error:
            return "; ".join(error.messages)

    def has_add_permission(self, request, obj=None):
        return not (obj and rules_locked(obj)) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return not (obj and rules_locked(obj)) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not (obj and rules_locked(obj)) and super().has_delete_permission(request, obj)


class ManualQuestionForm(forms.ModelForm):
    class Meta:
        model = ManualRuleQuestion
        fields = ("question", "display_order")

    def __init__(self, *args, rule=None, pool_cache=None, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            ids = eligible_for_rule(rule, cache=pool_cache) if rule and rule.section_id else set()
        except ValidationError:
            ids = set()
        self.fields["question"].queryset = Question.objects.filter(pk__in=ids)


class ManualQuestionFormSet(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.pool_cache = {}
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        return super().get_form_kwargs(index) | {"rule": self.instance, "pool_cache": self.pool_cache}

    def clean(self):
        super().clean()
        if any(self.errors) or rules_locked(self.instance):
            return
        rows = [form.instance for form in self.forms if form.cleaned_data and not form.cleaned_data.get("DELETE")]
        if self.instance.selection_mode == "manual" and len(rows) != self.instance.question_count:
            raise ValidationError(f"Select exactly {self.instance.question_count} manual questions.")
        if self.instance.selection_mode != "manual" and rows:
            raise ValidationError("Random rules cannot contain manual questions.")


class ManualQuestionInline(admin.TabularInline):
    model = ManualRuleQuestion
    form = ManualQuestionForm
    formset = ManualQuestionFormSet
    raw_id_fields = ("question",)
    extra = 0

    def has_add_permission(self, request, obj=None):
        return not (obj and rules_locked(obj)) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return not (obj and rules_locked(obj)) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not (obj and rules_locked(obj)) and super().has_delete_permission(request, obj)


@admin.register(SectionSelectionRule)
class SelectionRuleAdmin(admin.ModelAdmin):
    list_display = ("section", "display_order", "question_count", "selection_mode", "difficulty")
    list_filter = ("selection_mode", "difficulty", "section__pattern__exam")
    search_fields = ("section__name", "section__pattern__name")
    list_select_related = ("section__pattern",)
    autocomplete_fields = ("section", "subject", "part", "module", "chapter", "topic")
    readonly_fields = ("eligible_count", "rule_status", "pattern_status")
    inlines = (ManualQuestionInline,)
    fieldsets = (
        ("Rule", {"fields": ("section", "display_order", "selection_mode", "question_count", "difficulty")}),
        ("Taxonomy filter", {"fields": ("subject", "part", "module", "chapter", "topic"),
            "description": "Choose exactly one filter. Descendants and secondary topic tags are included. Detailed rules replace section-level Subject/Topic filters."}),
        ("Validation", {"fields": ("eligible_count", "rule_status", "pattern_status")}),
    )

    @admin.display(description="Eligible questions")
    def eligible_count(self, obj):
        if not obj.pk:
            return "Save to check"
        try:
            return len(eligible_for_rule(obj))
        except ValidationError as error:
            return "; ".join(error.messages)

    @admin.display(description="Section rule validation")
    def rule_status(self, obj):
        if not obj.pk:
            return "Save, then add manual questions if needed. Choose exactly one taxonomy filter."
        try:
            selection_tasks([obj.section], legacy_eligibility=eligible_question_ids)
        except ValidationError as error:
            return "; ".join(error.messages)
        return "Section rule quotas and individual eligibility are valid; see pattern status for shared-pool capacity."

    @admin.display(description="Overall pattern validation")
    def pattern_status(self, obj):
        if not obj.pk:
            return "Save to validate"
        try:
            validate_configuration(obj.section.pattern)
        except ValidationError as error:
            return "; ".join(error.messages)
        return "Valid configuration and sufficient distinct eligible questions."

    def has_change_permission(self, request, obj=None):
        return not (obj and rules_locked(obj)) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not (obj and rules_locked(obj)) and super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields) + self.readonly_fields if obj and rules_locked(obj) else self.readonly_fields


class SectionFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors) or self.instance.is_active:
            return
        sections = [form.instance for form in self.forms if form.cleaned_data and not form.cleaned_data.get("DELETE")]
        try:
            validate_configuration(self.instance, sections, check_availability=False)
        except ValidationError as error:
            # Formsets require a list, while model validation can return a field dictionary.
            raise ValidationError(error.messages) from error


class SectionForm(forms.ModelForm):
    class Meta:
        model = ExamPatternSection
        fields = "__all__"
        help_texts = {"language_mode": "English/Bengali requires both complete translations in each question's published revision. Students choose which edition to display when starting."}


class SectionInline(admin.TabularInline):
    model = ExamPatternSection
    form = SectionForm
    formset = SectionFormSet
    extra = 0
    show_change_link = True
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
    form = SectionForm
    list_display = ("name", "pattern", "display_order", "question_count", "subject", "topic", "language_mode")
    list_filter = ("pattern", "subject", "language_mode")
    search_fields = ("name", "pattern__name")
    readonly_fields = ("eligible_count", "configuration_status")
    list_select_related = ("pattern__exam", "subject", "topic")
    inlines = (RuleInline,)

    @admin.display(description="Pattern configuration status")
    def configuration_status(self, obj):
        if not obj.pk:
            return "Save to add detailed rules. Without rules, existing section filters apply."
        try:
            validate_configuration(obj.pattern)
        except ValidationError as error:
            return "; ".join(error.messages)
        return "Valid configuration and sufficient distinct eligible questions."

    def has_change_permission(self, request, obj=None):
        return not (obj and (obj.pattern.is_active or obj.pattern.attempts.exists())) and super().has_change_permission(request, obj)

    @admin.display(description="Eligible questions")
    def eligible_count(self, obj):
        return len(eligible_question_ids(obj)) if obj.pk else "Save to check"

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields) + self.readonly_fields if obj and (obj.pattern.is_active or obj.pattern.attempts.exists()) else self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return not (obj and (obj.pattern.is_active or obj.pattern.attempts.exists())) and super().has_delete_permission(request, obj)
