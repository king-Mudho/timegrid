"""
Django models for Melsoft TimeGrid timetable application.
(Updated: normalized availability handling and small safety improvements.)
"""
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
import json


class SchoolSettings(models.Model):
    """
    Global school configuration for timetable generation.
    Should have only one instance.
    """
    school_name = models.CharField(max_length=200, default="My School")
    academic_year = models.CharField(max_length=20, default="2024-2025")
    days_per_week = models.IntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(7)],
        help_text="Number of working days per week (typically 5)"
    )
    lesson_start_time = models.TimeField(default="08:00:00", help_text="First lesson start time")
    lesson_duration_min = models.IntegerField(default=45, help_text="Duration of each lesson in minutes")
    periods_before_break = models.IntegerField(default=2, help_text="Number of periods before first break")
    break_duration_min = models.IntegerField(default=15, help_text="Short break duration in minutes")
    periods_after_break = models.IntegerField(default=2, help_text="Periods between break and lunch")
    lunch_duration_min = models.IntegerField(default=45, help_text="Lunch break duration in minutes")

    class Meta:
        verbose_name = "School Settings"
        verbose_name_plural = "School Settings"

    def __str__(self):
        return f"{self.school_name} - {self.academic_year}"

    def save(self, *args, **kwargs):
        # Ensure only one settings instance exists
        if not self.pk and SchoolSettings.objects.exists():
            self.pk = SchoolSettings.objects.first().pk
        super().save(*args, **kwargs)


class Subject(models.Model):
    """
    Academic subject with scheduling metadata.
    """
    SUBJECT_TYPE_CHOICES = [
        ('theory', 'Theory'),
        ('practical', 'Practical'),
    ]

    DIFFICULTY_CHOICES = [
        ('easy', 'Easy'),
        ('fair', 'Fair'),
        ('difficult', 'Difficult'),
    ]

    ROOM_TYPE_CHOICES = [
        ('classroom', 'Regular Classroom'),
        ('lab', 'Laboratory'),
        ('computer_lab', 'Computer Lab'),
        ('gym', 'Gymnasium'),
        ('art_room', 'Art Room'),
        ('music_room', 'Music Room'),
    ]

    name = models.CharField(max_length=100, unique=True)
    weekly_periods = models.IntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Required periods per week"
    )
    subject_type = models.CharField(max_length=20, choices=SUBJECT_TYPE_CHOICES, default='theory')
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, default='fair')
    requires_room_type = models.CharField(
        max_length=30,
        choices=ROOM_TYPE_CHOICES,
        default='classroom',
        help_text="Type of room required for this subject"
    )
    requires_consecutive_periods = models.BooleanField(
        default=False,
        help_text="Should be scheduled in double periods"
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.weekly_periods}p/week)"


class Teacher(models.Model):
    """
    Teacher with availability and subject competencies.
    """
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    subjects = models.ManyToManyField(Subject, related_name='teachers', blank=True)
    max_periods_week = models.IntegerField(
        default=25,
        validators=[MinValueValidator(1), MaxValueValidator(50)],
        help_text="Maximum teaching periods per week"
    )
    availability = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON: {day_index: {period_index: true/false}}"
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_availability_dict(self):
        """Parse availability JSON safely and normalize keys to strings for consistent lookup."""
        # Accept both dict or JSON string, then ensure nested keys are strings
        raw = self.availability
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = {}
        data = raw or {}
        normalized = {}
        for k, v in data.items():
            sk = str(k)
            if isinstance(v, dict):
                nested = {}
                for pk, pv in v.items():
                    nested[str(pk)] = bool(pv)
                normalized[sk] = nested
            else:
                # If availability uses a flat true/false, ignore (not expected)
                normalized[sk] = v
        return normalized

    def is_available(self, day_index, period_index):
        """Check if teacher is available at given slot. Defaults to True when unavailable data missing."""
        avail = self.get_availability_dict()
        # try both string and int keys; default to True (available) if not specified
        day = avail.get(str(day_index), avail.get(day_index, {}))
        if not isinstance(day, dict):
            # if stored as something else, assume available
            return True
        return day.get(str(period_index), day.get(period_index, True))


class ClassGroup(models.Model):
    """
    A class/section that needs a timetable.
    """
    name = models.CharField(max_length=50, unique=True, help_text="e.g., Grade 10A")
    student_count = models.IntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    subjects = models.ManyToManyField(Subject, related_name='classes', blank=True)

    class Meta:
        ordering = ['name']
        verbose_name = "Class"
        verbose_name_plural = "Classes"

    def __str__(self):
        return self.name


class Room(models.Model):
    """
    Physical room with capacity and type.
    """
    ROOM_TYPE_CHOICES = Subject.ROOM_TYPE_CHOICES

    name = models.CharField(max_length=50, unique=True)
    room_type = models.CharField(max_length=30, choices=ROOM_TYPE_CHOICES, default='classroom')
    capacity = models.IntegerField(
        default=40,
        validators=[MinValueValidator(1), MaxValueValidator(200)]
    )
    availability = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON: {day_index: {period_index: true/false}}"
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.room_type})"

    def get_availability_dict(self):
        """Parse availability JSON safely and normalize keys to strings for consistent lookup."""
        raw = self.availability
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = {}
        data = raw or {}
        normalized = {}
        for k, v in data.items():
            sk = str(k)
            if isinstance(v, dict):
                nested = {}
                for pk, pv in v.items():
                    nested[str(pk)] = bool(pv)
                normalized[sk] = nested
            else:
                normalized[sk] = v
        return normalized

    def is_available(self, day_index, period_index):
        """Check if room is available at given slot. Defaults to True when unspecified."""
        avail = self.get_availability_dict()
        day = avail.get(str(day_index), avail.get(day_index, {}))
        if not isinstance(day, dict):
            return True
        return day.get(str(period_index), day.get(period_index, True))


class TimeSlot(models.Model):
    """
    A specific time slot in the weekly schedule.
    """
    DAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    day_index = models.IntegerField(choices=DAY_CHOICES)
    period_index = models.IntegerField(help_text="0-based period number within the day")
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ['day_index', 'period_index']
        unique_together = ['day_index', 'period_index']

    def __str__(self):
        return f"{self.get_day_index_display()} P{self.period_index + 1} ({self.start_time}-{self.end_time})"


class TeacherSubjectAllocation(models.Model):
    """
    Assignment of a teacher to teach a subject for a specific class.
    """
    classgroup = models.ForeignKey(ClassGroup, on_delete=models.CASCADE, related_name='allocations')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='allocations')

    class Meta:
        unique_together = ['classgroup', 'subject', 'teacher']
        verbose_name = "Teacher-Subject Allocation"
        verbose_name_plural = "Teacher-Subject Allocations"

    def __str__(self):
        return f"{self.teacher.name} → {self.subject.name} for {self.classgroup.name}"


class TimetableEntry(models.Model):
    """
    A scheduled lesson in the timetable.
    """
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='timetable_entries')
    classgroup = models.ForeignKey(ClassGroup, on_delete=models.CASCADE, related_name='timetable_entries')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='timetable_entries')
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='timetable_entries')
    timeslot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE, related_name='timetable_entries')
    is_locked = models.BooleanField(
        default=False,
        help_text="Locked entries won't be modified by the solver"
    )

    class Meta:
        verbose_name = "Timetable Entry"
        verbose_name_plural = "Timetable Entries"
        ordering = ['timeslot__day_index', 'timeslot__period_index']

    def __str__(self):
        return f"{self.classgroup.name} - {self.subject.name} @ {self.timeslot}"


class ConflictReport(models.Model):
    """
    Record of constraint violations detected by solver.
    """
    SEVERITY_CHOICES = [
        ('error', 'Error'),
        ('warning', 'Warning'),
        ('info', 'Info'),
    ]

    generated_at = models.DateTimeField(auto_now_add=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='error')
    message = models.TextField()
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-generated_at', 'severity']
        verbose_name = "Conflict Report"
        verbose_name_plural = "Conflict Reports"

    def __str__(self):
        return f"[{self.severity.upper()}] {self.message[:50]}"
