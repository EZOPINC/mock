from django import forms
from exams.models import Topic

from .models import Question, QuestionRevision, QuestionTranslation, TRANSLATED_FIELDS


CONTENT_FIELDS = ("language", "question_text", "option_a", "option_b", "option_c", "option_d", "correct_answer", "explanation")


class TopicSubjectOptions:
    allowed_subject_id = None

    def create_option(self, *args, **kwargs):
        option = super().create_option(*args, **kwargs)
        instance = getattr(option["value"], "instance", None)
        if instance is not None:
            option["attrs"]["data-subject-id"] = str(instance.subject_id)
            if str(instance.subject_id) != str(self.allowed_subject_id):
                option["attrs"].update(disabled=True, hidden=True)
        return option


class TopicSubjectSelect(TopicSubjectOptions, forms.Select):
    pass


class TopicSubjectSelectMultiple(TopicSubjectOptions, forms.SelectMultiple):
    pass


class RevisionForm(forms.ModelForm):
    class Meta:
        model = QuestionRevision
        fields = CONTENT_FIELDS + ("difficulty_level",)


class TranslationForm(forms.ModelForm):
    class Meta:
        model = QuestionTranslation
        fields = ("language",) + TRANSLATED_FIELDS


class QuestionAdminForm(forms.ModelForm):
    additional_topics = forms.ModelMultipleChoiceField(
        queryset=Topic.objects.none(), required=False,
        widget=TopicSubjectSelectMultiple(attrs={"size": 6}),
        help_text="Optional secondary topics from the same subject. Select a primary topic above whenever any topics are assigned.",
    )

    class Meta:
        model = Question
        fields = ("source_question_id", "subject", "topic")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        subject_id = self.data.get(self.add_prefix("subject")) if self.is_bound else self.initial.get("subject", self.instance.subject_id)
        subject_id = getattr(subject_id, "pk", subject_id)
        self.fields["topic"].label = "Primary topic"
        existing_widget = self.fields["topic"].widget
        if hasattr(existing_widget, "widget"):
            # Keep Django Admin's related-object controls around the scoped select.
            existing_widget.widget = TopicSubjectSelect()
        else:
            self.fields["topic"].widget = TopicSubjectSelect()
        catalogue = Topic.objects.select_related("subject", "part__subject", "module__subject", "module__part__subject", "chapter__subject", "chapter__part__subject", "chapter__module__subject", "chapter__module__part__subject")
        if self.is_bound:
            catalogue = catalogue.filter(subject_id=int(subject_id)) if str(subject_id).isdigit() else catalogue.none()
        for field in ("topic", "additional_topics"):
            self.fields[field].widget.allowed_subject_id = subject_id
            if hasattr(self.fields[field].widget, "widget"):
                self.fields[field].widget.widget.allowed_subject_id = subject_id
            self.fields[field].queryset = catalogue
        if self.instance.pk and not self.is_bound:
            self.initial["additional_topics"] = list(self.instance.topic_associations.filter(is_primary=False).values_list("topic_id", flat=True))

    def clean(self):
        cleaned = super().clean()
        primary = cleaned.get("topic")
        extra = list(cleaned.get("additional_topics", []))
        if extra and not primary:
            self.add_error("topic", "Select a primary topic when assigning additional topics.")
        if primary and any(topic.pk == primary.pk for topic in extra):
            self.add_error("additional_topics", "The primary topic must not also be an additional topic.")
        raw = self.data.getlist(self.add_prefix("additional_topics")) if hasattr(self.data, "getlist") else self.data.get(self.add_prefix("additional_topics"), [])
        if len(raw) != len(set(raw)):
            self.add_error("additional_topics", "Duplicate topic assignments are not allowed.")
        return cleaned


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
    difficulty_level = forms.CharField(max_length=100, required=False)
