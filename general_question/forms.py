from django import forms

from exams.models import Exam, Subject, Topic


class GeneralQuestionFilters(forms.Form):
    exam = forms.ModelChoiceField(queryset=Exam.objects.filter(is_active=True, authority__is_active=True).select_related("authority"), required=False)
    subject = forms.ModelChoiceField(queryset=Subject.objects.all(), required=False)
    topic = forms.ModelChoiceField(queryset=Topic.objects.select_related("subject"), required=False)
    language = forms.ChoiceField(choices=(("", "All languages"), ("en", "English"), ("bn", "Bengali")), required=False)
