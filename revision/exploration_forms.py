from django import forms
from django.db.models.functions import Lower, Trim
from exams.models import Exam


class RelatedFilters(forms.Form):
    exam = forms.ModelChoiceField(queryset=Exam.objects.none(), required=False, empty_label="All exams")
    difficulty = forms.ChoiceField(required=False, choices=[("", "All difficulties")])

    def __init__(self, *args, questions, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["exam"].queryset = Exam.objects.filter(is_active=True, authority__is_active=True,
            question_associations__question__in=questions).distinct().order_by("name", "pk")
        self.fields["exam"].label_from_instance = lambda exam: f"{exam.name} [{exam.code}]"
        levels = questions.annotate(_level=Lower(Trim("published_revision__difficulty_level"))).order_by("_level").values_list("_level", flat=True).distinct()
        self.fields["difficulty"].choices = [("", "All difficulties")] + [
            ("level:" + level, level.title() if level else "Unspecified difficulty") for level in levels]

    def clean_difficulty(self):
        value = self.cleaned_data["difficulty"]
        return value[len("level:"):] if value else None
