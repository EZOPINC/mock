from django import forms

from exams.models import Chapter, Exam, Module, Subject
from exams.selectors import topics_with_ancestry
from questions.forms import TopicSubjectSelect, TopicSubjectSelectMultiple
from questions.models import Question, QuestionKind, QuestionRevision, TRANSLATED_FIELDS
from .forms import GeneralQuestionFilters


class ReviewFilters(GeneralQuestionFilters):
    exam = forms.ModelChoiceField(queryset=Exam.objects.select_related("authority"), required=False)
    batch = forms.IntegerField(required=False, min_value=1, label="Import batch ID")
    source = forms.ChoiceField(choices=[("", "All sources"), ("previous_year", "Previous-Year Papers"),
        ("general", "General Questions")], required=False)
    year = forms.IntegerField(required=False, min_value=1, max_value=2147483647, label="Paper year")
    text = forms.CharField(required=False, max_length=200, label="Question text")
    module = forms.ModelChoiceField(queryset=Module.objects.select_related("subject", "part__subject"), required=False)
    chapter = forms.ModelChoiceField(queryset=Chapter.objects.select_related(
        "subject", "part__subject", "module__subject", "module__part__subject",
        "submodule__module__subject", "submodule__module__part__subject"), required=False)
    review = forms.ChoiceField(choices=[("", "Any review status"), *Question.ReviewStatus.choices], required=False)
    publication = forms.ChoiceField(choices=[("", "Any publication status"), *Question.PublicationStatus.choices], required=False)
    kind = forms.ChoiceField(choices=[("", "Any kind"), *QuestionKind.choices], required=False)


class ReviewEditForm(forms.Form):
    subject = forms.ModelChoiceField(queryset=Subject.objects.all())
    topic = forms.ModelChoiceField(queryset=topics_with_ancestry(), required=False,
        label="Primary topic", widget=TopicSubjectSelect)
    additional_topics = forms.ModelMultipleChoiceField(queryset=topics_with_ancestry(), required=False,
        widget=TopicSubjectSelectMultiple(attrs={"size": 6}))
    exams = forms.ModelMultipleChoiceField(queryset=Exam.objects.select_related("authority"), required=False)
    question_kind = forms.ChoiceField(choices=QuestionKind.choices)
    current_as_of = forms.DateField(required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    expires_on = forms.DateField(required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    correct_answer = forms.ChoiceField(choices=QuestionRevision._meta.get_field("correct_answer").choices)
    difficulty_level = forms.CharField(required=False, max_length=100)
    content_fields = ("correct_answer", "difficulty_level")

    def __init__(self, *args, question, **kwargs):
        revision = question.current_revision
        initial = {name: getattr(question, name) for name in ("question_kind", "current_as_of", "expires_on")}
        initial.update(subject=question.subject_id, topic=question.topic_id,
            exams=[exam.pk for exam in question.exams.all()],
            additional_topics=list(question.topic_associations.filter(is_primary=False).values_list("topic_id", flat=True)),
            correct_answer=revision.correct_answer, difficulty_level=revision.difficulty_level)
        super().__init__(*args, initial=initial, **kwargs)
        subject = self.data.get("subject") if self.is_bound else question.subject_id
        for name in ("topic", "additional_topics"):
            self.fields[name].widget.allowed_subject_id = subject
        self.editions = []
        for edition in revision.translations.all():
            fields = []
            for name in TRANSLATED_FIELDS:
                key = f"{name}_{edition.language}"
                self.fields[key] = forms.CharField(label=name.replace("_", " ").capitalize(),
                    strip=False, required=name != "explanation",
                    widget=forms.Textarea(attrs={"rows": 3}) if name in {"question_text", "explanation"} else forms.TextInput())
                self.initial[key] = getattr(edition, name)
                fields.append(self[key])
            self.editions.append((edition.get_language_display(), fields))
        self.metadata = [self[name] for name in ("subject", "topic", "additional_topics", "exams", "question_kind", "current_as_of", "expires_on")]
        self.shared_content = [self[name] for name in self.content_fields]

    def clean(self):
        cleaned = super().clean()
        subject, primary = cleaned.get("subject"), cleaned.get("topic")
        additional = list(cleaned.get("additional_topics") or ())
        if additional and not primary:
            self.add_error("topic", "Select a primary topic when assigning additional topics.")
        if primary in additional:
            self.add_error("additional_topics", "The primary topic cannot also be an additional topic.")
        if subject and any(topic.subject_id != subject.pk for topic in ([primary] if primary else []) + additional):
            self.add_error("topic", "Choose topics from the selected subject.")
        return cleaned
