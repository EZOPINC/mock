from copy import deepcopy
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from exams.models import Part, Module, Chapter, Topic
from questions.services import add_translation, create_revision, mark_reviewed, publish_question
from questions.tagging import set_question_topics
from .discovery import PracticeTaxonomy
from .forms import PracticeStartForm
from .models import PracticeSession
from .services import start_session, submit_answer, progress
from .tests import PracticeFixture


class PracticeTaxonomyTests(PracticeFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.part = Part.objects.create(subject=cls.subject, name="India", slug="india")
        cls.module = Module.objects.create(part=cls.part, name="Foundations", slug="foundations")
        cls.chapter = Chapter.objects.create(module=cls.module, name="Numbers", slug="numbers")
        cls.deep = Topic.objects.create(subject=cls.subject, chapter=cls.chapter, name="Deep topic", slug="deep")

    def test_each_level_includes_descendants_and_primary_secondary_tags(self):
        primary = self.question(topic=self.deep)
        secondary = self.question()
        set_question_topics(secondary, [self.topic.pk, self.deep.pk], primary_topic_id=self.topic.pk)
        unclassified = self.question(topic=None)
        scope = PracticeTaxonomy(self.exam, self.subject)
        for kind, node in (("part", self.part), ("module", self.module), ("chapter", self.chapter), ("topic", self.deep)):
            self.assertEqual(scope.selected_ids({kind: node}), {primary.pk, secondary.pk})
            session = self.session(**{kind: node})
            self.assertEqual(set(session.questions.values_list("question_id", flat=True)), {primary.pk, secondary.pk})
        self.assertEqual(scope.selected_ids({}), {primary.pk, secondary.pk, unclassified.pk})
        self.assertEqual(self.session().questions.count(), 3)

    def test_all_skipped_parent_relationships(self):
        root_module = Module.objects.create(subject=self.subject, name="Root module", slug="root-module")
        root_chapter = Chapter.objects.create(subject=self.subject, name="Root chapter", slug="root-chapter")
        part_chapter = Chapter.objects.create(part=self.part, name="Part chapter", slug="part-chapter")
        parent_paths = [{}, {"part": self.part}, {"module": root_module}, {"chapter": root_chapter},
                        {"chapter": part_chapter}, {"module": self.module}, {"chapter": self.chapter}]
        for index, parent in enumerate(parent_paths):
            topic = Topic.objects.create(subject=self.subject, name=f"Skipped {index}", slug=f"skipped-{index}", **parent)
            question = self.question(topic=topic)
            scope = PracticeTaxonomy(self.exam, self.subject)
            self.assertEqual(scope.selected_ids(parent | {"topic": topic}), {question.pk})

    def test_multiple_tags_under_same_parent_never_duplicate_question(self):
        extra = Topic.objects.create(subject=self.subject, chapter=self.chapter, name="More", slug="more")
        question = self.question(topic=self.deep)
        set_question_topics(question, [self.deep.pk, extra.pk], primary_topic_id=self.deep.pk)
        scope = PracticeTaxonomy(self.exam, self.subject)
        self.assertEqual(scope.pools["part"][self.part.pk], {question.pk})
        self.assertEqual(self.session(part=self.part).questions.count(), 1)

    def test_filters_respect_exam_publication_language_and_complete_options(self):
        good = self.question(topic=self.deep)
        self.question(topic=self.deep, exam=self.other_exam)
        self.question(topic=self.deep, published=False)
        unsupported = self.question(topic=self.deep)
        incomplete = self.question(topic=self.deep)
        with connection.cursor() as cursor:
            cursor.execute("UPDATE questions_questiontranslation SET option_b = '   ' WHERE revision_id = %s", [incomplete.published_revision_id])
            cursor.execute("UPDATE questions_questiontranslation SET language = 'xx' WHERE revision_id = %s", [unsupported.published_revision_id])
        self.assertEqual(PracticeTaxonomy(self.exam, self.subject).selected_ids({"part": self.part}), {good.pk})

    def test_cross_subject_and_unrelated_branch_filters_are_rejected(self):
        self.question(topic=self.deep)
        unrelated = Part.objects.create(subject=self.subject, name="World", slug="world")
        foreign = Part.objects.create(subject=self.other_subject, name="Foreign", slug="foreign")
        for filters in ({"part": foreign}, {"topic": self.other_topic}, {"part": unrelated, "chapter": self.chapter}):
            with self.assertRaises(ValidationError):
                self.session(**filters)
        self.assertFalse(PracticeSession.objects.exists())

    def test_empty_and_insufficient_pools_fail_without_partial_session(self):
        self.question()
        for filters in ({"part": self.part}, {"count": "10"}, {"count": "5"}):
            with self.assertRaises(ValidationError):
                self.session(**filters)
        self.assertFalse(PracticeSession.objects.exists())

    def test_bilingual_master_is_selected_once_and_feedback_stays_locked(self):
        question = self.question(topic=self.deep, language="bn", question_text="বাংলা প্রশ্ন")
        add_translation(question, language="en", question_text="English question", option_a="A", option_b="B", option_c="C", option_d="D")
        publish_question(mark_reviewed(question))
        session = self.session(chapter=self.chapter)
        row = session.questions.get()
        self.client.force_login(self.user)
        response = self.client.get(self.session_url(session))
        self.assertContains(response, "বাংলা প্রশ্ন")
        self.assertContains(response, "English question")
        self.assertNotContains(response, "VERIFIED SOLUTION")
        self.assertFalse(submit_answer(self.user, session.pk, row.pk, "B").is_correct)
        with self.assertRaises(ValidationError):
            submit_answer(self.user, session.pk, row.pk, "A")
        self.assertEqual(progress(session.questions.all())["incorrect"], 1)

    def test_resume_after_retagging_preserves_frozen_revision_filters_and_scoring(self):
        question = self.question(topic=self.deep)
        token = uuid4()
        session = self.session(part=self.part, topic=self.deep, token=token)
        frozen = deepcopy(session.configuration)
        row = session.questions.get()
        revision_id = row.question_revision_id
        set_question_topics(question, [self.topic.pk], primary_topic_id=self.topic.pk)
        create_revision(question, language="en", question_text="Later", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="D")
        publish_question(mark_reviewed(question))
        self.assertEqual(self.session(part=self.part, topic=self.deep, token=token).pk, session.pk)
        self.assertTrue(submit_answer(self.user, session.pk, row.pk, "A").is_correct)
        session.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual(session.configuration, frozen)
        self.assertEqual(row.question_revision_id, revision_id)
        self.assertEqual(session.status, "completed")
        self.client.force_login(self.user)
        self.assertRedirects(self.client.post(self.configure_url(), {"part": self.part.pk, "topic": self.deep.pk, "count": "available", "token": token}), self.session_url(session))
        with self.assertRaises(ValidationError):
            self.session(token=token)
        self.assertEqual(PracticeSession.objects.count(), 1)

    def test_legacy_session_configuration_without_new_filters_still_resumes(self):
        question = self.question()
        token = uuid4()
        session = self.session(token=token, topic=self.topic)
        with connection.cursor() as cursor:
            cursor.execute("UPDATE practice_practicesession SET configuration = configuration - 'taxonomy_filters' WHERE id = %s", [session.pk])
        set_question_topics(question, [], primary_topic_id=None)
        self.assertEqual(self.session(token=token, topic=self.topic).pk, session.pk)

    def test_preview_lists_only_eligible_options_with_counts_and_no_answers(self):
        self.question(topic=self.deep)
        empty = Part.objects.create(subject=self.subject, name="Unavailable branch", slug="empty")
        self.client.force_login(self.user)
        response = self.client.get(self.configure_url())
        self.assertContains(response, 'id="id_part"')
        self.assertContains(response, 'id="id_module"')
        self.assertContains(response, 'id="id_chapter"')
        self.assertContains(response, "practice-filters.js")
        self.assertNotContains(response, empty.name)
        payload = response.context["taxonomy_options"]
        self.assertEqual(payload["part"][0]["count"], 1)
        self.assertNotIn("correct_answer", str(payload))
        self.assertNotIn("question_ids", str(payload))

    def test_invalid_browser_filter_combinations_and_foreign_ids_are_rejected(self):
        self.question(topic=self.deep)
        unrelated = Part.objects.create(subject=self.subject, name="Other", slug="other")
        self.question(topic=Topic.objects.create(subject=self.subject, part=unrelated, name="Other topic", slug="other-topic"))
        self.client.force_login(self.user)
        for filters in ({"part": unrelated.pk, "chapter": self.chapter.pk}, {"topic": self.other_topic.pk}):
            response = self.client.post(self.configure_url(), {"token": uuid4(), "count": "available", **filters})
            self.assertEqual(response.status_code, 400)
        self.assertFalse(PracticeSession.objects.exists())

    def test_empty_subject_has_clear_state_and_disabled_start(self):
        self.client.force_login(self.user)
        response = self.client.get(self.configure_url())
        self.assertContains(response, "No eligible questions are available")
        self.assertContains(response, "data-practice-start disabled")

    def test_query_count_does_not_grow_with_question_or_tag_count(self):
        self.question(topic=self.deep)
        with CaptureQueriesContext(connection) as initial:
            PracticeTaxonomy(self.exam, self.subject)
        for _ in range(4):
            question = self.question(topic=self.deep)
            set_question_topics(question, [self.deep.pk, self.topic.pk], primary_topic_id=self.deep.pk)
        with CaptureQueriesContext(connection) as expanded:
            scope = PracticeTaxonomy(self.exam, self.subject)
        self.assertEqual(len(initial), len(expanded))
        with self.assertNumQueries(0):
            scope.selected_ids({"part": self.part})
            scope.options()

    def test_form_option_rendering_does_not_query_each_ancestor(self):
        self.question(topic=self.deep)
        scope = PracticeTaxonomy(self.exam, self.subject)
        form = PracticeStartForm(scope=scope, available_count=1)
        with self.assertNumQueries(4):
            html = form.as_p()
        self.assertIn("Deep topic (1)", html)
