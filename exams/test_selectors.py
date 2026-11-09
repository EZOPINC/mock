from django.test import TestCase

from .models import Exam, ExamAuthority
from .selectors import active_authorities, active_exams


class PublicSelectorTests(TestCase):
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
