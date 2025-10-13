"""
Django admin interface for Melsoft TimeGrid with CSV import.
"""
from django.contrib import admin
from django.shortcuts import render, redirect
from django.urls import path
from django.contrib import messages
from django.http import HttpResponse
import csv
import io

from .models import (
    SchoolSettings, Subject, Teacher, ClassGroup, Room,
    TimeSlot, TimetableEntry, TeacherSubjectAllocation, ConflictReport
)


@admin.register(SchoolSettings)
class SchoolSettingsAdmin(admin.ModelAdmin):
    list_display = ['school_name', 'academic_year', 'days_per_week', 'lesson_start_time']
    fieldsets = (
        ('Basic Information', {
            'fields': ('school_name', 'academic_year', 'days_per_week')
        }),
        ('Timing Configuration', {
            'fields': ('lesson_start_time', 'lesson_duration_min')
        }),
        ('Break Schedule', {
            'fields': ('periods_before_break', 'break_duration_min', 'periods_after_break', 'lunch_duration_min')
        }),
    )

    def has_add_permission(self, request):
        # Only allow one settings instance
        return not SchoolSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'weekly_periods', 'subject_type', 'difficulty', 'requires_room_type', 'requires_consecutive_periods']
    list_filter = ['subject_type', 'difficulty', 'requires_room_type']
    search_fields = ['name']

    change_list_template = 'admin/subject_changelist.html'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('import-csv/', self.import_csv, name='subject_import_csv'),
        ]
        return custom_urls + urls

    def import_csv(self, request):
        if request.method == 'POST':
            csv_file = request.FILES.get('csv_file')
            if not csv_file:
                messages.error(request, 'No file uploaded')
                return redirect('..')

            try:
                decoded_file = csv_file.read().decode('utf-8')
                io_string = io.StringIO(decoded_file)
                reader = csv.DictReader(io_string)

                count = 0
                for row in reader:
                    Subject.objects.update_or_create(
                        name=row['name'],
                        defaults={
                            'weekly_periods': int(row.get('weekly_periods', 3)),
                            'subject_type': row.get('subject_type', 'theory'),
                            'difficulty': row.get('difficulty', 'fair'),
                            'requires_room_type': row.get('requires_room_type', 'classroom'),
                            'requires_consecutive_periods': row.get('requires_consecutive_periods', 'False').lower() == 'true',
                        }
                    )
                    count += 1

                messages.success(request, f'Successfully imported {count} subjects')
            except Exception as e:
                messages.error(request, f'Error importing CSV: {str(e)}')

            return redirect('..')

        return render(request, 'admin/csv_import_form.html', {
            'title': 'Import Subjects from CSV',
            'fields': 'name,weekly_periods,subject_type,difficulty,requires_room_type,requires_consecutive_periods'
        })


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'max_periods_week', 'get_subjects']
    list_filter = ['subjects']
    search_fields = ['name', 'email']
    filter_horizontal = ['subjects']

    change_list_template = 'admin/teacher_changelist.html'

    def get_subjects(self, obj):
        return ", ".join([s.name for s in obj.subjects.all()[:3]])
    get_subjects.short_description = 'Subjects'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('import-csv/', self.import_csv, name='teacher_import_csv'),
        ]
        return custom_urls + urls

    def import_csv(self, request):
        if request.method == 'POST':
            csv_file = request.FILES.get('csv_file')
            if not csv_file:
                messages.error(request, 'No file uploaded')
                return redirect('..')

            try:
                decoded_file = csv_file.read().decode('utf-8')
                io_string = io.StringIO(decoded_file)
                reader = csv.DictReader(io_string)

                count = 0
                for row in reader:
                    teacher, created = Teacher.objects.update_or_create(
                        email=row['email'],
                        defaults={
                            'name': row['name'],
                            'max_periods_week': int(row.get('max_periods_week', 25)),
                        }
                    )

                    # Handle subjects
                    if 'subjects' in row and row['subjects']:
                        subject_names = [s.strip() for s in row['subjects'].split(',')]
                        subjects = Subject.objects.filter(name__in=subject_names)
                        teacher.subjects.set(subjects)

                    count += 1

                messages.success(request, f'Successfully imported {count} teachers')
            except Exception as e:
                messages.error(request, f'Error importing CSV: {str(e)}')

            return redirect('..')

        return render(request, 'admin/csv_import_form.html', {
            'title': 'Import Teachers from CSV',
            'fields': 'name,email,max_periods_week,subjects (comma-separated)'
        })


@admin.register(ClassGroup)
class ClassGroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'student_count', 'get_subjects']
    search_fields = ['name']
    filter_horizontal = ['subjects']

    change_list_template = 'admin/class_changelist.html'

    def get_subjects(self, obj):
        return ", ".join([s.name for s in obj.subjects.all()[:3]])
    get_subjects.short_description = 'Subjects'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('import-csv/', self.import_csv, name='class_import_csv'),
        ]
        return custom_urls + urls

    def import_csv(self, request):
        if request.method == 'POST':
            csv_file = request.FILES.get('csv_file')
            if not csv_file:
                messages.error(request, 'No file uploaded')
                return redirect('..')

            try:
                decoded_file = csv_file.read().decode('utf-8')
                io_string = io.StringIO(decoded_file)
                reader = csv.DictReader(io_string)

                count = 0
                for row in reader:
                    classgroup, created = ClassGroup.objects.update_or_create(
                        name=row['name'],
                        defaults={
                            'student_count': int(row.get('student_count', 30)),
                        }
                    )

                    # Handle subjects
                    if 'subjects' in row and row['subjects']:
                        subject_names = [s.strip() for s in row['subjects'].split(',')]
                        subjects = Subject.objects.filter(name__in=subject_names)
                        classgroup.subjects.set(subjects)

                    count += 1

                messages.success(request, f'Successfully imported {count} classes')
            except Exception as e:
                messages.error(request, f'Error importing CSV: {str(e)}')

            return redirect('..')

        return render(request, 'admin/csv_import_form.html', {
            'title': 'Import Classes from CSV',
            'fields': 'name,student_count,subjects (comma-separated)'
        })

    def response_add(self, request, obj, post_url_override=None):
        """Redirect to allocation page after creating a class."""
        if '_addanother' not in request.POST and '_continue' not in request.POST:
            return redirect('allocate_teachers', class_id=obj.id)
        return super().response_add(request, obj, post_url_override)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ['name', 'room_type', 'capacity']
    list_filter = ['room_type']
    search_fields = ['name']

    change_list_template = 'admin/room_changelist.html'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('import-csv/', self.import_csv, name='room_import_csv'),
        ]
        return custom_urls + urls

    def import_csv(self, request):
        if request.method == 'POST':
            csv_file = request.FILES.get('csv_file')
            if not csv_file:
                messages.error(request, 'No file uploaded')
                return redirect('..')

            try:
                decoded_file = csv_file.read().decode('utf-8')
                io_string = io.StringIO(decoded_file)
                reader = csv.DictReader(io_string)

                count = 0
                for row in reader:
                    Room.objects.update_or_create(
                        name=row['name'],
                        defaults={
                            'room_type': row.get('room_type', 'classroom'),
                            'capacity': int(row.get('capacity', 40)),
                        }
                    )
                    count += 1

                messages.success(request, f'Successfully imported {count} rooms')
            except Exception as e:
                messages.error(request, f'Error importing CSV: {str(e)}')

            return redirect('..')

        return render(request, 'admin/csv_import_form.html', {
            'title': 'Import Rooms from CSV',
            'fields': 'name,room_type,capacity'
        })


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ['day_index', 'period_index', 'start_time', 'end_time']
    list_filter = ['day_index']
    ordering = ['day_index', 'period_index']


@admin.register(TeacherSubjectAllocation)
class TeacherSubjectAllocationAdmin(admin.ModelAdmin):
    list_display = ['classgroup', 'subject', 'teacher']
    list_filter = ['classgroup', 'subject']
    search_fields = ['teacher__name', 'classgroup__name', 'subject__name']
    autocomplete_fields = ['teacher', 'classgroup', 'subject']


@admin.register(TimetableEntry)
class TimetableEntryAdmin(admin.ModelAdmin):
    list_display = ['classgroup', 'subject', 'teacher', 'room', 'timeslot', 'is_locked']
    list_filter = ['classgroup', 'timeslot__day_index', 'is_locked']
    search_fields = ['teacher__name', 'classgroup__name', 'subject__name']
    list_editable = ['is_locked']


@admin.register(ConflictReport)
class ConflictReportAdmin(admin.ModelAdmin):
    list_display = ['generated_at', 'severity', 'message']
    list_filter = ['severity', 'generated_at']
    readonly_fields = ['generated_at', 'severity', 'message', 'details']

    def has_add_permission(self, request):
        return False
