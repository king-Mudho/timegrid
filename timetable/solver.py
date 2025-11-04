"""
Timetable constraint solver using Google OR-Tools CP-SAT.

Supports:
 - Hard constraints:
    * No teacher/class/room double-booking
    * Teacher & room availability
    * Curriculum hours satisfied
    * Consecutive periods for subjects that require them (same day, consecutive timeslots, same room)
    * Room type & capacity matching
 - Soft constraints:
    * Minimize teacher idle gaps
    * Schedule difficult subjects early
    * Balanced teacher daily workload
    * Strong preference to schedule required allocation periods (helps feasibility search)
"""
from ortools.sat.python import cp_model
from django.db import transaction
from datetime import datetime, timedelta

from .models import (
    SchoolSettings, Subject, Teacher, ClassGroup, Room,
    TimeSlot, TimetableEntry, TeacherSubjectAllocation, ConflictReport
)


class TimetableSolver:
    def __init__(self):
        self.model = cp_model.CpModel()
        self.solver = cp_model.CpSolver()
        # key: (class_id, subject_id, teacher_id, room_id, timeslot_id, period_num) -> BoolVar
        self.variables = {}
        self.timeslots = []
        self.classes = []
        self.teachers = []
        self.rooms = []
        self.subjects = []
        self.allocations = []
        self._vars_list = []

    def load_data(self):
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
        Create boolean vars only for feasible assignment combinations:
         - teacher available
         - room available
         - room capacity adequate
         - subject required room type considered (fallback to all rooms)
        """
        print("Creating decision variables (with pruning)...")
        self.variables = {}

        # Map rooms by type
        rooms_by_type = {}
        for room in self.rooms:
            rooms_by_type.setdefault(room.room_type, []).append(room)

        # Caches for availability checks
        teacher_avail_cache = {}
        for teacher in self.teachers:
            teacher_avail_cache[teacher.id] = {
                (ts.day_index, ts.period_index): teacher.is_available(ts.day_index, ts.period_index)
                for ts in self.timeslots
            }
        room_avail_cache = {}
        for room in self.rooms:
            room_avail_cache[room.id] = {
                (ts.day_index, ts.period_index): room.is_available(ts.day_index, ts.period_index)
                for ts in self.timeslots
            }

        for allocation in self.allocations:
            classgroup = allocation.classgroup
            subject = allocation.subject
            teacher = allocation.teacher

            # candidate rooms (type fallback to all)
            candidate_rooms = rooms_by_type.get(subject.requires_room_type, [])
            if not candidate_rooms:
                candidate_rooms = self.rooms

            for period_num in range(subject.weekly_periods):
                for ts in self.timeslots:
                    # prune on teacher availability
                    if not teacher_avail_cache.get(teacher.id, {}).get((ts.day_index, ts.period_index), False):
                        continue

                    for room in candidate_rooms:
                        # prune on room availability and capacity
                        if not room_avail_cache.get(room.id, {}).get((ts.day_index, ts.period_index), False):
                            continue
                        if room.capacity < classgroup.student_count:
                            continue

                        var_name = f"c{classgroup.id}_s{subject.id}_t{teacher.id}_r{room.id}_ts{ts.id}_p{period_num}"
                        var = self.model.NewBoolVar(var_name)
                        self.variables[(classgroup.id, subject.id, teacher.id, room.id, ts.id, period_num)] = var

        total = len(self.variables)
        print(f"Total decision variables created after pruning: {total}")

        # detect allocations with zero candidate vars
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

        # store deterministic order for debugging
        if self.variables:
            self._vars_list = sorted(self.variables.items(), key=lambda kv: (kv[0][4], kv[0][0], kv[0][5]))
        else:
            self._vars_list = []

        return total

    def add_hard_constraints(self):
        """
        Add hard constraints:
         - Each required period (allocation.period_num) must be scheduled exactly once (if candidates exist)
         - No double-bookings (teacher, class, room)
         - Consecutive multi-period enforcement for subjects that require it (same day, consecutive timeslots, same room)
        """
        print("Adding hard constraints...")

        # 1) Each required subject period must be scheduled exactly once (per allocation & period index)
        for allocation in self.allocations:
            cg = allocation.classgroup
            subj = allocation.subject
            teacher = allocation.teacher

            for period_num in range(subj.weekly_periods):
                matching_vars = [
                    var for (c_id, s_id, t_id, r_id, ts_id, p_num), var in self.variables.items()
                    if c_id == cg.id and s_id == subj.id and t_id == teacher.id and p_num == period_num
                ]
                if matching_vars:
                    self.model.Add(sum(matching_vars) == 1)
                else:
                    # log - will be reported in conflict report
                    print(f"DEBUG: No candidates for allocation {allocation} period {period_num}")

        # 2) No teacher double-booking
        for teacher in self.teachers:
            for ts in self.timeslots:
                teacher_vars = [
                    var for (c, s, t, r, ts_id, p), var in self.variables.items()
                    if t == teacher.id and ts_id == ts.id
                ]
                if teacher_vars:
                    self.model.Add(sum(teacher_vars) <= 1)

        # 3) No class double-booking
        for cg in self.classes:
            for ts in self.timeslots:
                class_vars = [
                    var for (c, s, t, r, ts_id, p), var in self.variables.items()
                    if c == cg.id and ts_id == ts.id
                ]
                if class_vars:
                    self.model.Add(sum(class_vars) <= 1)

        # 4) No room double-booking
        for room in self.rooms:
            for ts in self.timeslots:
                room_vars = [
                    var for (c, s, t, r, ts_id, p), var in self.variables.items()
                    if r == room.id and ts_id == ts.id
                ]
                if room_vars:
                    self.model.Add(sum(room_vars) <= 1)

        # 5) Consecutive periods (strict enforcement) for allocations with requires_consecutive_periods=True
        # For each such allocation we create "start-room" indicator variables representing choosing a
        # start timeslot (on a given day) and a specific room that will host all consecutive periods.
        # Then we enforce exactly one start-room to be chosen and link it to the existing assignment vars.
        print("Applying consecutive-periods constraints for subjects that require them...")

        # Precompute timeslots by day and by day sorted order
        slots_by_day = {}
        for ts in self.timeslots:
            slots_by_day.setdefault(ts.day_index, []).append(ts)
        for day in slots_by_day:
            slots_by_day[day] = sorted(slots_by_day[day], key=lambda x: x.period_index)

        for alloc in self.allocations:
            subj = alloc.subject
            if not getattr(subj, 'requires_consecutive_periods', False):
                continue
            k = subj.weekly_periods
            if k <= 1:
                continue  # nothing to do

            cg = alloc.classgroup
            teacher = alloc.teacher

            # gather candidate rooms used in variables for this allocation (avoid non-existing combos)
            candidate_rooms = sorted({r for (c, s, t, r, ts, p) in self.variables.keys()
                                      if c == cg.id and s == subj.id and t == teacher.id})
            # If no candidate rooms overall, conflict report will handle later
            if not candidate_rooms:
                print(f"DEBUG: allocation {alloc} has no candidate rooms for consecutive enforcement.")
                continue

            # Build start-room vars
            start_room_vars = []
            # For optimization: only consider day-start positions where k consecutive slots exist
            for day_idx, day_slots in slots_by_day.items():
                if len(day_slots) < k:
                    continue
                for start_i in range(len(day_slots) - k + 1):
                    start_ts = day_slots[start_i]
                    # candidate timeslot sequence
                    seq_ts = [day_slots[start_i + offset] for offset in range(k)]
                    # Ensure all these timeslots are consecutive in period_index (they should be by construction),
                    # but verify consecutiveness in index to be safe
                    ok_seq = True
                    for idx in range(k - 1):
                        if seq_ts[idx + 1].period_index != seq_ts[idx].period_index + 1:
                            ok_seq = False
                            break
                    if not ok_seq:
                        continue

                    # For each room candidate, create a start-room indicator
                    for room_id in candidate_rooms:
                        # Check that room has variable candidates for each timeslot in sequence (with appropriate p)
                        has_all = True
                        for p_idx, ts_obj in enumerate(seq_ts):
                            # there could be multiple room-var combos; ensure at least one exists for this exact (room, ts, p_idx)
                            found = any(
                                1 for (c, s, t, r, ts_id, pnum) in self.variables.keys()
                                if c == cg.id and s == subj.id and t == teacher.id and r == room_id and ts_id == ts_obj.id and pnum == p_idx
                            )
                            if not found:
                                has_all = False
                                break
                        if not has_all:
                            continue

                        start_var = self.model.NewBoolVar(f"start_alloc{alloc.id}_d{day_idx}_s{start_i}_r{room_id}")
                        start_room_vars.append((start_var, day_idx, start_i, room_id, seq_ts))

                        # Link start_var -> for each p, some var with same (cg, subj, teacher, room_id, seq_ts[p], p) must be chosen
                        for p_idx, ts_obj in enumerate(seq_ts):
                            # gather all candidate assignment variables that match this exact (class,subject,teacher,room,ts,p)
                            candidate_assignment_vars = [
                                var for (c, s, t, r, ts_id, pnum), var in self.variables.items()
                                if c == cg.id and s == subj.id and t == teacher.id and r == room_id and ts_id == ts_obj.id and pnum == p_idx
                            ]
                            if candidate_assignment_vars:
                                # if start_var is chosen, one of candidate_assignment_vars must be 1
                                self.model.Add(sum(candidate_assignment_vars) >= 1).OnlyEnforceIf(start_var)
                                # conversely, if start_var=0 there's no restriction (other starts could satisfy)
                            else:
                                # shouldn't happen due to has_all check, but safe
                                pass

            # If we have any start_room_vars, require that exactly one of them is true (exactly one way to position the consecutive block)
            if start_room_vars:
                self.model.Add(sum(v for (v, d, s, r, seq) in start_room_vars) == 1)
            else:
                # No valid place to schedule consecutive block -> will be captured in conflict report
                print(f"DEBUG: No valid consecutive start positions found for allocation {alloc}")

    def add_soft_constraints(self):
        """
        Adds soft optimization objectives:
         - Minimize teacher gaps
         - Prefer difficult subjects early
         - Balance teacher daily workload (minimize max daily load)
         - Strong incentive to schedule each required allocation period
        """
        print("Adding soft constraints...")
        objective_terms = []  # tuples (var_or_intvar, weight)

        # Soft 1: minimize teacher gaps (approximation using 3-slot windows)
        gap_penalties = []
        for teacher in self.teachers:
            for day_idx in set(ts.day_index for ts in self.timeslots):
                day_slots = sorted([ts for ts in self.timeslots if ts.day_index == day_idx], key=lambda x: x.period_index)
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

                    has_before = self.model.NewBoolVar(f"has_before_t{teacher.id}_d{day_idx}_p{i}")
                    has_gap = self.model.NewBoolVar(f"has_gap_t{teacher.id}_d{day_idx}_p{i}")
                    has_after = self.model.NewBoolVar(f"has_after_t{teacher.id}_d{day_idx}_p{i}")

                    self.model.Add(sum(vars_before) >= 1).OnlyEnforceIf(has_before)
                    self.model.Add(sum(vars_before) == 0).OnlyEnforceIf(has_before.Not())

                    self.model.Add(sum(vars_gap) >= 1).OnlyEnforceIf(has_gap)
                    self.model.Add(sum(vars_gap) == 0).OnlyEnforceIf(has_gap.Not())

                    self.model.Add(sum(vars_after) >= 1).OnlyEnforceIf(has_after)
                    self.model.Add(sum(vars_after) == 0).OnlyEnforceIf(has_after.Not())

                    gap_bool = self.model.NewBoolVar(f"gap_exists_t{teacher.id}_d{day_idx}_p{i}")
                    # gap_bool == (has_before AND NOT has_gap AND has_after)
                    self.model.AddBoolAnd([has_before, has_after, has_gap.Not()]).OnlyEnforceIf(gap_bool)
                    gap_penalties.append(gap_bool)

        for g in gap_penalties:
            objective_terms.append((g, 5))  # weight 5

        # Soft 2: prefer difficult subjects early
        for alloc in self.allocations:
            subj = alloc.subject
            if getattr(subj, 'difficulty', None) == 'difficult':
                for ts in self.timeslots:
                    if ts.period_index <= 1:
                        for (c, s, t, r, ts_id, p), var in self.variables.items():
                            if c == alloc.classgroup.id and s == subj.id and ts_id == ts.id:
                                objective_terms.append((var, -2))  # negative weight favors assignment early

        # Soft 3: balanced teacher daily max
        workload_vars = []
        for teacher in self.teachers:
            daily_loads = []
            for day_idx in set(ts.day_index for ts in self.timeslots):
                day_slots = [ts for ts in self.timeslots if ts.day_index == day_idx]
                if not day_slots:
                    continue
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

        for wl in workload_vars:
            objective_terms.append((wl, 1))

        # Soft 4 (debug/strong): prefer scheduling each required allocation period (encourage feasibility)
        for alloc in self.allocations:
            for period_num in range(alloc.subject.weekly_periods):
                vars_for_slot = [
                    var for (c, s, t, r, ts, p), var in self.variables.items()
                    if c == alloc.classgroup.id and s == alloc.subject.id and t == alloc.teacher.id and p == period_num
                ]
                if vars_for_slot:
                    allocated = self.model.NewBoolVar(f"allocated_alloc{alloc.id}_p{period_num}")
                    self.model.Add(sum(vars_for_slot) >= 1).OnlyEnforceIf(allocated)
                    self.model.Add(sum(vars_for_slot) == 0).OnlyEnforceIf(allocated.Not())
                    # strong negative weight: prefer allocated==1
                    objective_terms.append((allocated, -50))

        # Build linear objective
        if objective_terms:
            linear_list = [weight * var for (var, weight) in objective_terms]
            self.model.Minimize(sum(linear_list))
        else:
            self.model.Minimize(0)

    def solve(self, time_limit_seconds=300):
        print(f"Starting solver with {time_limit_seconds}s time limit...")
        self.solver.parameters.max_time_in_seconds = time_limit_seconds
        self.solver.parameters.log_search_progress = True
        self.solver.parameters.num_search_workers = 8
        self.solver.parameters.random_seed = 0

        status = self.solver.Solve(self.model)

        print("=== Solver diagnostics ===")
        try:
            print(self.solver.ResponseStats())
        except Exception:
            pass
        print(f"Solver numeric status: {status}")
        try:
            print(f"Solver status: {self.solver.StatusName(status)}")
        except Exception:
            pass
        try:
            print(f"Wall time used: {self.solver.WallTime()}s")
        except Exception:
            pass
        print("==========================")

        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            solution = self.extract_solution()
            if not solution:
                print("Solver returned FEASIBLE/OPTIMAL but no variables set to 1. Check model.")
            return status, solution
        else:
            conflicts = self.generate_conflict_report(status)
            print(f"Conflicts generated: {len(conflicts)}")
            return status, None

    def extract_solution(self):
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
        print(f"Saving {len(solution)} timetable entries...")
        with transaction.atomic():
            TimetableEntry.objects.filter(is_locked=False).delete()
            entries = []
            for e in solution:
                entries.append(TimetableEntry(
                    classgroup_id=e['classgroup_id'],
                    subject_id=e['subject_id'],
                    teacher_id=e['teacher_id'],
                    room_id=e['room_id'],
                    timeslot_id=e['timeslot_id'],
                    is_locked=False
                ))
            TimetableEntry.objects.bulk_create(entries)
            print("Solution saved successfully!")

    def generate_conflict_report(self, status):
        ConflictReport.objects.all().delete()
        reports = []

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

        # allocs with zero candidate vars
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

        # room shortages per subject type
        for subj in self.subjects:
            req_type = subj.requires_room_type
            if req_type:
                count = Room.objects.filter(room_type=req_type).count()
                if count == 0:
                    reports.append(ConflictReport(
                        severity='error',
                        message=f"No rooms of type '{req_type}' for subject {subj.name}",
                        details={'subject': subj.name, 'required_type': req_type}
                    ))

        # teacher availability overloads
        for teacher in self.teachers:
            available_slots = sum(1 for ts in self.timeslots if teacher.is_available(ts.day_index, ts.period_index))
            required_periods = sum(alloc.subject.weekly_periods for alloc in self.allocations if alloc.teacher_id == teacher.id)
            if required_periods > available_slots:
                reports.append(ConflictReport(
                    severity='error',
                    message=f"Teacher {teacher.name} appears overallocated",
                    details={'teacher': teacher.name, 'required': required_periods, 'available': available_slots}
                ))

        # class overloads
        total_timeslots = len(self.timeslots)
        for cg in self.classes:
            required_for_class = sum(alloc.subject.weekly_periods for alloc in self.allocations if alloc.classgroup_id == cg.id)
            if required_for_class > total_timeslots:
                reports.append(ConflictReport(
                    severity='error',
                    message=f"Class {cg.name} requires more periods ({required_for_class}) than available timeslots ({total_timeslots})",
                    details={'class': cg.name, 'required': required_for_class, 'available': total_timeslots}
                ))

        if not reports and status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            reports.append(ConflictReport(
                severity='warning' if status == cp_model.UNKNOWN else 'error',
                message="Solver did not produce a timetable but no specific conflict was detected.",
                details={'status': status_name, 'advice': 'Try increasing time limit, inspect allocations and rooms.'}
            ))

        if reports:
            ConflictReport.objects.bulk_create(reports)
        return reports


def generate_timeslots():
    settings = SchoolSettings.objects.first()
    if not settings:
        raise ValueError("School settings not configured")

    TimeSlot.objects.all().delete()

    timeslots = []
    for day_idx in range(settings.days_per_week):
        current_time = datetime.combine(datetime.today(), settings.lesson_start_time)
        period_idx = 0

        for _ in range(settings.periods_before_break):
            end_time = (current_time + timedelta(minutes=settings.lesson_duration_min)).time()
            timeslots.append(TimeSlot(day_index=day_idx, period_index=period_idx,
                                      start_time=current_time.time(), end_time=end_time))
            period_idx += 1
            current_time = datetime.combine(datetime.today(), end_time)

        current_time = current_time + timedelta(minutes=settings.break_duration_min)

        for _ in range(settings.periods_after_break):
            end_time = (current_time + timedelta(minutes=settings.lesson_duration_min)).time()
            timeslots.append(TimeSlot(day_index=day_idx, period_index=period_idx,
                                      start_time=current_time.time(), end_time=end_time))
            period_idx += 1
            current_time = datetime.combine(datetime.today(), end_time)

        current_time = current_time + timedelta(minutes=settings.lunch_duration_min)

    TimeSlot.objects.bulk_create(timeslots)
    print(f"Generated {len(timeslots)} time slots")
    return timeslots



