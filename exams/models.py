from django.db import models
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower, Trim


class HierarchyNode(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    display_order = models.PositiveIntegerField(default=0)
    parent_field = None

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        self.name = self.name.strip()
        if not self.name:
            raise ValidationError({"name": "A name is required."})
        if self.pk and self.parent_field:
            field = self.parent_field + "_id"
            previous = type(self).objects.filter(pk=self.pk).values_list(field, flat=True).first()
            if previous is not None and previous != getattr(self, field):
                raise ValidationError({self.parent_field: "Existing hierarchy nodes cannot be moved to another parent. Create a new node instead."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


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


class Part(HierarchyNode):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="parts")
    parent_field = "subject"

    class Meta:
        ordering = ("subject__name", "display_order", "name", "pk")
        constraints = [
            models.UniqueConstraint(fields=("subject", "slug"), name="exams_part_subject_slug_uniq"),
            models.UniqueConstraint("subject", Lower(Trim("name")), name="exams_part_subject_name_uniq"),
        ]

    def __str__(self):
        return f"{self.subject}: {self.name}"


class Module(HierarchyNode):
    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name="modules")
    parent_field = "part"

    class Meta:
        ordering = ("part_id", "display_order", "name", "pk")
        constraints = [
            models.UniqueConstraint(fields=("part", "slug"), name="exams_module_part_slug_uniq"),
            models.UniqueConstraint("part", Lower(Trim("name")), name="exams_module_part_name_uniq"),
        ]

    def __str__(self):
        return f"{self.part}: {self.name}"


class Chapter(HierarchyNode):
    module = models.ForeignKey(Module, on_delete=models.PROTECT, related_name="chapters")
    parent_field = "module"

    class Meta:
        ordering = ("module_id", "display_order", "name", "pk")
        constraints = [
            models.UniqueConstraint(fields=("module", "slug"), name="exams_chapter_module_slug_uniq"),
            models.UniqueConstraint("module", Lower(Trim("name")), name="exams_chapter_module_name_uniq"),
        ]

    def __str__(self):
        return f"{self.module}: {self.name}"


class Topic(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="topics")
    chapter = models.ForeignKey(Chapter, on_delete=models.PROTECT, related_name="topics", null=True, blank=True)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)

    class Meta:
        ordering = ("name", "pk")
        constraints = [
            models.UniqueConstraint(fields=("subject", "slug"), name="exams_topic_subject_slug_uniq"),
            models.UniqueConstraint("chapter", Lower(Trim("name")), condition=models.Q(chapter__isnull=False), name="exams_topic_chapter_name_uniq"),
        ]

    def __str__(self):
        return f"{self.chapter or self.subject}: {self.name}"

    def clean(self):
        super().clean()
        if self.chapter_id and self.subject_id and self.chapter.module.part.subject_id != self.subject_id:
            raise ValidationError({"chapter": "Chapter must belong to the selected subject."})
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values_list("subject_id", flat=True).first()
            if previous is not None and previous != self.subject_id:
                raise ValidationError({"subject": "An existing topic cannot move to another subject. Create a new topic instead."})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)
