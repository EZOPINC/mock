from django.contrib import admin

from .models import Chapter, Exam, ExamAuthority, ExamStage, Module, Part, Subject, Topic


class ExamStageInline(admin.TabularInline):
    model = ExamStage
    extra = 0


class TopicInline(admin.TabularInline):
    model = Topic
    extra = 0
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("chapter",)


class ModuleInline(admin.TabularInline):
    model = Module
    extra = 0
    prepopulated_fields = {"slug": ("name",)}


class PartInline(admin.TabularInline):
    model = Part
    extra = 0
    prepopulated_fields = {"slug": ("name",)}


class ChapterInline(admin.TabularInline):
    model = Chapter
    extra = 0
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ("name", "subject", "display_order")
    search_fields = ("name", "subject__name")
    list_filter = ("subject",)
    list_select_related = ("subject",)
    autocomplete_fields = ("subject",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = (ModuleInline,)


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("name", "part", "display_order")
    search_fields = ("name", "part__name", "part__subject__name")
    list_filter = ("part__subject", "part")
    list_select_related = ("part__subject",)
    autocomplete_fields = ("part",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = (ChapterInline,)


@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ("name", "module", "display_order")
    search_fields = ("name", "module__name", "module__part__name", "module__part__subject__name")
    list_filter = ("module__part__subject", "module__part", "module")
    list_select_related = ("module__part__subject",)
    autocomplete_fields = ("module",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ExamAuthority)
class ExamAuthorityAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "slug", "is_active")
    search_fields = ("name", "code")
    list_filter = ("is_active",)
    ordering = ("name",)
    prepopulated_fields = {"slug": ("name",)}


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
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "slug")
    search_fields = ("name", "code")
    ordering = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = (PartInline, TopicInline)


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("name", "subject", "chapter", "slug")
    search_fields = ("name", "subject__name", "subject__code", "chapter__name", "chapter__module__name", "chapter__module__part__name")
    list_filter = ("subject", "chapter__module__part", "chapter__module", "chapter")
    list_select_related = ("subject", "chapter__module__part__subject")
    autocomplete_fields = ("chapter",)
    ordering = ("subject__name", "name")
    prepopulated_fields = {"slug": ("name",)}
