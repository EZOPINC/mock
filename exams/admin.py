from django.contrib import admin
from django.conf import settings
from django.db.models import Q
from django.urls import reverse
from urllib.parse import urlencode

from .models import Chapter, Exam, ExamAuthority, ExamStage, Module, Submodule, Part, Subject, Topic


class ModulePathFilter(admin.SimpleListFilter):
    title = "module (including ancestors)"
    parameter_name = "module_path"

    def lookups(self, request, model_admin):
        nodes = Module.objects.select_related("subject", "part__subject")
        subject = request.GET.get("subject__id__exact")
        if subject and subject.isdecimal():
            nodes = nodes.filter(subject_id=subject)
        return [(str(node.pk), str(node)) for node in nodes]

    def queryset(self, request, queryset):
        if self.value() and self.value().isdecimal():
            query = Q(module_id=self.value())
            if queryset.model is Chapter:
                query |= Q(submodule__module_id=self.value())
            if queryset.model is Topic:
                query |= Q(chapter__module_id=self.value()) | Q(chapter__submodule__module_id=self.value())
            return queryset.filter(query)
        return queryset


class SubmodulePathFilter(admin.SimpleListFilter):
    title = "sub-module"
    parameter_name = "submodule_path"

    def lookups(self, request, model_admin):
        nodes = Submodule.objects.select_related("subject", "module__subject", "module__part__subject")
        for param, field in (("subject__id__exact", "subject_id"), ("module_path", "module_id")):
            value = request.GET.get(param)
            if value and value.isdecimal():
                nodes = nodes.filter(**{field: value})
        return [(str(node.pk), str(node)) for node in nodes]

    def queryset(self, request, queryset):
        if self.value() and self.value().isdecimal():
            field = "chapter__submodule_id" if queryset.model is Topic else "submodule_id"
            return queryset.filter(**{field: self.value()})
        return queryset


class ChapterPathFilter(admin.SimpleListFilter):
    title = "chapter"
    parameter_name = "chapter_path"

    def lookups(self, request, model_admin):
        nodes = Chapter.objects.select_related("subject", "module__part__subject", "module__subject", "part__subject", "submodule__module__part__subject", "submodule__module__subject", "submodule__subject")
        for param, field in (("subject__id__exact", "subject_id"), ("module_path", "module_id")):
            value = request.GET.get(param)
            if value and value.isdecimal():
                nodes = nodes.filter(Q(module_id=value) | Q(submodule__module_id=value)) if field == "module_id" else nodes.filter(**{field: value})
        submodule = request.GET.get("submodule_path")
        if submodule and submodule.isdecimal():
            nodes = nodes.filter(submodule_id=submodule)
        return [(str(node.pk), str(node)) for node in nodes]

    def queryset(self, request, queryset):
        if self.value() and self.value().isdecimal():
            return queryset.filter(chapter_id=self.value())
        return queryset


class ExamInline(admin.TabularInline):
    model = Exam
    extra = 0
    show_change_link = True


class ExamStageInline(admin.TabularInline):
    model = ExamStage
    extra = 0
    show_change_link = True


class PartInline(admin.TabularInline):
    show_change_link = True
    model = Part
    extra = 0
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("code",)


class ModuleInline(admin.TabularInline):
    show_change_link = True
    model = Module
    extra = 0
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("code",)


class SubmoduleInline(admin.TabularInline):
    model = Submodule
    extra = 0
    show_change_link = True
    autocomplete_fields = ("module",)
    readonly_fields = ("code",)
    prepopulated_fields = {"slug": ("name",)}


class ChapterInline(admin.TabularInline):
    show_change_link = True
    model = Chapter
    autocomplete_fields = ("submodule", "module", "part")
    extra = 0
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("code",)


class TopicInline(admin.TabularInline):
    show_change_link = True
    model = Topic
    extra = 0
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("chapter", "module", "part")
    readonly_fields = ("code",)


class TaxonomyInlineBudgetAdmin:
    change_form_template = "admin/exams/taxonomy_change_form.html"

    def get_inline_instances(self, request, obj=None):
        instances = super().get_inline_instances(request, obj)
        request.taxonomy_overflow_links = []
        limit = settings.DATA_UPLOAD_MAX_NUMBER_FIELDS
        if limit is None or obj is None:
            return instances
        # Reserve the parent form, CSRF/save controls and related-widget fields.
        remaining = max(0, limit - 64)
        visible = []
        for inline in instances:
            formset = inline.get_formset(request, obj)
            count = inline.get_queryset(request).filter(**{formset.fk.name: obj.pk}).count()
            # Per-row model fields, hidden identity/delete controls, the empty
            # add-row template and the four formset management inputs.
            needed = (count + inline.get_extra(request, obj) + 1) * (len(formset.form.base_fields) + 3) + 4
            if needed <= remaining:
                visible.append(inline)
                remaining -= needed
            else:
                opts = inline.model._meta
                request.taxonomy_overflow_links.append({
                    "label": str(opts.verbose_name_plural), "count": count,
                    "url": reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist") + "?" + urlencode({f"{formset.fk.name}__id__exact": obj.pk}),
                })
        return visible

    def render_change_form(self, request, context, *args, **kwargs):
        context["taxonomy_overflow_links"] = getattr(request, "taxonomy_overflow_links", [])
        return super().render_change_form(request, context, *args, **kwargs)


class TaxonomyCodeAdmin(TaxonomyInlineBudgetAdmin):
    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return (*fields, "code") if obj else fields


@admin.register(ExamAuthority)
class ExamAuthorityAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "slug", "is_active")
    search_fields = ("name", "code")
    list_filter = ("is_active",)
    ordering = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = (ExamInline,)


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("name", "authority", "code", "slug", "is_active")
    search_fields = ("name", "code", "authority__name", "authority__code")
    list_filter = ("authority", "is_active")
    list_select_related = ("authority",)
    ordering = ("authority__name", "name")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (ExamStageInline,)


@admin.register(ExamStage)
class ExamStageAdmin(admin.ModelAdmin):
    list_display = ("name", "exam", "code", "display_order")
    search_fields = ("name", "code", "exam__name", "exam__code")
    list_filter = ("exam__authority", "exam")
    list_select_related = ("exam__authority",)
    ordering = ("exam__name", "display_order", "name")


@admin.register(Subject)
class SubjectAdmin(TaxonomyCodeAdmin, admin.ModelAdmin):
    list_display = ("name", "code", "slug", "display_order")
    search_fields = ("name", "code")
    ordering = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = (PartInline, ModuleInline, ChapterInline, TopicInline)


@admin.register(Part)
class PartAdmin(TaxonomyCodeAdmin, admin.ModelAdmin):
    list_display = ("name", "code", "subject", "display_order")
    search_fields = ("name", "code", "subject__name")
    list_filter = ("subject",)
    list_select_related = ("subject",)
    autocomplete_fields = ("subject",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = (ModuleInline, ChapterInline, TopicInline)


@admin.register(Module)
class ModuleAdmin(TaxonomyCodeAdmin, admin.ModelAdmin):
    list_display = ("name", "code", "subject", "part", "display_order")
    search_fields = ("name", "code", "subject__name", "part__name")
    list_filter = ("subject", "part")
    list_select_related = ("subject", "part__subject")
    autocomplete_fields = ("subject", "part")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (SubmoduleInline, ChapterInline, TopicInline)

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return (*fields, "part") if obj and obj.part_id is not None else fields


@admin.register(Submodule)
class SubmoduleAdmin(TaxonomyCodeAdmin, admin.ModelAdmin):
    list_display = ("name", "code", "subject", "module", "display_order")
    search_fields = ("name", "code", "subject__name", "module__name")
    list_filter = ("subject", ModulePathFilter)
    list_select_related = ("subject", "module__subject", "module__part__subject")
    autocomplete_fields = ("subject", "module")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (ChapterInline,)


@admin.register(Chapter)
class ChapterAdmin(TaxonomyCodeAdmin, admin.ModelAdmin):
    list_display = ("name", "code", "subject",
                    "submodule", "module", "part", "display_order")
    search_fields = ("name", "code", "subject__name",
                     "submodule__name", "module__name", "part__name")
    list_filter = ("subject", "part", ModulePathFilter, SubmodulePathFilter)
    list_select_related = ("subject", "part__subject",
                           "module__subject", "module__part__subject", "submodule__subject", "submodule__module__subject", "submodule__module__part__subject")
    autocomplete_fields = ("subject", "submodule", "module", "part")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (TopicInline,)


@admin.register(Topic)
class TopicAdmin(TaxonomyCodeAdmin, admin.ModelAdmin):
    list_display = ("name", "code", "subject",
                    "chapter", "module", "part", "slug")
    search_fields = ("name", "code", "subject__name", "subject__code",
                     "chapter__name", "chapter__submodule__name", "module__name", "part__name")
    list_filter = ("subject", "part", ModulePathFilter, SubmodulePathFilter, ChapterPathFilter)
    list_select_related = ("subject", "part__subject", "module__subject", "module__part__subject", "chapter__subject",
                           "chapter__part__subject", "chapter__module__subject", "chapter__module__part__subject", "chapter__submodule__subject", "chapter__submodule__module__subject", "chapter__submodule__module__part__subject")
    autocomplete_fields = ("chapter", "module", "part")
    ordering = ("subject__name", "name")
    prepopulated_fields = {"slug": ("name",)}
