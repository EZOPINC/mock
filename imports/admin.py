from django.contrib import admin
from .models import ImportBatch, ImportedQuestion


class ImportedQuestionInline(admin.TabularInline):
    model = ImportedQuestion
    extra = 0
    can_delete = False
    fields = ("source_row_number", "question", "action")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    change_list_template = "admin/imports/importbatch/change_list.html"
    list_display = ("id", "filename", "uploaded_by", "paper", "row_count", "confirmed_at")
    readonly_fields = tuple(field.name for field in ImportBatch._meta.fields)
    inlines = (ImportedQuestionInline,)
    search_fields = ("filename", "file_sha256")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ImportedQuestion)
class ImportedQuestionAdmin(admin.ModelAdmin):
    list_display = ("batch", "source_row_number", "question", "action")
    readonly_fields = tuple(field.name for field in ImportedQuestion._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
