from django import forms
from django.utils import timezone

from exams.models import Exam
from previous_year.models import QuestionAppearance


class AppearanceForm(forms.ModelForm):
    verified = forms.BooleanField(required=False, label="Verified against the source")
    version = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = QuestionAppearance
        fields = ("exam", "exam_name", "authority_name", "year", "stage", "session",
                  "question_number", "source_reference")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["exam"].queryset = Exam.objects.select_related("authority")
        self.fields["source_reference"].queryset = self.instance.question.source_references.select_related("source")
        self.initial["verified"] = self.instance.verified_at is not None
        if self.instance.pk:
            self.initial["version"] = self.instance.updated_at.isoformat()

    def clean_version(self):
        value = self.cleaned_data["version"]
        if self.instance.pk and value != self.instance.updated_at.isoformat():
            raise forms.ValidationError("This appearance changed. Reload it before saving.")
        return value

    def save_for_reviewer(self, user):
        appearance = self.save(commit=False)
        if self.cleaned_data["verified"]:
            if not appearance.verified_at or set(self.changed_data) - {"version"}:
                appearance.verified_by = user
                appearance.verified_at = timezone.now()
        else:
            appearance.verified_by = None
            appearance.verified_at = None
        appearance.save()
        return appearance
