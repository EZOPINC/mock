from uuid import uuid4
from django import forms
from exams.models import Topic
from .services import COUNTS


class PracticeStartForm(forms.Form):
    topic = forms.ModelChoiceField(queryset=Topic.objects.none(), required=False, empty_label="All topics")
    count = forms.ChoiceField(label="Number of questions")
    token = forms.UUIDField(widget=forms.HiddenInput, error_messages={
        "required": "Reload this page before starting a session.",
        "invalid": "Reload this page before starting a session.",
    })

    def __init__(self, *args, topic_ids, available_count, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["topic"].queryset = Topic.objects.filter(pk__in=topic_ids)
        self.fields["count"].choices = [(value, value) for value in COUNTS[:-1] if int(value) <= available_count] + [("available", f"Available count ({available_count})")]
        self.fields["token"].initial = uuid4
        self.fields["count"].initial = "available"
