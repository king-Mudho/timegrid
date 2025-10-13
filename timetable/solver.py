"""
Timetable constraint solver using Google OR-Tools CP-SAT.

This module implements a constraint programming approach to generate conflict-free
school timetables. It handles hard constraints (no double-booking, availability,
curriculum requirements) and soft preferences (balanced workload, minimal gaps).
"""

from ortools.sat.python import cp_model
from django.db import transaction
from datetime import datetime, timedelta

from .models import (
    SchoolSettings, Subject, Teacher, ClassGroup, Room,
    TimeSlot, TimetableEntry, TeacherSubjectAllocation, ConflictReport
)


class TimetableSolver:
    """
    OR-Tools CP-SAT based timetable generator.
    """

    def __init__(self):
        self.model = cp_model.CpModel()
        self.solver = cp_model.CpSolver()
        self.variables = {}
        self.timeslots = []
        self.classes = []
        self.teachers = []
        self.rooms = []
        self.subjects = []
        self.allocations = []

    def load_data(self):
        """Load all required data from database."""
        self.timeslots = list(TimeSlot.objects.all().order_by('day_index', 'period_index'))
        self.classes = list(ClassGroup.objects.all())
        self.teachers = list(Teacher.objects.all())
        self.rooms = list(Room.objects.all())
        self.subjects = list(Subject.objects.all())
        self.allocations = list(TeacherSubjectAllocation.objects.select_related(
            'teacher', 'classgroup', 'subject'
        ).all())

        if not self.timeslots:
            raise ValueError("No time slots defined. Please generate time slots first.")
        if not self.allocations:
            raise ValueError("No teacher-subject allocations defined. Please allocate teachers to classes.")

    def create_variables(self):
        """
        Create decision variables for the CP-SAT model.
        Variable: assignment[class, subject, teacher, room, timeslot] = 1 if scheduled, 0 otherwise
        """
        print("Creating decision variables...")
        for allocation in self.allocations:
            classgroup = allocation.classgroup
            subject = allocation.subject
            teacher = allocation.teacher

            # For each required period of this subject
            for period_num in range(subject.weekly_periods):
                for timeslot in self.timeslots:
                    for room in self.rooms:
                        # Only consider rooms of matching type
                        if room.room_type != subject.requires_room_type:
                            continue

                        # Create boolean variable
                        var_name = f"c{classgroup.id}_s{subject.id}_t{teacher.id}_r{room.id}_ts{timeslot.id}_p{period_num}"
                        var = self.model.NewBoolVar(var_name)
                        self.variables[(classgroup.id, subject.id, teacher.id, room.id, timeslot.id, period_num)] = var

    def add_hard_constraints(self):
        """
        Add hard constraints that must be satisfied.
        """
        print("Adding hard constraints...")

        # CONSTRAINT 1: Each required subject period must be scheduled exactly once
        for allocation in self.allocations:
            classgroup = allocation.classgroup
            subject = allocation.subject
            teacher = allocation.teacher

            for period_num in range(subject.weekly_periods):
                matching_vars = []
                for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items():
                    if c_id == classgroup.id and s_id == subject.id and t_id == teacher.id and p_num == period_num:
                        matching_vars.append(var)

                if matching_vars:
                    # Exactly one slot must be chosen for this period
                    self.model.Add(sum(matching_vars) == 1)

        # CONSTRAINT 2: No teacher double-booking
        # A teacher cannot teach two classes at the same time
        for teacher in self.teachers:
            for timeslot in self.timeslots:
                teacher_vars_at_slot = []
                for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items():
                    if t_id == teacher.id and ts_id == timeslot.id:
                        teacher_vars_at_slot.append(var)

                if teacher_vars_at_slot:
                    self.model.Add(sum(teacher_vars_at_slot) <= 1)

        # CONSTRAINT 3: No class double-booking
        # A class cannot be in two places at the same time
        for classgroup in self.classes:
            for timeslot in self.timeslots:
                class_vars_at_slot = []
                for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items():
                    if c_id == classgroup.id and ts_id == timeslot.id:
                        class_vars_at_slot.append(var)

                if class_vars_at_slot:
                    self.model.Add(sum(class_vars_at_slot) <= 1)

        # CONSTRAINT 4: No room double-booking
        # A room cannot host two classes at the same time
        for room in self.rooms:
            for timeslot in self.timeslots:
                room_vars_at_slot = []
                for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items():
                    if r_id == room.id and ts_id == timeslot.id:
                        room_vars_at_slot.append(var)

                if room_vars_at_slot:
                    self.model.Add(sum(room_vars_at_slot) <= 1)

        # CONSTRAINT 5: Teacher availability
        # Teachers can only be scheduled when available
        for teacher in self.teachers:
            for timeslot in self.timeslots:
                if not teacher.is_available(timeslot.day_index, timeslot.period_index):
                    # Force all variables for this teacher at this slot to 0
                    for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items():
                        if t_id == teacher.id and ts_id == timeslot.id:
                            self.model.Add(var == 0)

        # CONSTRAINT 6: Room availability
        for room in self.rooms:
            for timeslot in self.timeslots:
                if not room.is_available(timeslot.day_index, timeslot.period_index):
                    for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items():
                        if r_id == room.id and ts_id == timeslot.id:
                            self.model.Add(var == 0)

        # CONSTRAINT 7: Room capacity must accommodate class size
        for classgroup in self.classes:
            for room in self.rooms:
                if room.capacity < classgroup.student_count:
                    # This room is too small for this class
                    for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items():
                        if c_id == classgroup.id and r_id == room.id:
                            self.model.Add(var == 0)

        # CONSTRAINT 8: Consecutive double periods for subjects that require it
        for allocation in self.allocations:
            subject = allocation.subject
            if subject.requires_consecutive_periods and subject.weekly_periods >= 2:
                classgroup = allocation.classgroup
                teacher = allocation.teacher

                # Group timeslots by day
                slots_by_day = {}
                for ts in self.timeslots:
                    if ts.day_index not in slots_by_day:
                        slots_by_day[ts.day_index] = []
                    slots_by_day[ts.day_index].append(ts)

                # For each pair of consecutive periods, if one is scheduled, the next should be too
                for day_slots in slots_by_day.values():
                    for i in range(len(day_slots) - 1):
                        slot1 = day_slots[i]
                        slot2 = day_slots[i + 1]

                        # Check if these are actually consecutive (no breaks)
                        if slot2.period_index == slot1.period_index + 1:
                            # If we schedule at slot1, we should schedule at slot2
                            for p_num in range(subject.weekly_periods - 1):
                                vars_slot1 = [var for (c_id, s_id, t_id, r_id, ts_id, p_num_var), var in self.variables.items()
                                             if c_id == classgroup.id and s_id == subject.id and ts_id == slot1.id and p_num_var == p_num]
                                vars_slot2 = [var for (c_id, s_id, t_id, r_id, ts_id, p_num_var), var in self.variables.items()
                                             if c_id == classgroup.id and s_id == subject.id and ts_id == slot2.id and p_num_var == p_num + 1]

                                if vars_slot1 and vars_slot2:
                                    # If slot1 is used, slot2 must be used with same room
                                    for (c_id, s_id, t_id, r_id, ts_id, p_num_var), var1 in self.variables.items():
                                        if c_id == classgroup.id and s_id == subject.id and ts_id == slot1.id and p_num_var == p_num:
                                            for (c_id2, s_id2, t_id2, r_id2, ts_id2, p_num_var2), var2 in self.variables.items():
                                                if (c_id2 == classgroup.id and s_id2 == subject.id and
                                                    ts_id2 == slot2.id and p_num_var2 == p_num + 1 and r_id2 == r_id):
                                                    # var1 implies var2
                                                    self.model.Add(var2 >= var1)

    def add_soft_constraints(self):
        """
        Add soft preferences as optimization objectives.
        """
        print("Adding soft constraints...")

        # SOFT CONSTRAINT 1: Minimize teacher idle periods (gaps in schedule)
        gap_penalties = []
        for teacher in self.teachers:
            for day_idx in range(7):
                day_slots = [ts for ts in self.timeslots if ts.day_index == day_idx]
                for i in range(len(day_slots) - 2):
                    # Penalty if teacher has classes at slot i and i+2 but not i+1 (gap)
                    slot_before = day_slots[i]
                    slot_gap = day_slots[i + 1]
                    slot_after = day_slots[i + 2]

                    has_before = self.model.NewBoolVar(f"gap_before_t{teacher.id}_d{day_idx}_p{i}")
                    has_gap = self.model.NewBoolVar(f"gap_middle_t{teacher.id}_d{day_idx}_p{i}")
                    has_after = self.model.NewBoolVar(f"gap_after_t{teacher.id}_d{day_idx}_p{i}")

                    vars_before = [var for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items()
                                  if t_id == teacher.id and ts_id == slot_before.id]
                    vars_gap = [var for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items()
                               if t_id == teacher.id and ts_id == slot_gap.id]
                    vars_after = [var for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items()
                                 if t_id == teacher.id and ts_id == slot_after.id]

                    if vars_before:
                        self.model.Add(sum(vars_before) >= 1).OnlyEnforceIf(has_before)
                        self.model.Add(sum(vars_before) == 0).OnlyEnforceIf(has_before.Not())
                    else:
                        self.model.Add(has_before == 0)

                    if vars_gap:
                        self.model.Add(sum(vars_gap) == 0).OnlyEnforceIf(has_gap)
                        self.model.Add(sum(vars_gap) >= 1).OnlyEnforceIf(has_gap.Not())
                    else:
                        self.model.Add(has_gap == 1)

                    if vars_after:
                        self.model.Add(sum(vars_after) >= 1).OnlyEnforceIf(has_after)
                        self.model.Add(sum(vars_after) == 0).OnlyEnforceIf(has_after.Not())
                    else:
                        self.model.Add(has_after == 0)

                    # Gap exists if has_before AND has_gap AND has_after
                    gap_exists = self.model.NewBoolVar(f"gap_exists_t{teacher.id}_d{day_idx}_p{i}")
                    self.model.AddBoolAnd([has_before, has_gap, has_after]).OnlyEnforceIf(gap_exists)
                    gap_penalties.append(gap_exists)

        # SOFT CONSTRAINT 2: Schedule difficult subjects early in the day
        early_morning_bonus = []
        for allocation in self.allocations:
            subject = allocation.subject
            if subject.difficulty == 'difficult':
                classgroup = allocation.classgroup
                # Prefer first 2 periods of the day
                for timeslot in self.timeslots:
                    if timeslot.period_index <= 1:
                        for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items():
                            if c_id == classgroup.id and s_id == subject.id and ts_id == timeslot.id:
                                early_morning_bonus.append(var)

        # SOFT CONSTRAINT 3: Balance teacher workload across days
        workload_vars = []
        for teacher in self.teachers:
            daily_loads = []
            for day_idx in range(7):
                day_slots = [ts for ts in self.timeslots if ts.day_index == day_idx]
                day_vars = []
                for ts in day_slots:
                    for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items():
                        if t_id == teacher.id and ts_id == ts.id:
                            day_vars.append(var)

                if day_vars:
                    daily_load = self.model.NewIntVar(0, len(day_slots), f"daily_load_t{teacher.id}_d{day_idx}")
                    self.model.Add(daily_load == sum(day_vars))
                    daily_loads.append(daily_load)

            # Minimize variance in daily loads (simplified: minimize max daily load)
            if daily_loads:
                max_daily = self.model.NewIntVar(0, 100, f"max_daily_t{teacher.id}")
                self.model.AddMaxEquality(max_daily, daily_loads)
                workload_vars.append(max_daily)

        # Combine all soft constraints into objective
        # Minimize: gap penalties - early morning bonus + workload variance
        objective_terms = []

        if gap_penalties:
            objective_terms.extend([(penalty, 10) for penalty in gap_penalties])  # Weight: 10

        if early_morning_bonus:
            objective_terms.extend([(bonus, -5) for bonus in early_morning_bonus])  # Weight: -5 (maximize)

        if workload_vars:
            objective_terms.extend([(wl, 2) for wl in workload_vars])  # Weight: 2

        if objective_terms:
            self.model.Minimize(sum(coef * var for var, coef in objective_terms))

    def solve(self, time_limit_seconds=60):
        """
        Run the CP-SAT solver with given time limit.
        Returns: (status, solution_dict or None)
        """
        print(f"Starting solver with {time_limit_seconds}s time limit...")

        self.solver.parameters.max_time_in_seconds = time_limit_seconds
        self.solver.parameters.log_search_progress = True

        status = self.solver.Solve(self.model)

        status_names = {
            cp_model.OPTIMAL: 'OPTIMAL',
            cp_model.FEASIBLE: 'FEASIBLE',
            cp_model.INFEASIBLE: 'INFEASIBLE',
            cp_model.MODEL_INVALID: 'MODEL_INVALID',
            cp_model.UNKNOWN: 'UNKNOWN'
        }

        print(f"Solver status: {status_names.get(status, 'UNKNOWN')}")

        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            return status, self.extract_solution()
        else:
            return status, None

    def extract_solution(self):
        """
        Extract the solution from solver and return as list of assignments.
        """
        solution = []
        for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items():
            if self.solver.Value(var) == 1:
                solution.append({
                    'classgroup_id': c_id,
                    'subject_id': s_id,
                    'teacher_id': t_id,
                    'room_id': r_id,
                    'timeslot_id': ts_id,
                    'period_num': p_num
                })
        return solution

    def save_solution(self, solution):
        """
        Save the solution to database as TimetableEntry records.
        """
        print(f"Saving {len(solution)} timetable entries...")

        with transaction.atomic():
            # Clear existing non-locked entries
            TimetableEntry.objects.filter(is_locked=False).delete()

            # Create new entries
            entries = []
            for entry in solution:
                entries.append(TimetableEntry(
                    classgroup_id=entry['classgroup_id'],
                    subject_id=entry['subject_id'],
                    teacher_id=entry['teacher_id'],
                    room_id=entry['room_id'],
                    timeslot_id=entry['timeslot_id'],
                    is_locked=False
                ))

            TimetableEntry.objects.bulk_create(entries)
            print("Solution saved successfully!")

    def generate_conflict_report(self, status):
        """
        Generate a conflict report when solver fails.
        """
        ConflictReport.objects.all().delete()  # Clear old reports

        if status == cp_model.INFEASIBLE:
            # Analyze why infeasible
            conflicts = []

            # Check if enough rooms of each type
            for subject in self.subjects:
                required_rooms = Room.objects.filter(room_type=subject.requires_room_type).count()
                if required_rooms == 0:
                    conflicts.append(ConflictReport(
                        severity='error',
                        message=f"No rooms available for {subject.name}",
                        details={'subject': subject.name, 'required_type': subject.requires_room_type}
                    ))

            # Check teacher allocations
            for allocation in self.allocations:
                teacher = allocation.teacher
                if teacher not in allocation.subject.teachers.all():
                    conflicts.append(ConflictReport(
                        severity='error',
                        message=f"Teacher {teacher.name} not qualified for {allocation.subject.name}",
                        details={'teacher': teacher.name, 'subject': allocation.subject.name}
                    ))

            # Check teacher availability vs workload
            for teacher in self.teachers:
                available_slots = sum(
                    1 for ts in self.timeslots
                    if teacher.is_available(ts.day_index, ts.period_index)
                )
                required_periods = sum(
                    alloc.subject.weekly_periods
                    for alloc in self.allocations if alloc.teacher == teacher
                )
                if required_periods > available_slots:
                    conflicts.append(ConflictReport(
                        severity='error',
                        message=f"Teacher {teacher.name} overallocated",
                        details={
                            'teacher': teacher.name,
                            'required': required_periods,
                            'available': available_slots
                        }
                    ))

            if not conflicts:
                conflicts.append(ConflictReport(
                    severity='error',
                    message="Timetable is infeasible due to constraint conflicts",
                    details={'status': 'INFEASIBLE'}
                ))

            ConflictReport.objects.bulk_create(conflicts)
            return conflicts

        return []


def generate_timeslots():
    """
    Generate time slots based on school settings.
    """
    settings = SchoolSettings.objects.first()
    if not settings:
        raise ValueError("School settings not configured")

    TimeSlot.objects.all().delete()

    timeslots = []
    for day_idx in range(settings.days_per_week):
        current_time = datetime.combine(datetime.today(), settings.lesson_start_time)

        period_idx = 0

        # Periods before break
        for _ in range(settings.periods_before_break):
            end_time = (datetime.combine(datetime.today(), current_time.time()) +
                       timedelta(minutes=settings.lesson_duration_min)).time()
            timeslots.append(TimeSlot(
                day_index=day_idx,
                period_index=period_idx,
                start_time=current_time.time(),
                end_time=end_time
            ))
            period_idx += 1
            current_time = datetime.combine(datetime.today(), end_time) + timedelta(minutes=0)

        # Short break
        current_time += timedelta(minutes=settings.break_duration_min)

        # Periods after break
        for _ in range(settings.periods_after_break):
            end_time = (datetime.combine(datetime.today(), current_time.time()) +
                       timedelta(minutes=settings.lesson_duration_min)).time()
            timeslots.append(TimeSlot(
                day_index=day_idx,
                period_index=period_idx,
                start_time=current_time.time(),
                end_time=end_time
            ))
            period_idx += 1
            current_time = datetime.combine(datetime.today(), end_time) + timedelta(minutes=0)

        # Lunch break
        current_time += timedelta(minutes=settings.lunch_duration_min)

        # Additional periods can be added here if needed

    TimeSlot.objects.bulk_create(timeslots)
    print(f"Generated {len(timeslots)} time slots")
    return timeslots
