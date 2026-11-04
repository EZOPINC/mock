from django.db import models


class ExamAuthority(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=200, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name", "pk")
        verbose_name_plural = "exam authorities"

    def __str__(self):
        return self.name


class Exam(models.Model):
    authority = models.ForeignKey(ExamAuthority, on_delete=models.PROTECT, related_name="exams")
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50)
    slug = models.SlugField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name", "pk")
        constraints = [
            models.UniqueConstraint(fields=("authority", "code"), name="exams_exam_authority_code_uniq"),
            models.UniqueConstraint(fields=("authority", "slug"), name="exams_exam_authority_slug_uniq"),
        ]

    def __str__(self):
        return f"{self.authority}: {self.name}"


class ExamStage(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name="stages")
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("display_order", "name", "pk")
        constraints = [
            models.UniqueConstraint(fields=("exam", "code"), name="exams_stage_exam_code_uniq"),
        ]

    def __str__(self):
        return f"{self.exam}: {self.name}"


class Subject(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=200, unique=True)

    class Meta:
        ordering = ("name", "pk")

    def __str__(self):
        return self.name


class Topic(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="topics")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)

    class Meta:
        ordering = ("name", "pk")
        constraints = [
            models.UniqueConstraint(fields=("subject", "slug"), name="exams_topic_subject_slug_uniq"),
        ]

    def __str__(self):
        return f"{self.subject}: {self.name}"
