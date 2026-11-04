from django import forms

from exams.models import Exam, ExamAuthority, ExamStage
from previous_year.models import PreviousYearPaper


class UploadForm(forms.Form):
    file = forms.FileField(label="CSV or XLSX file", widget=forms.FileInput(attrs={"accept": ".csv,.xlsx"}))
    worksheet = forms.CharField(required=False, max_length=100, help_text="Leave blank for a single-sheet workbook. Otherwise enter its exact worksheet name.")
    authority = forms.ModelChoiceField(queryset=ExamAuthority.objects.all())
    exam = forms.ModelChoiceField(queryset=Exam.objects.select_related("authority"))
    paper = forms.ModelChoiceField(queryset=PreviousYearPaper.objects.filter(is_published=False).select_related("exam"), required=False, label="Existing draft paper")
    year = forms.IntegerField(min_value=1, required=False)
    stage = forms.ModelChoiceField(queryset=ExamStage.objects.select_related("exam"), required=False)
    paper_name = forms.CharField(max_length=200, required=False)
    part = forms.CharField(max_length=100, required=False)
    session = forms.CharField(max_length=100, required=False)
    exam_aliases = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False, max_length=4000, help_text="Explicitly approved labels for the selected exam, one per line. Multiple categories use semicolons or |.")
    paper_aliases = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False, max_length=4000, help_text="Explicitly confirm source paper labels such as Prelims 2023 (Part-I, Session I), one per line.")

    def clean(self):
        data = super().clean()
        exam, authority, paper = data.get("exam"), data.get("authority"), data.get("paper")
        if exam and authority and exam.authority_id != authority.pk:
            self.add_error("exam", "Exam must belong to the selected authority.")
        if paper and exam and paper.exam_id != exam.pk:
            self.add_error("paper", "Paper must belong to the selected exam.")
        if not paper and exam:
            if not data.get("year") or not data.get("paper_name"):
                self.add_error(None, "Choose an existing paper, or provide year and paper name.")
            else:
                candidate = PreviousYearPaper(exam=exam, stage=data.get("stage"), year=data["year"], paper_name=data["paper_name"], part=data.get("part"), session=data.get("session"))
                try:
                    candidate.full_clean()
                except forms.ValidationError as error:
                    self.add_error(None, "; ".join(error.messages))
        return data

    def selection(self):
        data = self.cleaned_data
        return {
            "authority_id": data["authority"].pk, "exam_id": data["exam"].pk,
            "paper_id": data["paper"].pk if data.get("paper") else None,
            "paper": {"year": data.get("year"), "stage_id": data["stage"].pk if data.get("stage") else None,
                      "paper_name": data.get("paper_name", ""), "part": data.get("part", ""), "session": data.get("session", "")},
            "exam_aliases": data.get("exam_aliases", ""), "paper_aliases": data.get("paper_aliases", ""),
        }
