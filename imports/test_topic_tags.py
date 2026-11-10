from questions.models import QuestionTopic
from .services import confirm_import
from .tests import ImportFixture, values
from .validation import validate


class ImportTopicTagTests(ImportFixture):
    def test_confirmation_creates_primary_tag_and_repeat_does_not_duplicate(self):
        data = self.data([values(topic=self.topic.name)])
        batch = confirm_import(data, self.user)
        question = batch.imported_questions.get().question
        self.assertEqual(question.topic_id, self.topic.pk)
        self.assertEqual(list(question.topic_associations.values_list("topic_id", "is_primary")), [(self.topic.pk, True)])
        self.assertEqual(confirm_import(data, self.user).pk, batch.pk)
        self.assertEqual(QuestionTopic.objects.filter(question=question).count(), 1)

    def test_bilingual_rows_create_one_master_and_one_primary_tag(self):
        data = self.data([values(topic=self.topic.name), values(topic=self.topic.name, language="bn")])
        group = validate(data)["groups"][0]
        data["pairings"] = {group["number"]: group["signature"]}
        batch = confirm_import(data, self.user)
        questions = {row.question_id for row in batch.imported_questions.all()}
        self.assertEqual(len(questions), 1)
        self.assertEqual(QuestionTopic.objects.filter(question_id__in=questions, is_primary=True).count(), 1)
