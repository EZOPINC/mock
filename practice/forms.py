from uuid import uuid4
from django import forms
from exams.models import Topic
from .discovery import LEVELS, MODELS
from .services import COUNTS


class PracticeStartForm(forms.Form):
    topic = forms.ModelChoiceField(queryset=Topic.objects.none(), required=False, empty_label="All topics")
    count = forms.ChoiceField(label="Number of questions")
    token = forms.UUIDField(widget=forms.HiddenInput, error_messages={
        "required": "Reload this page before starting a session.",
        "invalid": "Reload this page before starting a session.",
    })

    def __init__(self, *args, topic_ids=(), available_count, scope=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["topic"].queryset = Topic.objects.filter(pk__in=topic_ids)
        self.scope = scope
        if scope:
            for kind in LEVELS:
                self.fields[kind] = forms.ModelChoiceField(queryset=MODELS[kind].objects.filter(pk__in=scope.pools[kind]),
                    required=False, empty_label=f"All {kind}s", label=kind.title())
                # Avoid HierarchyNode.__str__ traversing parent FKs for every option.
                self.fields[kind].label_from_instance = lambda node, level=kind: f"{node.name} ({len(scope.pools[level][node.pk])})"
            self.order_fields([*LEVELS, "count", "token"])
        self.fields["count"].choices = [(value, value) for value in COUNTS[:-1] if int(value) <= available_count] + [("available", f"Available count ({available_count})")]
        self.fields["token"].initial = uuid4
        self.fields["count"].initial = "available"

    def clean(self):
        cleaned = super().clean()
        if self.scope and not self.errors:
            ids = self.scope.selected_ids(cleaned)
            count = cleaned.get("count")
            if not ids or (count != "available" and int(count) > len(ids)):
                raise forms.ValidationError("Insufficient eligible questions. Select another filter or question count.")
        return cleaned
