from django.contrib.admin.apps import AdminConfig
from django.contrib.admin.sites import AdminSite


class PlatformAdminSite(AdminSite):
    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        order = {name: index for index, name in enumerate((
            "ExamAuthority", "Exam", "ExamStage", "Subject", "Part", "Module", "Chapter", "Topic",
        ))}
        for app in app_list:
            if app["app_label"] == "exams":
                app["models"].sort(key=lambda model: order.get(model["object_name"], len(order)))
        return app_list


class PlatformAdminConfig(AdminConfig):
    default_site = "config.admin.PlatformAdminSite"
