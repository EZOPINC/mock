from django import forms


class PaperChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, paper):
        return " · ".join(str(value) for value in (
            paper.paper_name, paper.stage.name if paper.stage_id else None,
            paper.part, paper.session,
        ) if value)


class PaperSelectionForm(forms.Form):
    paper = PaperChoiceField(queryset=None, label="Paper / stage / shift or session", empty_label="Choose a paper")

    def __init__(self, *args, papers, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["paper"].queryset = papers
