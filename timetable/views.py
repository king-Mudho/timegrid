"""
Views for Melsoft TimeGrid timetable application.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.db.models import Count, Q
from django.views.decorators.http import require_http_methods
from ortools.sat.python import cp_model
import csv
import json

from .models import (
    SchoolSettings, Subject, Teacher, ClassGroup, Room,
    TimeSlot, TimetableEntry, TeacherSubjectAllocation, ConflictReport
)
from .solver import TimetableSolver, generate_timeslots
from .export import export_to_pdf, export_to_excel, export_to_csv


def dashboard(request):
    """
    Main dashboard with statistics and quick actions.
    """
    context = {
        'total_teachers': Teacher.objects.count(),
        'total_classes': ClassGroup.objects.count(),
        'total_rooms': Room.objects.count(),
        'total_subjects': Subject.objects.count(),
        'total_timeslots': TimeSlot.objects.count(),
        'total_entries': TimetableEntry.objects.count(),
        'conflicts': ConflictReport.objects.filter(severity='error').count(),
        'settings': SchoolSettings.objects.first(),
        'recent_conflicts': ConflictReport.objects.all()[:5],
    }

    # Teacher workload data
    teacher_workload = []
    for teacher in Teacher.objects.all()[:10]:
        periods = TimetableEntry.objects.filter(teacher=teacher).count()
        teacher_workload.append({
            'name': teacher.name,
            'periods': periods,
            'max': teacher.max_periods_week
        })
    context['teacher_workload'] = teacher_workload

    # Room utilization
    room_utilization = []
    total_slots = TimeSlot.objects.count()
    for room in Room.objects.all()[:10]:
        used = TimetableEntry.objects.filter(room=room).count()
        utilization = (used / total_slots * 100) if total_slots > 0 else 0
        room_utilization.append({
            'name': room.name,
            'utilization': round(utilization, 1)
        })
    context['room_utilization'] = room_utilization

    return render(request, 'timetable/dashboard.html', context)


def allocate_teachers(request, class_id):
    """
    Allocation page: assign teachers to subjects for a specific class.
    """
    classgroup = get_object_or_404(ClassGroup, id=class_id)

    if request.method == 'POST':
        # Process form submission
        for subject in classgroup.subjects.all():
            teacher_id = request.POST.get(f'teacher_for_subject_{subject.id}')
            if teacher_id:
                teacher = Teacher.objects.get(id=teacher_id)
                TeacherSubjectAllocation.objects.update_or_create(
                    classgroup=classgroup,
                    subject=subject,
                    defaults={'teacher': teacher}
                )

        messages.success(request, f'Teacher allocations saved for {classgroup.name}')
        return redirect('dashboard')

    # Get existing allocations
    existing_allocations = {}
    for alloc in TeacherSubjectAllocation.objects.filter(classgroup=classgroup):
        existing_allocations[alloc.subject.id] = alloc.teacher.id

    # Get available teachers for each subject
    subject_teachers = {}
    for subject in classgroup.subjects.all():
        subject_teachers[subject.id] = Teacher.objects.filter(subjects=subject)

    context = {
        'classgroup': classgroup,
        'subjects': classgroup.subjects.all(),
        'subject_teachers': subject_teachers,
        'existing_allocations': existing_allocations,
    }

    return render(request, 'timetable/allocate_teachers.html', context)


def generate_timetable(request):
    """
    Run the OR-Tools solver to generate timetable.
    """
    if request.method == 'POST':
        try:
            # Check if timeslots exist
            if not TimeSlot.objects.exists():
                messages.info(request, 'Generating time slots first...')
                generate_timeslots()

            # Initialize and run solver
            solver = TimetableSolver()
            solver.load_data()
            solver.create_variables()
            solver.add_hard_constraints()
            solver.add_soft_constraints()

            time_limit = int(request.POST.get('time_limit', 60))
            status, solution = solver.solve(time_limit_seconds=time_limit)

            if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                solver.save_solution(solution)
                messages.success(request, f'Timetable generated successfully! ({len(solution)} entries)')
                return redirect('master_timetable')
            else:
                conflicts = solver.generate_conflict_report(status)
                messages.error(request, f'Could not generate timetable. Found {len(conflicts)} conflicts.')
                return redirect('conflict_report')

        except Exception as e:
            messages.error(request, f'Error generating timetable: {str(e)}')
            return redirect('dashboard')

    context = {
        'total_allocations': TeacherSubjectAllocation.objects.count(),
        'total_timeslots': TimeSlot.objects.count(),
    }
    return render(request, 'timetable/generate.html', context)


def master_timetable(request):
    """
    Display master timetable grid with all classes.
    """
    timeslots = TimeSlot.objects.all().order_by('day_index', 'period_index')
    classes = ClassGroup.objects.all()

    # Group timeslots by day
    days = {}
    for ts in timeslots:
        if ts.day_index not in days:
            days[ts.day_index] = []
        days[ts.day_index].append(ts)

    # Build grid data
    grid = {}
    for classgroup in classes:
        grid[classgroup.id] = {}
        for ts in timeslots:
            entry = TimetableEntry.objects.filter(
                classgroup=classgroup,
                timeslot=ts
            ).select_related('teacher', 'subject', 'room').first()
            grid[classgroup.id][ts.id] = entry

    context = {
        'days': days,
        'classes': classes,
        'grid': grid,
    }
    return render(request, 'timetable/master_timetable.html', context)


def teacher_timetable(request, teacher_id=None):
    """
    Display timetable for a specific teacher or list all teachers.
    """
    if teacher_id:
        teacher = get_object_or_404(Teacher, id=teacher_id)
        entries = TimetableEntry.objects.filter(teacher=teacher).select_related(
            'classgroup', 'subject', 'room', 'timeslot'
        ).order_by('timeslot__day_index', 'timeslot__period_index')

        timeslots = TimeSlot.objects.all().order_by('day_index', 'period_index')
        days = {}
        for ts in timeslots:
            if ts.day_index not in days:
                days[ts.day_index] = []
            days[ts.day_index].append(ts)

        grid = {}
        for ts in timeslots:
            entry = entries.filter(timeslot=ts).first()
            grid[ts.id] = entry

        context = {
            'teacher': teacher,
            'entries': entries,
            'days': days,
            'grid': grid,
            'total_periods': entries.count(),
        }
        return render(request, 'timetable/teacher_detail.html', context)
    else:
        teachers = Teacher.objects.annotate(
            period_count=Count('timetable_entries')
        ).all()
        context = {'teachers': teachers}
        return render(request, 'timetable/teacher_list.html', context)


def class_timetable(request, class_id=None):
    """
    Display timetable for a specific class or list all classes.
    """
    if class_id:
        classgroup = get_object_or_404(ClassGroup, id=class_id)
        entries = TimetableEntry.objects.filter(classgroup=classgroup).select_related(
            'teacher', 'subject', 'room', 'timeslot'
        ).order_by('timeslot__day_index', 'timeslot__period_index')

        timeslots = TimeSlot.objects.all().order_by('day_index', 'period_index')
        days = {}
        for ts in timeslots:
            if ts.day_index not in days:
                days[ts.day_index] = []
            days[ts.day_index].append(ts)

        grid = {}
        for ts in timeslots:
            entry = entries.filter(timeslot=ts).first()
            grid[ts.id] = entry

        context = {
            'classgroup': classgroup,
            'entries': entries,
            'days': days,
            'grid': grid,
        }
        return render(request, 'timetable/class_detail.html', context)
    else:
        classes = ClassGroup.objects.annotate(
            period_count=Count('timetable_entries')
        ).all()
        context = {'classes': classes}
        return render(request, 'timetable/class_list.html', context)


def room_timetable(request, room_id=None):
    """
    Display timetable for a specific room or list all rooms.
    """
    if room_id:
        room = get_object_or_404(Room, id=room_id)
        entries = TimetableEntry.objects.filter(room=room).select_related(
            'teacher', 'subject', 'classgroup', 'timeslot'
        ).order_by('timeslot__day_index', 'timeslot__period_index')

        timeslots = TimeSlot.objects.all().order_by('day_index', 'period_index')
        days = {}
        for ts in timeslots:
            if ts.day_index not in days:
                days[ts.day_index] = []
            days[ts.day_index].append(ts)

        grid = {}
        for ts in timeslots:
            entry = entries.filter(timeslot=ts).first()
            grid[ts.id] = entry

        total_slots = TimeSlot.objects.count()
        utilization = (entries.count() / total_slots * 100) if total_slots > 0 else 0

        context = {
            'room': room,
            'entries': entries,
            'days': days,
            'grid': grid,
            'utilization': round(utilization, 1),
        }
        return render(request, 'timetable/room_detail.html', context)
    else:
        rooms = Room.objects.annotate(
            period_count=Count('timetable_entries')
        ).all()
        context = {'rooms': rooms}
        return render(request, 'timetable/room_list.html', context)


def conflict_report(request):
    """
    Display conflict reports from solver.
    """
    conflicts = ConflictReport.objects.all().order_by('-generated_at', 'severity')
    context = {'conflicts': conflicts}
    return render(request, 'timetable/conflicts.html', context)


@require_http_methods(["POST"])
def update_entry(request):
    """
    AJAX endpoint to update a timetable entry (drag-and-drop).
    """
    try:
        data = json.loads(request.body)
        entry_id = data.get('entry_id')
        new_timeslot_id = data.get('timeslot_id')
        new_room_id = data.get('room_id')

        entry = TimetableEntry.objects.get(id=entry_id)
        new_timeslot = TimeSlot.objects.get(id=new_timeslot_id)
        new_room = Room.objects.get(id=new_room_id) if new_room_id else entry.room

        # Validate constraints
        errors = []

        # Check teacher availability
        if not entry.teacher.is_available(new_timeslot.day_index, new_timeslot.period_index):
            errors.append(f"Teacher {entry.teacher.name} is not available at this time")

        # Check room availability
        if not new_room.is_available(new_timeslot.day_index, new_timeslot.period_index):
            errors.append(f"Room {new_room.name} is not available at this time")

        # Check teacher double-booking
        if TimetableEntry.objects.filter(
            teacher=entry.teacher,
            timeslot=new_timeslot
        ).exclude(id=entry_id).exists():
            errors.append(f"Teacher {entry.teacher.name} is already scheduled at this time")

        # Check class double-booking
        if TimetableEntry.objects.filter(
            classgroup=entry.classgroup,
            timeslot=new_timeslot
        ).exclude(id=entry_id).exists():
            errors.append(f"Class {entry.classgroup.name} is already scheduled at this time")

        # Check room double-booking
        if TimetableEntry.objects.filter(
            room=new_room,
            timeslot=new_timeslot
        ).exclude(id=entry_id).exists():
            errors.append(f"Room {new_room.name} is already occupied at this time")

        # Check room capacity
        if new_room.capacity < entry.classgroup.student_count:
            errors.append(f"Room {new_room.name} is too small for class {entry.classgroup.name}")

        # Check room type
        if new_room.room_type != entry.subject.requires_room_type:
            errors.append(f"Room type mismatch: {entry.subject.name} requires {entry.subject.requires_room_type}")

        if errors:
            return JsonResponse({'success': False, 'errors': errors}, status=400)

        # Update entry
        entry.timeslot = new_timeslot
        entry.room = new_room
        entry.save()

        return JsonResponse({'success': True})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def export_view(request, format='pdf', view_type='master', object_id=None):
    """
    Export timetable in various formats.
    """
    if format == 'pdf':
        return export_to_pdf(view_type, object_id)
    elif format == 'excel':
        return export_to_excel(view_type, object_id)
    elif format == 'csv':
        return export_to_csv(view_type, object_id)
    else:
        return HttpResponse('Invalid format', status=400)








