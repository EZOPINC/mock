from django.test import TestCase

from .models import Chapter, Exam, ExamAuthority, Module, Part, Subject, Topic
from .selectors import active_authorities, active_exams


class PublicSelectorTests(TestCase):
    def test_import_and_general_topic_choices_load_all_parent_paths_once(self):
        from imports.forms import UploadForm
        from general_question.forms import GeneralQuestionFilters

        subject = Subject.objects.create(code='H', name='History', slug='history')
        part = Part.objects.create(subject=subject, name='India', slug='india')
        module = Module.objects.create(part=part, name='Ancient', slug='ancient')
        chapter = Chapter.objects.create(module=module, name='Stone Age', slug='stone-age')
        direct_chapter = Chapter.objects.create(subject=subject, name='Direct chapter', slug='direct-chapter')
        part_chapter = Chapter.objects.create(part=part, name='Part chapter', slug='part-chapter')
        root_module = Module.objects.create(subject=subject, name='Root module', slug='root-module')
        root_module_chapter = Chapter.objects.create(module=root_module, name='Root module chapter', slug='root-module-chapter')
        paths = ({}, {'part': part}, {'module': module}, {'module': root_module},
                 {'chapter': chapter}, {'chapter': direct_chapter}, {'chapter': part_chapter},
                 {'chapter': root_module_chapter})
        for index, parents in enumerate(paths):
            Topic.objects.create(subject=subject, name=f'Topic {index}', slug=f'topic-{index}', **parents)
        for form_class in (UploadForm, GeneralQuestionFilters):
            with self.subTest(form=form_class.__name__):
                field = form_class().fields['topic']
                with self.assertNumQueries(1):
                    labels = [label for value, label in field.choices]
                self.assertEqual(len(labels), len(paths) + 1)
                self.assertIn('History: India: Ancient: Stone Age: Topic 4', labels)
                self.assertIn('History: Topic 0', labels)

    def test_active_exam_requires_active_parent(self):
        authority = ExamAuthority.objects.create(name="Active", code="A", slug="active")
        hidden = ExamAuthority.objects.create(name="Hidden", code="H", slug="hidden", is_active=False)
        visible = Exam.objects.create(authority=authority, name="Visible", code="V", slug="visible")
        Exam.objects.create(authority=authority, name="Inactive", code="I", slug="inactive", is_active=False)
        Exam.objects.create(authority=hidden, name="Hidden parent", code="H", slug="hidden-parent")
        self.assertEqual(list(active_exams()), [visible])
        with self.assertNumQueries(2):
            authorities = list(active_authorities())
            self.assertEqual([item.pk for item in authorities], [authority.pk])
            self.assertEqual(authorities[0].available_exams, [visible])
            self.assertEqual(authorities[0].available_exams[0].authority.name, "Active")

    def test_empty_authorities_remain_discoverable(self):
        authority = ExamAuthority.objects.create(name="Empty", code="E", slug="empty")
        self.assertEqual(list(active_exams()), [])
        self.assertEqual(list(active_authorities())[0].pk, authority.pk)
        self.assertEqual(list(active_authorities())[0].available_exams, [])
