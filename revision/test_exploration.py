from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from exams.models import Chapter, Module, Part, Topic
from mock_tests.execution import submit_attempt
from mock_tests.test_execution import ExecutionFixture
from practice.tests import PracticeFixture
from questions.models import QuestionExam
from questions.services import add_translation, create_revision, mark_reviewed, publish_question
from questions.tagging import set_question_topics
from .exploration import load_node, question_paths, related_questions, taxonomy_path
from .models import SavedQuestion
from .sessions import start_revision
from uuid import uuid4


class TopicExplorationTests(PracticeFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.part = Part.objects.create(subject=cls.subject, name="Foundations", slug="foundations", code="P-FOUND")
        cls.module = Module.objects.create(part=cls.part, name="Numbers", slug="numbers", code="M-NUM")
        cls.chapter = Chapter.objects.create(module=cls.module, name="Integers", slug="integers", code="C-INT")
        cls.deep = Topic.objects.create(subject=cls.subject, chapter=cls.chapter, name="Addition", slug="addition", code="T-ADD")
        cls.second = Topic.objects.create(subject=cls.subject, module=cls.module, name="Subtraction", slug="subtraction", code="T-SUB")

    def setUp(self):
        self.client.force_login(self.user)

    def url(self, kind="topic", node=None):
        return reverse("revision:explore", args=[kind, (node or self.deep).pk])

    def question_url(self, question):
        return reverse("revision:question_topics", args=[question.pk])

    def leveled(self, value, **kwargs):
        question = self.question(**kwargs)
        create_revision(question, language="en", question_text="Published related " + value,
            option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="A",
            explanation="AUTHORIZED RELATED EXPLANATION", difficulty_level=value)
        return publish_question(mark_reviewed(question))

    def test_full_and_skipped_paths_use_stored_ids_and_codes_without_queries(self):
        node = load_node("topic", self.deep.pk)
        with self.assertNumQueries(0):
            path = taxonomy_path("topic", node)
        self.assertEqual([(kind, node.code) for kind, node in path],
            [("subject", "M"), ("part", "P-FOUND"), ("module", "M-NUM"), ("chapter", "C-INT"), ("topic", "T-ADD")])
        root_module = Module.objects.create(subject=self.subject, name="Direct module", slug="direct-module")
        root_chapter = Chapter.objects.create(subject=self.subject, name="Direct chapter", slug="direct-chapter")
        part_chapter = Chapter.objects.create(part=self.part, name="Part chapter", slug="part-chapter")
        for parent, expected in (({}, ["subject", "topic"]), ({"part": self.part}, ["subject", "part", "topic"]),
            ({"module": root_module}, ["subject", "module", "topic"]),
            ({"chapter": root_chapter}, ["subject", "chapter", "topic"]),
            ({"chapter": part_chapter}, ["subject", "part", "chapter", "topic"])):
            topic = Topic.objects.create(subject=self.subject, name="Skipped", slug="skipped", **parent)
            loaded = load_node("topic", topic.pk)
            with self.assertNumQueries(0):
                self.assertEqual([kind for kind, _ in taxonomy_path("topic", loaded)], expected)

    def test_question_entry_shows_primary_secondary_paths_and_saved_origin(self):
        source = self.question(topic=self.deep)
        set_question_topics(source, [self.deep.pk, self.second.pk], primary_topic_id=self.deep.pk)
        saved = SavedQuestion.objects.create(user=self.user, question=source)
        response = self.client.get(self.question_url(source))
        self.assertContains(response, "Primary topic")
        self.assertContains(response, "Secondary topic")
        self.assertContains(response, "T-ADD")
        self.assertContains(response, "T-SUB")
        self.assertContains(response, reverse("revision:detail", args=[saved.pk]))
        self.assertContains(response, self.url("module", self.module) + f"?from_question={source.pk}")
        paths = question_paths(source.pk)
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0]["path"][-1]["node"].pk, self.deep.pk)

    def test_descendants_secondary_associations_deduplication_and_current_exclusion(self):
        source = self.question(topic=self.deep)
        secondary = self.question()
        set_question_topics(secondary, [self.topic.pk, self.deep.pk, self.second.pk], primary_topic_id=self.topic.pk)
        module_question = self.question(topic=self.second)
        unrelated = self.question()
        unclassified = self.question(topic=None)
        QuestionExam.objects.create(question=secondary, exam=self.other_exam)
        self.assertEqual(set(related_questions(self.user, "topic", self.deep, source=source).values_list("pk", flat=True)), {secondary.pk})
        for kind, node, expected in (("chapter", self.chapter, {secondary.pk}),
                                    ("module", self.module, {secondary.pk, module_question.pk}),
                                    ("part", self.part, {secondary.pk, module_question.pk}),
                                    ("subject", self.subject, {secondary.pk, module_question.pk, unrelated.pk, unclassified.pk})):
            rows = list(related_questions(self.user, kind, node, source=source))
            self.assertEqual({q.pk for q in rows}, expected)
            self.assertEqual(len(rows), len(expected))
        response = self.client.get(self.url("module", self.module), {"from_question": source.pk})
        self.assertEqual(response.context["page"].paginator.count, 2)
        self.assertNotIn(source.pk, [q.pk for q in response.context["page"]])

    def test_exam_and_case_normalized_difficulty_filters(self):
        easy = self.leveled(" eAsY ", topic=self.deep)
        hard = self.leveled("Hard", topic=self.deep, exam=self.other_exam)
        unknown = self.question(topic=self.deep)
        QuestionExam.objects.create(question=easy, exam=self.other_exam)
        response = self.client.get(self.url(), {"exam": self.other_exam.pk, "difficulty": "level:easy"})
        self.assertEqual([q.pk for q in response.context["page"]], [easy.pk])
        self.assertEqual(self.client.get(self.url(), {"difficulty": "level:hard"}).context["page"].paginator.count, 1)
        self.assertEqual([q.pk for q in self.client.get(self.url(), {"difficulty": "level:"}).context["page"]], [unknown.pk])
        invalid = self.client.get(self.url(), {"exam": "999999", "difficulty": "invented"})
        self.assertTrue(invalid.context["form"].errors)
        self.assertEqual(invalid.context["page"].paginator.count, 0)

    def test_unpublished_inactive_incomplete_unsupported_and_drafts_are_excluded(self):
        good = self.question(topic=self.deep)
        self.question(topic=self.deep, published=False)
        self.question(topic=self.deep, exam=self.other_exam)
        self.other_exam.is_active = False
        self.other_exam.save()
        unsupported = self.question(topic=self.deep)
        incomplete = self.question(topic=self.deep)
        no_exam = self.question(topic=self.deep)
        no_exam.exam_associations.all().delete()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE questions_questiontranslation SET language='xx' WHERE revision_id=%s", [unsupported.published_revision_id])
            cursor.execute("UPDATE questions_questiontranslation SET option_a='   ' WHERE revision_id=%s", [incomplete.published_revision_id])
        create_revision(good, language="en", question_text="SECRET WORKING DRAFT", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="D")
        response = self.client.get(self.url())
        self.assertEqual([q.pk for q in response.context["page"]], [good.pk])
        self.assertNotContains(response, "SECRET WORKING DRAFT")
        self.assertContains(response, "VERIFIED SOLUTION")

    def test_bilingual_explanations_and_bookmark_state_remain_personal(self):
        question = self.leveled("Easy", topic=self.deep)
        add_translation(question, language="bn", question_text="\u09ac\u09be\u0982\u09b2\u09be", option_a="A", option_b="B", option_c="C", option_d="D", explanation="BENGALI EXPLANATION")
        publish_question(mark_reviewed(question))
        saved = SavedQuestion.objects.create(user=self.user, question=question, personal_note="My private note", review_count=4, is_mastered=True)
        response = self.client.get(self.url())
        self.assertContains(response, "\u09ac\u09be\u0982\u09b2\u09be")
        self.assertContains(response, "AUTHORIZED RELATED EXPLANATION")
        self.assertContains(response, "BENGALI EXPLANATION")
        self.assertContains(response, "Saved for revision")
        self.assertNotContains(response, "My private note")
        self.client.post(reverse("revision:save", args=[question.pk]), HTTP_ACCEPT="application/json")
        saved.refresh_from_db()
        self.assertEqual((saved.personal_note, saved.review_count, saved.is_mastered), ("My private note", 4, True))
        self.client.force_login(self.other_user)
        self.assertContains(self.client.get(self.url()), "Save for revision")
        self.assertNotContains(self.client.get(self.url()), "Saved for revision")
        self.client.post(reverse("revision:unsave", args=[question.pk]), HTTP_ACCEPT="application/json")
        self.assertTrue(SavedQuestion.objects.filter(pk=saved.pk).exists())

    def test_login_and_origin_ownership_private_saved_content(self):
        public = self.question(topic=self.deep)
        other_saved = SavedQuestion.objects.create(user=self.other_user, question=public, personal_note="OTHER USER NOTE")
        response = self.client.get(self.question_url(public))
        self.assertIsNone(response.context["saved_source"])
        self.assertNotContains(response, reverse("revision:detail", args=[other_saved.pk]))
        self.assertNotContains(response, "OTHER USER NOTE")
        private = self.question(published=False, topic=self.deep)
        SavedQuestion.objects.create(user=self.other_user, question=private)
        self.assertEqual(self.client.get(self.question_url(private)).status_code, 404)
        self.assertEqual(self.client.get(self.url(), {"from_question": private.pk}).status_code, 404)
        self.assertEqual(self.client.get(self.url(), {"from_question": "bad"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("revision:explore", args=["invalid", self.deep.pk])).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url()).status_code, 302)
        self.assertEqual(self.client.get(self.question_url(public)).status_code, 302)

    def test_no_topic_subject_entry_and_clear_empty_state(self):
        source = self.question(topic=None)
        response = self.client.get(self.question_url(source))
        self.assertContains(response, "No topics are assigned")
        self.assertContains(response, self.url("subject", self.subject))
        self.assertContains(self.client.get(self.url(), {"from_question": source.pk}), "No eligible related questions")
        self.assertEqual(self.client.post(self.url()).status_code, 405)

    def test_pagination_preserves_source_exam_and_difficulty(self):
        source = self.question(topic=self.deep)
        for _ in range(21):
            self.leveled("Easy", topic=self.deep)
        data = {"from_question": source.pk, "exam": self.exam.pk, "difficulty": "level:easy"}
        first = self.client.get(self.url(), data)
        self.assertEqual(len(first.context["page"]), 20)
        self.assertContains(first, f"from_question={source.pk}&amp;exam={self.exam.pk}&amp;difficulty=level%3Aeasy&amp;page=2")
        last = self.client.get(self.url(), data | {"page": 2})
        self.assertEqual(len(last.context["page"]), 1)
        self.assertNotIn(last.context["page"][0].pk, [q.pk for q in first.context["page"]])
        self.assertNotIn(source.pk, [q.pk for q in first.context["page"]])

    def test_query_count_does_not_grow_with_rows_or_topic_paths(self):
        question = self.question(topic=self.deep)
        with CaptureQueriesContext(connection) as initial:
            self.client.get(self.url())
        for _ in range(4):
            self.question(topic=self.deep)
        with CaptureQueriesContext(connection) as expanded:
            self.client.get(self.url())
        self.assertEqual(len(initial), len(expanded))
        self.assertLess(len(expanded), 25)
        with CaptureQueriesContext(connection) as one:
            self.client.get(self.question_url(question))
        set_question_topics(question, [self.deep.pk, self.second.pk, self.topic.pk], primary_topic_id=self.deep.pk)
        with CaptureQueriesContext(connection) as many:
            self.client.get(self.question_url(question))
        self.assertEqual(len(one), len(many))

    def test_exploration_and_related_bookmarks_do_not_change_revision_history(self):
        source = self.question(topic=self.deep)
        related = self.question(topic=self.deep)
        saved = SavedQuestion.objects.create(user=self.user, question=source, personal_note="Preserved", review_count=2, is_mastered=True)
        session = start_revision(self.user, {"token": uuid4()})
        before = list(session.questions.values())
        self.client.get(self.question_url(source))
        self.client.get(self.url(), {"from_question": source.pk})
        self.client.post(reverse("revision:save", args=[related.pk]), HTTP_ACCEPT="application/json")
        self.assertContains(self.client.get(self.url(), {"from_question": source.pk}), "Saved for revision")
        self.client.post(reverse("revision:unsave", args=[related.pk]), HTTP_ACCEPT="application/json")
        self.assertEqual(before, list(session.questions.values()))
        saved.refresh_from_db()
        self.assertEqual((saved.personal_note, saved.review_count, saved.is_mastered), ("Preserved", 2, True))


class MockExplorationConfidentialityTests(ExecutionFixture):
    def test_active_mock_has_no_entrypoint_and_direct_scopes_are_blocked(self):
        attempt = self.ready_attempt()
        row = attempt.questions.get()
        related = self.question()
        create_revision(related, language="en", question_text="CONFIDENTIAL RELATED STEM", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="A", explanation="RELATED ANSWER SENTINEL")
        publish_question(mark_reviewed(related))
        self.client.force_login(self.user)
        before = type(attempt).objects.filter(pk=attempt.pk).values().get()
        self.assertNotContains(self.client.get(self.detail_url(attempt)), "Explore Topic")
        self.assertEqual(self.client.get(reverse("revision:question_topics", args=[row.question_id])).status_code, 404)
        with self.assertRaises(PermissionDenied):
            related_questions(self.user, "topic", self.topic)
        for kind, node in (("topic", self.topic), ("subject", self.subject)):
            response = self.client.get(reverse("revision:explore", args=[kind, node.pk]))
            self.assertEqual(response.status_code, 403)
            self.assertNotContains(response, "CONFIDENTIAL RELATED STEM", status_code=403)
            self.assertNotContains(response, "RELATED ANSWER SENTINEL", status_code=403)
        self.assertEqual(before, type(attempt).objects.filter(pk=attempt.pk).values().get())
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(reverse("revision:explore", args=["topic", self.topic.pk])).status_code, 200)
        self.client.force_login(self.user)
        submit_attempt(self.user, attempt.pk, expected_version=attempt.save_version)
        self.assertNotContains(self.client.get(reverse("mock_tests:results", args=[attempt.pk])), "Explore Topic")
        self.assertContains(self.client.get(reverse("revision:explore", args=["topic", self.topic.pk])), "RELATED ANSWER SENTINEL")


class ExplorationEntryPointTests(ExecutionFixture):
    def test_question_cards_omit_topic_controls_and_preserve_bookmarks(self):
        from practice.services import start_session
        from previous_year.models import PaperQuestion, PreviousYearPaper
        from previous_year.services import publish_paper
        attempt = self.ready_attempt()
        row = attempt.questions.get()
        submit_attempt(self.user, attempt.pk, expected_version=attempt.save_version)
        saved = SavedQuestion.objects.create(user=self.user, question=row.question)
        paper = PreviousYearPaper.objects.create(exam=self.exam, year=2025, paper_name="Explore source")
        PaperQuestion.objects.create(paper=paper, question_revision=row.question_revision, question_number="1", display_order=1)
        publish_paper(paper)
        practice = start_session(self.user, exam=self.exam, subject=self.subject, token=uuid4())
        paper_url = reverse("previous_year:paper_detail", args=[self.exam.authority.slug, self.exam.slug, 2025, paper.pk])
        self.client.force_login(self.user)
        topics_url = reverse("revision:question_topics", args=[row.question_id])
        for url in (reverse("revision:dashboard"), reverse("revision:detail", args=[saved.pk]),
                    reverse("practice:session", args=[practice.pk]), paper_url, paper_url + "?mode=practice",
                    reverse("mock_tests:results", args=[attempt.pk])):
            response = self.client.get(url)
            self.assertNotContains(response, "Explore Topic")
            self.assertNotContains(response, topics_url)
        self.assertContains(self.client.get(paper_url), "Saved for revision")
        self.assertContains(self.client.get(reverse("practice:session", args=[practice.pk])), "Saved for revision")
        self.assertContains(self.client.get(topics_url), reverse("revision:detail", args=[saved.pk]))
        self.client.logout()
        self.assertNotContains(self.client.get(paper_url + "?mode=practice"), "Sign in to explore topics")
