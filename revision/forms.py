from django import forms
from exams.models import Exam, Subject, Part, Module, Chapter, Topic
from questions.models import QuestionTopic
from .selectors import visible_questions
from .models import SavedQuestion


class BankFilters(forms.Form):
    exam = forms.ModelChoiceField(queryset=Exam.objects.none(), required=False, empty_label="All exams")
    subject = forms.ModelChoiceField(queryset=Subject.objects.none(), required=False, empty_label="All subjects")
    part = forms.ModelChoiceField(queryset=Part.objects.none(), required=False, empty_label="All parts")
    module = forms.ModelChoiceField(queryset=Module.objects.none(), required=False, empty_label="All modules")
    chapter = forms.ModelChoiceField(queryset=Chapter.objects.none(), required=False, empty_label="All chapters")
    topic = forms.ModelChoiceField(queryset=Topic.objects.none(), required=False, empty_label="All topics")
    mastery = forms.ChoiceField(required=False, choices=[("", "All statuses"), ("mastered", "Mastered"), ("needs_revision", "Needs revision")])
    sort = forms.ChoiceField(required=False, choices=[("saved_newest", "Newest saved"), ("saved_oldest", "Oldest saved"),
        ("difficulty_asc", "Difficulty: easy to hard"), ("difficulty_desc", "Difficulty: hard to easy")])

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        questions = visible_questions(user).filter(saved_by_users__user=user)
        subjects = questions.values("subject_id")
        self.fields["exam"].queryset = Exam.objects.filter(question_associations__question__in=questions, is_active=True, authority__is_active=True).distinct().order_by("name", "pk")
        self.fields["subject"].queryset = Subject.objects.filter(pk__in=subjects).order_by("name", "pk")
        for kind, model in (("part", Part), ("module", Module), ("chapter", Chapter)):
            self.fields[kind].queryset = model.objects.filter(subject_id__in=subjects).order_by("name", "pk")
        self.fields["topic"].queryset = Topic.objects.filter(pk__in=QuestionTopic.objects.filter(question__in=questions).values("topic_id")).order_by("name", "pk")
        for kind in ("exam", "subject", "part", "module", "chapter", "topic"):
            self.fields[kind].label_from_instance = lambda node: f"{node.name} [{node.code}]"


class NoteForm(forms.ModelForm):
    class Meta:
        model = SavedQuestion
        fields = ("personal_note",)
        widgets = {"personal_note": forms.Textarea(attrs={"rows": 5})}
        help_texts = {"personal_note": "Private to you. Leave blank to delete your note (maximum 10,000 characters)."}


from uuid import uuid4


class RevisionStartForm(BankFilters):
    question_limit = forms.IntegerField(required=False, min_value=1, max_value=10000,
        label="Question limit", help_text="Leave blank for all eligible saved questions, or choose up to 10,000.")
    token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop("sort")
