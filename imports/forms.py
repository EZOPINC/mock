from django import forms
from django.core.exceptions import ValidationError

from exams.models import Exam, ExamAuthority, ExamStage, Subject, Topic
from previous_year.models import PreviousYearPaper

DEFAULT_PAPER_NAME = "Previous Year Paper"


class ImportSubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ("name", "code", "slug")

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if any(" ".join(value.split()).casefold() == name.casefold()
               for value in Subject.objects.values_list("name", flat=True)):
            raise ValidationError("A subject with this name already exists. Use its mapping instead.")
        return name


class ImportTopicForm(forms.ModelForm):
    class Meta:
        model = Topic
        fields = ("subject", "name", "slug")

    def clean(self):
        cleaned = super().clean()
        subject, name = cleaned.get("subject"), cleaned.get("name")
        if subject and name:
            name = " ".join(name.split())
            cleaned["name"] = name
            if any(" ".join(value.split()).casefold() == name.casefold()
                   for value in Topic.objects.filter(subject=subject).values_list("name", flat=True)):
                self.add_error("name", "A topic with this name already exists under this subject. Use its mapping instead.")
        return cleaned


class UploadForm(forms.Form):
    import_type = forms.ChoiceField(choices=(("", "Choose import type"), ("previous_year", "Previous Year Questions"), ("general", "General Question Bank")))
    file = forms.FileField(label="CSV or XLSX file", widget=forms.FileInput(attrs={"accept": ".csv,.xlsx"}))
    worksheet = forms.CharField(required=False, max_length=100, help_text="Optional; required by name when the workbook has multiple sheets.")
    authority = forms.ModelChoiceField(queryset=ExamAuthority.objects.all(), required=False, label="Authority filter (optional)")
    exam = forms.ModelChoiceField(queryset=Exam.objects.select_related("authority"), required=False, label="Exam (required for Previous Year)")
    exams = forms.ModelMultipleChoiceField(queryset=Exam.objects.select_related("authority"), required=False, label="Exams (required for General Question Bank)", widget=forms.SelectMultiple(attrs={"size": 6}))
    exam_mapping = forms.ChoiceField(choices=(("selected", "Use selected exams for every row"), ("rows", "Resolve row exam_categories; use selected exams when blank")), initial="selected", required=False)
    year = forms.IntegerField(min_value=1, required=False, label="Year (required for Previous Year)")
    stage = forms.ModelChoiceField(queryset=ExamStage.objects.select_related("exam"), required=False)
    paper = forms.ModelChoiceField(queryset=PreviousYearPaper.objects.filter(is_published=False).select_related("exam"), required=False, label="Existing draft paper (optional)")
    paper_name = forms.CharField(max_length=200, required=False, help_text="Optional; defaults to Previous Year Paper. Matching draft identities are reused.")
    part = forms.CharField(max_length=100, required=False)
    session = forms.CharField(max_length=100, required=False)
    subject = forms.ModelChoiceField(queryset=Subject.objects.all(), required=False, label="Default subject (optional)", help_text="Used only when a row has no subject.")
    topic = forms.ModelChoiceField(queryset=Topic.objects.select_related("subject"), required=False, label="Default topic (optional)", help_text="Used only when a row has no topic; it must match the resolved subject.")
    language = forms.ChoiceField(choices=(("", "Auto-detect English/Bengali from question text"), ("en", "English"), ("bn", "Bengali")), required=False, label="Default language (optional)", help_text="Explicit row language takes priority, then this default. Otherwise infer en/bn from question/options characters; ambiguous text needs correction.")
    acknowledge_existing = forms.BooleanField(required=False, label="I reviewed existing imports in this paper and intend to append new, nonconflicting numbers.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            mode = self.data.get("import_type")
            irrelevant = ("authority", "exam", "paper", "year", "stage", "paper_name", "part", "session", "acknowledge_existing") if mode == "general" else ("exams", "exam_mapping") if mode == "previous_year" else ()
            for name in irrelevant:
                self.fields[name].disabled = True

    def clean(self):
        data = super().clean()
        mode = data.get("import_type")
        if data.get("subject") and data.get("topic") and data["topic"].subject_id != data["subject"].pk:
            self.add_error("topic", "Default topic must belong to the default subject.")
        if mode == "previous_year":
            exam = data.get("exam")
            if not exam:
                self.add_error("exam", "Select one exam.")
            if not data.get("year"):
                self.add_error("year", "Year is required.")
            if exam and data.get("authority") and exam.authority_id != data["authority"].pk:
                self.add_error("exam", "Exam must belong to the authority filter.")
            if exam and data.get("stage") and data["stage"].exam_id != exam.pk:
                self.add_error("stage", "Stage must belong to the selected exam.")
            paper = data.get("paper")
            if paper and (not exam or paper.exam_id != exam.pk or paper.year != data.get("year") or paper.stage_id != (data["stage"].pk if data.get("stage") else None)):
                self.add_error("paper", "Existing paper must match the selected exam, year, and stage.")
        elif mode == "general":
            if not data.get("exams"):
                self.add_error("exams", "Select at least one exam.")
        return data

    def selection(self):
        data = self.cleaned_data
        general = data["import_type"] == "general"
        paper = None if general else data.get("paper")
        return {
            "import_type": data["import_type"],
            "exam_ids": sorted(exam.pk for exam in data["exams"]) if general else [data["exam"].pk],
            "exam_id": None if general else data["exam"].pk,
            "authority_id": None if general else data["exam"].authority_id,
            "exam_mapping": (data.get("exam_mapping") or "selected") if general else "selected",
            "paper_id": paper.pk if paper else None,
            "paper": {} if general else {
                "year": data["year"], "stage_id": data["stage"].pk if data.get("stage") else None,
                "paper_name": paper.paper_name if paper else (data.get("paper_name") or DEFAULT_PAPER_NAME),
                "part": paper.part if paper else data.get("part"), "session": paper.session if paper else data.get("session"),
            },
            "subject_id": data["subject"].pk if data.get("subject") else None,
            "topic_id": data["topic"].pk if data.get("topic") else None,
            "language": data.get("language", ""),
            "acknowledge_existing": data.get("acknowledge_existing", False),
        }
