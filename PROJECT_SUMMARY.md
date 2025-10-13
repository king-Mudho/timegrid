# Melsoft TimeGrid - Project Summary

## Overview

**Melsoft TimeGrid** is a complete Django-based school timetable generator using Google OR-Tools constraint programming. The application generates conflict-free timetables while respecting hard constraints (no double-booking, availability, room types) and optimizing soft preferences (balanced workload, early scheduling of difficult subjects).

## Project Statistics

- **Total Lines of Code**: ~1,800 lines (core modules)
- **Models**: 9 Django models
- **Views**: 12 view functions
- **Templates**: 16 HTML templates
- **Technology Stack**: Django 5.0 + OR-Tools 9.8 + Bootstrap 5 + PostgreSQL

## Project Structure

```
django_timetable/
├── manage.py                          # Django management script
├── requirements.txt                   # Python dependencies
├── README.md                          # Full documentation
├── QUICKSTART.md                      # 5-minute setup guide
├── .env.example                       # Environment variables template
├── .gitignore                         # Git ignore rules
│
├── timegrid/                          # Django project configuration
│   ├── __init__.py
│   ├── settings.py                    # Project settings (DB, apps, middleware)
│   ├── urls.py                        # Root URL configuration
│   ├── wsgi.py                        # WSGI entry point
│   └── asgi.py                        # ASGI entry point
│
├── timetable/                         # Main application
│   ├── __init__.py
│   ├── apps.py                        # App configuration
│   ├── models.py                      # 9 Django models (278 lines)
│   ├── admin.py                       # Admin interface + CSV import (302 lines)
│   ├── views.py                       # 12 view functions (383 lines)
│   ├── urls.py                        # App URL routing
│   ├── solver.py                      # OR-Tools constraint solver (487 lines)
│   ├── export.py                      # PDF/Excel/CSV export (338 lines)
│   └── fixtures/
│       └── sample_data.json           # Demo data (6 teachers, 6 subjects, 2 classes)
│
├── templates/                         # HTML templates
│   ├── base.html                      # Base template with Bootstrap 5
│   ├── timetable/
│   │   ├── dashboard.html             # Main dashboard with stats
│   │   ├── generate.html              # Solver configuration page
│   │   ├── master_timetable.html      # Master grid view (drag-and-drop)
│   │   ├── teacher_list.html          # All teachers
│   │   ├── teacher_detail.html        # Individual teacher schedule
│   │   ├── class_list.html            # All classes
│   │   ├── class_detail.html          # Individual class schedule
│   │   ├── room_list.html             # All rooms
│   │   ├── room_detail.html           # Individual room schedule
│   │   ├── allocate_teachers.html     # Teacher allocation form
│   │   └── conflicts.html             # Conflict report
│   └── admin/
│       ├── csv_import_form.html       # CSV import interface
│       ├── subject_changelist.html    # Subject list with import button
│       ├── teacher_changelist.html    # Teacher list with import button
│       ├── class_changelist.html      # Class list with import button
│       └── room_changelist.html       # Room list with import button
│
└── static/                            # Static files (CSS/JS served by CDN)
    └── .gitkeep
```

## Core Features Implemented

### 1. Data Models (models.py)

| Model | Purpose | Key Fields |
|-------|---------|------------|
| SchoolSettings | Global configuration | school_name, academic_year, timing settings |
| Subject | Academic subjects | name, weekly_periods, difficulty, room_type |
| Teacher | Teaching staff | name, email, subjects (M2M), availability (JSON) |
| ClassGroup | Student groups | name, student_count, subjects (M2M) |
| Room | Physical spaces | name, room_type, capacity, availability (JSON) |
| TimeSlot | Schedule slots | day_index, period_index, start/end time |
| TimetableEntry | Scheduled lessons | teacher, class, subject, room, timeslot |
| TeacherSubjectAllocation | Teacher assignments | teacher, subject, class |
| ConflictReport | Solver violations | severity, message, details (JSON) |

### 2. OR-Tools Constraint Solver (solver.py)

**Hard Constraints**:
1. Each subject period scheduled exactly once
2. No teacher double-booking
3. No class double-booking
4. No room double-booking
5. Teacher availability respected
6. Room availability respected
7. Room capacity ≥ class size
8. Consecutive periods for practical subjects

**Soft Constraints (Optimization)**:
1. Minimize teacher idle gaps
2. Schedule difficult subjects early in day
3. Balance teacher workload across days

**Solver Class Methods**:
- `load_data()`: Load all DB entities
- `create_variables()`: Create CP-SAT boolean variables
- `add_hard_constraints()`: Define mandatory rules
- `add_soft_constraints()`: Define optimization objectives
- `solve()`: Run CP-SAT solver with time limit
- `extract_solution()`: Parse solver output
- `save_solution()`: Write to database
- `generate_conflict_report()`: Analyze infeasibility

### 3. Admin Interface (admin.py)

- Full CRUD for all models
- CSV import for bulk data (Subjects, Teachers, Classes, Rooms)
- Auto-redirect to allocation page after class creation
- Custom list displays with filtering
- Inline editing where appropriate

### 4. Views & Templates (views.py + templates/)

| View | URL | Purpose |
|------|-----|---------|
| dashboard | `/` | Statistics, quick actions, charts |
| generate_timetable | `/generate/` | Solver configuration and execution |
| master_timetable | `/master/` | All classes in grid (drag-and-drop) |
| teacher_timetable | `/teachers/<id>/` | Individual teacher schedule |
| class_timetable | `/classes/<id>/` | Individual class schedule |
| room_timetable | `/rooms/<id>/` | Individual room schedule |
| allocate_teachers | `/allocate/<id>/` | Assign teachers to class subjects |
| conflict_report | `/conflicts/` | Show solver violations |
| update_entry | `/api/update-entry/` | AJAX endpoint for drag-and-drop |
| export_view | `/export/<format>/<type>/<id>/` | PDF/Excel/CSV export |

### 5. Export Functionality (export.py)

- **PDF**: Professional multi-page timetables (ReportLab)
- **Excel**: Formatted spreadsheets with styling (openpyxl)
- **CSV**: Raw data export for analysis
- Supports all view types (master, teacher, class, room)

### 6. UI/UX Features

- **Bootstrap 5** responsive design
- **Dashboard** with statistics cards and charts
- **Drag-and-drop** manual editing with constraint validation
- **Command palette** shortcut (floating action button)
- **Progress bars** for teacher workload and room utilization
- **Color-coded** conflict severity (error/warning/info)
- **Responsive tables** for all timetable views
- **Export buttons** on every timetable view

## Sample Data Included

The `sample_data.json` fixture includes:

- **1 School**: Greenwood High School (2024-2025)
- **6 Subjects**:
  - Mathematics (5 periods/week, difficult, theory)
  - Physics (4 periods/week, difficult, practical, lab)
  - Chemistry (4 periods/week, difficult, practical, lab)
  - English (4 periods/week, fair, theory)
  - Computer Science (3 periods/week, fair, practical, computer lab)
  - Physical Education (2 periods/week, easy, practical, gym)

- **6 Teachers**:
  - Dr. Sarah Johnson
  - Prof. Michael Chen
  - Mrs. Emily Davis
  - Mr. David Wilson
  - Ms. Rachel Martinez
  - Coach James Brown

- **6 Rooms**:
  - Room 101, 102 (classrooms, 40 capacity)
  - Physics Lab, Chemistry Lab (labs, 30 capacity)
  - Computer Lab A (35 capacity)
  - Gymnasium (60 capacity)

- **2 Classes**:
  - Grade 10A (35 students)
  - Grade 10B (32 students)

## Usage Workflow

1. **Setup**: Configure SchoolSettings, add Subjects, Teachers, Rooms
2. **Classes**: Add ClassGroup, assign subjects
3. **Allocate**: Assign qualified teachers to each class-subject pair
4. **Generate**: Run OR-Tools solver (generates TimeSlots automatically)
5. **View**: Browse Master/Teacher/Class/Room timetables
6. **Edit**: Drag-and-drop entries (validated against constraints)
7. **Export**: Download PDF/Excel/CSV reports
8. **Resolve**: Check Conflict Report if solver fails

## Technical Highlights

### OR-Tools Integration
- Uses CP-SAT (Constraint Programming - Satisfiability)
- Boolean decision variables for every possible assignment
- Efficient constraint propagation
- Multi-objective optimization

### Performance
- Small schools (2-3 classes): < 30 seconds
- Medium schools (5-10 classes): 1-2 minutes
- Configurable time limit (10-300 seconds)

### Database Design
- Normalized schema with proper foreign keys
- JSON fields for availability (flexible schedule patterns)
- Many-to-many relationships for subjects
- Unique constraints prevent duplicates

### Security
- CSRF protection on all forms
- Environment variables for secrets
- Django's built-in auth system
- Input validation on all user data

### Code Quality
- Comprehensive docstrings
- Clear variable naming
- Modular architecture
- Separation of concerns (models/views/templates/solver)

## Deployment Options

### Local Development
```bash
python manage.py runserver
```

### Production (Gunicorn + Nginx)
```bash
gunicorn timegrid.wsgi:application
```

### cPanel Shared Hosting
- Python App setup in cPanel
- PostgreSQL database
- Environment variables in `.htaccess`
- Static files via collectstatic

## Dependencies

```
Django==5.0.1               # Web framework
psycopg2-binary==2.9.10      # PostgreSQL adapter
ortools==9.8.3296           # Constraint solver
django-crispy-forms==2.3    # Form styling
crispy-bootstrap5==2.0.0    # Bootstrap 5 templates
openpyxl==3.1.2             # Excel export
reportlab==4.0.9            # PDF export
weasyprint==60.2            # Alternative PDF renderer
python-dotenv==1.0.1        # Environment variables
```

## Extensibility

The architecture supports:
- **Custom constraints**: Add to `solver.py`
- **New room types**: Extend `ROOM_TYPE_CHOICES`
- **Additional views**: Add to `views.py` and `urls.py`
- **Custom reports**: Create new templates
- **API endpoints**: Add REST API using Django REST Framework
- **Celery tasks**: Make solver run asynchronously
- **Multi-school**: Add school FK to all models
- **Automated scheduling**: Cron job for weekly generation

## Known Limitations

1. **Synchronous solver**: Blocks request during generation (use Celery for async)
2. **Single school**: Multi-tenant support requires schema changes
3. **Basic availability**: No advanced patterns (bi-weekly, rotating schedules)
4. **No calendar integration**: Could export to iCal/Google Calendar
5. **Limited reporting**: Could add analytics dashboard

## Future Enhancements

- [ ] Celery integration for async solver
- [ ] Real-time conflict detection (websockets)
- [ ] Advanced availability patterns
- [ ] Calendar export (iCal, Google Calendar)
- [ ] Mobile app (React Native)
- [ ] Multi-school support
- [ ] Teacher preferences/requests
- [ ] Substitution management
- [ ] Historical data & analytics
- [ ] API for third-party integrations

## Testing

To run basic functionality test:

```bash
python manage.py shell
>>> from timetable.solver import generate_timeslots
>>> from timetable.models import SchoolSettings
>>> settings = SchoolSettings.objects.first()
>>> if settings:
...     generate_timeslots()
...     print("Timeslots generated successfully!")
```

## File Count Summary

- **Python files**: 14
- **HTML templates**: 16
- **Config files**: 6 (.env.example, requirements.txt, etc.)
- **Total core code**: ~1,800 lines
- **Documentation**: 3 files (README, QUICKSTART, PROJECT_SUMMARY)

## License & Credits

- **Framework**: Django (BSD License)
- **Solver**: Google OR-Tools (Apache 2.0)
- **UI**: Bootstrap 5 (MIT License)

This project is provided as-is for educational and commercial use.

---

**Ready to use!** Follow `QUICKSTART.md` to get started in 5 minutes.
