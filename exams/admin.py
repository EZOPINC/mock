from django.contrib import admin
from django.db.models import Q

from .models import Chapter, Exam, ExamAuthority, ExamStage, Module, Part, Subject, Topic


class ModulePathFilter(admin.SimpleListFilter):
    title = "module (including ancestors)"
    parameter_name = "module_path"

    def lookups(self, request, model_admin):
        nodes = Module.objects.select_related("subject")
        subject = request.GET.get("subject__id__exact")
        if subject and subject.isdecimal():
            nodes = nodes.filter(subject_id=subject)
        return [(str(node.pk), str(node)) for node in nodes]

    def queryset(self, request, queryset):
        if self.value() and self.value().isdecimal():
            query = Q(module_id=self.value())
            if queryset.model is Topic:
                query |= Q(chapter__module_id=self.value())
            return queryset.filter(query)
        return queryset


class ChapterPathFilter(admin.SimpleListFilter):
    title = "chapter"
    parameter_name = "chapter_path"

    def lookups(self, request, model_admin):
        nodes = Chapter.objects.select_related("subject", "module", "part")
        for param, field in (("subject__id__exact", "subject_id"), ("module_path", "module_id")):
            value = request.GET.get(param)
            if value and value.isdecimal():
                nodes = nodes.filter(**{field: value})
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


class ChapterInline(admin.TabularInline):
    show_change_link = True
    model = Chapter
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


class TaxonomyCodeAdmin:
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
    inlines = (ChapterInline, TopicInline)


@admin.register(Chapter)
class ChapterAdmin(TaxonomyCodeAdmin, admin.ModelAdmin):
    list_display = ("name", "code", "subject",
                    "module", "part", "display_order")
    search_fields = ("name", "code", "subject__name",
                     "module__name", "part__name")
    list_filter = ("subject", "part", ModulePathFilter)
    list_select_related = ("subject", "part__subject",
                           "module__subject", "module__part__subject")
    autocomplete_fields = ("subject", "module", "part")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (TopicInline,)


@admin.register(Topic)
class TopicAdmin(TaxonomyCodeAdmin, admin.ModelAdmin):
    list_display = ("name", "code", "subject",
                    "chapter", "module", "part", "slug")
    search_fields = ("name", "code", "subject__name", "subject__code",
                     "chapter__name", "module__name", "part__name")
    list_filter = ("subject", "part", ModulePathFilter, ChapterPathFilter)
    list_select_related = ("subject", "part__subject", "module__subject", "module__part__subject", "chapter__subject",
                           "chapter__part__subject", "chapter__module__subject", "chapter__module__part__subject")
    autocomplete_fields = ("chapter", "module", "part")
    ordering = ("subject__name", "name")
    prepopulated_fields = {"slug": ("name",)}
