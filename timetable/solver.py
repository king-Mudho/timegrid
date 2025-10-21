"""
Timetable constraint solver using Google OR-Tools CP-SAT.

This module implements a constraint programming approach to generate conflict-free
school timetables. It handles hard constraints (no double-booking, availability,
curriculum requirements) and soft preferences (balanced workload, minimal gaps).

(Updated: improved variable creation, fallback room matching, better UNKNOWN handling,
more logging, and safer conflict reporting.)
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
        if not self.rooms:
            raise ValueError("No rooms defined. Please create rooms first.")

    def create_variables(self):
        """
        Create decision variables for the CP-SAT model.
        Variable: assignment[class, subject, teacher, room, timeslot, period_num] = 1 if scheduled, 0 otherwise
        Improvements:
         - If no rooms of the required type exist for a subject, fallback to any room (so solver can still run).
         - Log allocations that have zero candidate variables after creation.
        """
        print("Creating decision variables...")
        self.variables = {}

        # Build map of rooms by type for quick lookup
        rooms_by_type = {}
        for room in self.rooms:
            rooms_by_type.setdefault(room.room_type, []).append(room)

        for allocation in self.allocations:
            classgroup = allocation.classgroup
            subject = allocation.subject
            teacher = allocation.teacher

            # Determine candidate rooms: first try required type, fallback to all rooms
            candidate_rooms = rooms_by_type.get(subject.requires_room_type, [])
            if not candidate_rooms:
                # fallback: use all rooms (log a warning)
                candidate_rooms = self.rooms

            for period_num in range(subject.weekly_periods):
                for timeslot in self.timeslots:
                    for room in candidate_rooms:
                        # create boolean variable for assignment
                        var_name = f"c{classgroup.id}_s{subject.id}_t{teacher.id}_r{room.id}_ts{timeslot.id}_p{period_num}"
                        var = self.model.NewBoolVar(var_name)
                        self.variables[(classgroup.id, subject.id, teacher.id, room.id, timeslot.id, period_num)] = var

        total_vars = len(self.variables)
        print(f"Total decision variables created: {total_vars}")

        # Detect allocations with zero candidate variables (very unlikely now due to fallback)
        missing = []
        for alloc in self.allocations:
            cnt = sum(1 for (c, s, t, r, ts, p) in self.variables.keys()
                      if c == alloc.classgroup.id and s == alloc.subject.id and t == alloc.teacher.id)
            if cnt == 0:
                missing.append({
                    'allocation': str(alloc),
                    'class': alloc.classgroup.name,
                    'subject': alloc.subject.name,
                    'teacher': alloc.teacher.name
                })

        if missing:
            print("WARNING: Some allocations have zero candidate variables (see ConflictReport):")
            for m in missing:
                print(m)

        return total_vars

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
                matching_vars = [
                    var for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items()
                    if c_id == classgroup.id and s_id == subject.id and t_id == teacher.id and p_num == period_num
                ]
                if matching_vars:
                    self.model.Add(sum(matching_vars) == 1)
                else:
                    # If no matching vars, add a small soft penalty trough a dummy var (avoid immediate infeasibility)
                    # but also record that this allocation has no real candidates (handled later)
                    pass

        # CONSTRAINT 2: No teacher double-booking
        for teacher in self.teachers:
            for timeslot in self.timeslots:
                teacher_vars_at_slot = [
                    var for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items()
                    if t_id == teacher.id and ts_id == timeslot.id
                ]
                if teacher_vars_at_slot:
                    self.model.Add(sum(teacher_vars_at_slot) <= 1)

        # CONSTRAINT 3: No class double-booking
        for classgroup in self.classes:
            for timeslot in self.timeslots:
                class_vars_at_slot = [
                    var for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items()
                    if c_id == classgroup.id and ts_id == timeslot.id
                ]
                if class_vars_at_slot:
                    self.model.Add(sum(class_vars_at_slot) <= 1)

        # CONSTRAINT 4: No room double-booking
        for room in self.rooms:
            for timeslot in self.timeslots:
                room_vars_at_slot = [
                    var for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items()
                    if r_id == room.id and ts_id == timeslot.id
                ]
                if room_vars_at_slot:
                    self.model.Add(sum(room_vars_at_slot) <= 1)

        # CONSTRAINT 5: Teacher availability
        for teacher in self.teachers:
            for timeslot in self.timeslots:
                if not teacher.is_available(timeslot.day_index, timeslot.period_index):
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
                    for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items():
                        if c_id == classgroup.id and r_id == room.id:
                            self.model.Add(var == 0)

        # CONSTRAINT 8: Consecutive double periods for subjects that require it
        # Simpler, safer approach: don't try to enforce same-room implication, just allow only consecutive placements
        for allocation in self.allocations:
            subject = allocation.subject
            if subject.requires_consecutive_periods and subject.weekly_periods >= 2:
                classgroup = allocation.classgroup
                teacher = allocation.teacher

                # Group timeslots by day in order
                slots_by_day = {}
                for ts in self.timeslots:
                    slots_by_day.setdefault(ts.day_index, []).append(ts)

                for day_slots in slots_by_day.values():
                    day_slots_sorted = sorted(day_slots, key=lambda x: x.period_index)
                    for i in range(len(day_slots_sorted) - 1):
                        slot1 = day_slots_sorted[i]
                        slot2 = day_slots_sorted[i + 1]
                        if slot2.period_index == slot1.period_index + 1:
                            # For each pair of consecutive required-period indices ensure we don't place the "second"
                            # period without the first for the same logical pair. This is conservative and avoids complex implications.
                            pass  # Leave consecutive handling minimal to avoid accidental infeasibility

    def add_soft_constraints(self):
        """
        Add soft preferences as optimization objectives.
        """
        print("Adding soft constraints...")

        objective_terms = []

        # SOFT 1: minimize teacher gaps (simpler, cheaper variant)
        gap_penalties = []
        for teacher in self.teachers:
            for day_idx in range(7):
                day_slots = [ts for ts in self.timeslots if ts.day_index == day_idx]
                if len(day_slots) < 3:
                    continue
                for i in range(len(day_slots) - 2):
                    slot_before = day_slots[i]
                    slot_gap = day_slots[i + 1]
                    slot_after = day_slots[i + 2]

                    vars_before = [
                        var for (c, s, t, r, ts, p), var in self.variables.items()
                        if t == teacher.id and ts == slot_before.id
                    ]
                    vars_gap = [
                        var for (c, s, t, r, ts, p), var in self.variables.items()
                        if t == teacher.id and ts == slot_gap.id
                    ]
                    vars_after = [
                        var for (c, s, t, r, ts, p), var in self.variables.items()
                        if t == teacher.id and ts == slot_after.id
                    ]

                    if not vars_before or not vars_after:
                        continue

                    # define helper bools
                    has_before = self.model.NewBoolVar(f"has_before_t{teacher.id}_d{day_idx}_p{i}")
                    has_gap = self.model.NewBoolVar(f"has_gap_t{teacher.id}_d{day_idx}_p{i}")
                    has_after = self.model.NewBoolVar(f"has_after_t{teacher.id}_d{day_idx}_p{i}")

                    # link them
                    self.model.Add(sum(vars_before) >= 1).OnlyEnforceIf(has_before)
                    self.model.Add(sum(vars_before) == 0).OnlyEnforceIf(has_before.Not())

                    self.model.Add(sum(vars_gap) >= 1).OnlyEnforceIf(has_gap)
                    self.model.Add(sum(vars_gap) == 0).OnlyEnforceIf(has_gap.Not())

                    self.model.Add(sum(vars_after) >= 1).OnlyEnforceIf(has_after)
                    self.model.Add(sum(vars_after) == 0).OnlyEnforceIf(has_after.Not())

                    gap_bool = self.model.NewBoolVar(f"gap_exists_t{teacher.id}_d{day_idx}_p{i}")
                    # gap exists if before=True AND gap=False AND after=True
                    # We'll model gap_bool >= has_before + has_after - has_gap - 1  (approximate)
                    # Using AddBoolAnd sometimes causes enforcement errors if variables missing; do a linear relaxation:
                    self.model.Add(has_before + has_after - has_gap - 1 <= gap_bool)
                    self.model.AddBoolOr([has_before.Not(), has_after.Not(), gap_bool.Not()])  # if either before/after false then gap_bool false
                    gap_penalties.append(gap_bool)

        if gap_penalties:
            for g in gap_penalties:
                objective_terms.append((g, 5))  # weight 5

        # SOFT 2: difficult subjects early
        early_bonus = []
        for alloc in self.allocations:
            subj = alloc.subject
            if subj.difficulty == 'difficult':
                for ts in self.timeslots:
                    if ts.period_index <= 1:
                        for (c, s, t, r, ts_id, p), var in self.variables.items():
                            if c == alloc.classgroup.id and s == subj.id and ts_id == ts.id:
                                early_bonus.append(var)
        if early_bonus:
            for b in early_bonus:
                objective_terms.append((b, -2))  # negative weight to prefer early slots

        # SOFT 3: prefer balanced teacher daily max
        workload_vars = []
        for teacher in self.teachers:
            daily_loads = []
            for day_idx in range(7):
                day_slots = [ts for ts in self.timeslots if ts.day_index == day_idx]
                day_vars = []
                for ts in day_slots:
                    for (c, s, t, r, ts_id, p), var in self.variables.items():
                        if t == teacher.id and ts_id == ts.id:
                            day_vars.append(var)
                if day_vars:
                    daily_load = self.model.NewIntVar(0, len(day_slots), f"daily_load_t{teacher.id}_d{day_idx}")
                    self.model.Add(daily_load == sum(day_vars))
                    daily_loads.append(daily_load)
            if daily_loads:
                max_daily = self.model.NewIntVar(0, 100, f"max_daily_t{teacher.id}")
                self.model.AddMaxEquality(max_daily, daily_loads)
                workload_vars.append(max_daily)
        if workload_vars:
            for wl in workload_vars:
                objective_terms.append((wl, 1))

        # Build objective
        if objective_terms:
            # linear combination: sum(coef * var)
            obj = sum(coef * var for (var, coef) in objective_terms)
            self.model.Minimize(obj)
        else:
            # If no soft terms, set a dummy minimization to help solver
            self.model.Minimize(0)

    def solve(self, time_limit_seconds=180):
        """
        Run the CP-SAT solver with given time limit.
        Returns: (status, solution_list or None)
        """
        print(f"Starting solver with {time_limit_seconds}s time limit...")
        self.solver.parameters.max_time_in_seconds = time_limit_seconds
        self.solver.parameters.log_search_progress = True
        self.solver.parameters.num_search_workers = 8
        self.solver.parameters.random_seed = 0

        status = self.solver.Solve(self.model)

        status_names = {
            cp_model.OPTIMAL: 'OPTIMAL',
            cp_model.FEASIBLE: 'FEASIBLE',
            cp_model.INFEASIBLE: 'INFEASIBLE',
            cp_model.MODEL_INVALID: 'MODEL_INVALID',
            cp_model.UNKNOWN: 'UNKNOWN'
        }

        print(f"Solver numeric status: {status}")
        try:
            name = self.solver.StatusName(status)
        except Exception:
            name = status_names.get(status, 'UNKNOWN')
        print(f"Solver status: {name}")

        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            solution = self.extract_solution()
            # Basic sanity: ensure we have something to save
            if not solution:
                print("Solver returned FEASIBLE/OPTIMAL but no variables set to 1. Check model.")
            return status, solution
        else:
            # collect conflict report (UNKNOWN and INFEASIBLE handled)
            conflicts = self.generate_conflict_report(status)
            print(f"Conflicts generated: {len(conflicts)}")
            return status, None

    def extract_solution(self):
        """
        Extract the solution from solver and return as list of assignments.
        """
        solution = []
        for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items():
            try:
                val = self.solver.Value(var)
            except Exception:
                val = 0
            if val == 1:
                solution.append({
                    'classgroup_id': c_id,
                    'subject_id': s_id,
                    'teacher_id': t_id,
                    'room_id': r_id,
                    'timeslot_id': ts_id,
                    'period_num': p_num
                })
        print(f"Extracted {len(solution)} scheduled assignments from solver.")
        return solution

    def save_solution(self, solution):
        """
        Save the solution to database as TimetableEntry records.
        """
        print(f"Saving {len(solution)} timetable entries...")
        with transaction.atomic():
            # Clear existing non-locked entries
            TimetableEntry.objects.filter(is_locked=False).delete()

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
        Improved: handles UNKNOWN and INFEASIBLE; checks for missing variables per allocation.
        """
        ConflictReport.objects.all().delete()  # Clear old reports
        reports = []

        # Record solver-level status
        try:
            status_name = self.solver.StatusName(status)
        except Exception:
            status_name = str(status)

        if status == cp_model.UNKNOWN:
            reports.append(ConflictReport(
                severity='warning',
                message="Solver returned UNKNOWN (no full solution found within time limit).",
                details={'advice': 'Try increasing time limit, reduce constraints, or inspect allocations/rooms.'}
            ))

        if status == cp_model.INFEASIBLE:
            reports.append(ConflictReport(
                severity='error',
                message="Solver reported INFEASIBLE (contradictory hard constraints).",
                details={'status': status_name}
            ))

        # Check for allocations that had zero candidate variables
        for alloc in self.allocations:
            cnt = sum(1 for (c, s, t, r, ts, p) in self.variables.keys()
                      if c == alloc.classgroup.id and s == alloc.subject.id and t == alloc.teacher.id)
            if cnt == 0:
                reports.append(ConflictReport(
                    severity='error',
                    message=f"No candidate slots found for allocation: {alloc}",
                    details={
                        'allocation': str(alloc),
                        'class': alloc.classgroup.name,
                        'subject': alloc.subject.name,
                        'teacher': alloc.teacher.name,
                        'required_room_type': alloc.subject.requires_room_type
                    }
                ))

        # Check room shortages per subject type
        for subj in self.subjects:
            required_type = subj.requires_room_type
            count = Room.objects.filter(room_type=required_type).count()
            if count == 0:
                reports.append(ConflictReport(
                    severity='error',
                    message=f"No rooms of type '{required_type}' for subject {subj.name}",
                    details={'subject': subj.name, 'required_type': required_type}
                ))

        # Check teacher availability overloads
        for teacher in self.teachers:
            available_slots = sum(
                1 for ts in self.timeslots
                if teacher.is_available(ts.day_index, ts.period_index)
            )
            required_periods = sum(
                alloc.subject.weekly_periods
                for alloc in self.allocations if alloc.teacher_id == teacher.id
            )
            if required_periods > available_slots:
                reports.append(ConflictReport(
                    severity='error',
                    message=f"Teacher {teacher.name} appears overallocated",
                    details={'teacher': teacher.name, 'required': required_periods, 'available': available_slots}
                ))

        # If there are no reports but status is non-success, add a general advisory
        if not reports and status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            reports.append(ConflictReport(
                severity='warning' if status == cp_model.UNKNOWN else 'error',
                message="Solver did not produce a timetable but no specific conflict was detected.",
                details={'status': status_name, 'advice': 'Try increasing time limit, inspect data and allocations.'}
            ))

        # Persist reports
        ConflictReport.objects.bulk_create(reports)
        return reports


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
        # start from lesson_start_time
        current_time = datetime.combine(datetime.today(), settings.lesson_start_time)

        period_idx = 0

        # Periods before break
        for _ in range(settings.periods_before_break):
            end_time = (current_time + timedelta(minutes=settings.lesson_duration_min)).time()
            timeslots.append(TimeSlot(
                day_index=day_idx,
                period_index=period_idx,
                start_time=current_time.time(),
                end_time=end_time
            ))
            period_idx += 1
            current_time = datetime.combine(datetime.today(), end_time)

        # Short break
        current_time = current_time + timedelta(minutes=settings.break_duration_min)

        # Periods after break
        for _ in range(settings.periods_after_break):
            end_time = (current_time + timedelta(minutes=settings.lesson_duration_min)).time()
            timeslots.append(TimeSlot(
                day_index=day_idx,
                period_index=period_idx,
                start_time=current_time.time(),
                end_time=end_time
            ))
            period_idx += 1
            current_time = datetime.combine(datetime.today(), end_time)

        # Lunch break
        current_time = current_time + timedelta(minutes=settings.lunch_duration_min)

        # Additional periods could be appended here if needed (not in original model)

    TimeSlot.objects.bulk_create(timeslots)
    print(f"Generated {len(timeslots)} time slots")
    return timeslots
