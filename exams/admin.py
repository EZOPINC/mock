from django.contrib import admin

from .models import Exam, ExamAuthority, ExamStage, Subject, Topic


class ExamStageInline(admin.TabularInline):
    model = ExamStage
    extra = 0


class TopicInline(admin.TabularInline):
    model = Topic
    extra = 0
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
    inlines = (TopicInline,)


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("name", "subject", "slug")
    search_fields = ("name", "subject__name", "subject__code")
    list_filter = ("subject",)
    list_select_related = ("subject",)
    ordering = ("subject__name", "name")
    prepopulated_fields = {"slug": ("name",)}
