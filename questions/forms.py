from django import forms

from .models import Question, QuestionRevision


CONTENT_FIELDS = ("language", "question_text", "option_a", "option_b", "option_c", "option_d", "correct_answer", "explanation")


class RevisionForm(forms.ModelForm):
    class Meta:
        model = QuestionRevision
        fields = CONTENT_FIELDS


class QuestionAdminForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ("source_question_id", "subject", "topic")


class NewQuestionAdminForm(QuestionAdminForm):
    # Reuse the revision model's field validation on the initial creation page.
    language = QuestionRevision._meta.get_field("language").formfield()
    question_text = forms.CharField(widget=forms.Textarea)
    option_a = forms.CharField(widget=forms.Textarea)
    option_b = forms.CharField(widget=forms.Textarea)
    option_c = forms.CharField(widget=forms.Textarea)
    option_d = forms.CharField(widget=forms.Textarea)
    correct_answer = QuestionRevision._meta.get_field("correct_answer").formfield()
    explanation = forms.CharField(widget=forms.Textarea, required=False)
