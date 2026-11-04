from django.core.exceptions import PermissionDenied

REQUIRED_PERMISSIONS = (
    "imports.add_importbatch", "questions.add_question", "questions.add_questionrevision",
    "questions.add_questionexam", "questions.add_questionsource", "questions.add_questionsourcereference",
    "previous_year.add_previousyearpaper", "previous_year.add_paperquestion",
)


def require_import_permission(user):
    if not user.is_active or not user.is_staff or not user.has_perms(REQUIRED_PERMISSIONS):
        raise PermissionDenied("Staff access and the import/Question Bank/paper creation permissions are required.")
