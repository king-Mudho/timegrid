# TimeGrid Lite - School Timetable Generator

A lightweight Django-based web application for generating conflict-free school timetables using Google OR-Tools constraint programming solver.

## Features

- **Constraint Programming Solver**: Uses Google OR-Tools CP-SAT to generate optimal, conflict-free timetables
- **Hard Constraints**:
  - No teacher, class, or room double-booking
  - Teacher and room availability respected
  - All curriculum hours satisfied
  - Consecutive periods for practical subjects
  - Room type and capacity matching

- **Soft Preferences**:
  - Balanced teacher workload across days
  - Difficult subjects scheduled early in the day
  - Minimized idle gaps in teacher schedules

- **Comprehensive UI**:
  - Dashboard with statistics and visualizations
  - Master timetable grid view
  - Individual views for teachers, classes, and rooms
  - Drag-and-drop manual editing with constraint validation
  - Conflict detection and reporting

- **Data Management**:
  - Full Django admin interface
  - CSV import for bulk data
  - Teacher-subject allocation workflow

- **Export Options**:
  - PDF (via ReportLab)
  - Excel (via openpyxl)
  - CSV

## Prerequisites

- Python 3.8 or higher
- PostgreSQL 12 or higher (or SQLite for development)
- pip (Python package manager)

## Installation

### 1. Clone or Extract the Project

```bash
cd django_timetable
```

### 2. Create Virtual Environment

```bash
python -m venv venv

# On Windows:
venv\Scripts\activate

# On macOS/Linux:
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and configure your settings:

```env
SECRET_KEY=your-secret-key-here-change-in-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database Configuration
DB_NAME=timegrid_db
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
```

**For SQLite (development only)**: You can modify `timegrid/settings.py` to use SQLite instead of PostgreSQL:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
```

### 5. Set Up Database

If using PostgreSQL, create the database:

```bash
# Using psql
psql -U postgres
CREATE DATABASE timegrid_db;
\q
```

Run migrations:

```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Create Superuser

```bash
python manage.py createsuperuser
```

Follow the prompts to create an admin account.

### 7. Load Sample Data (Optional)

```bash
python manage.py loaddata timetable/fixtures/sample_data.json
```

This loads:
- 1 School Settings configuration
- 6 Subjects (Math, Physics, Chemistry, English, CS, PE)
- 6 Teachers
- 6 Rooms
- 2 Classes

### 8. Run Development Server

```bash
python manage.py runserver
```

Visit `http://127.0.0.1:8000` to access the application.

## Usage

### Initial Setup

1. **Configure School Settings**:
   - Go to Admin → School Settings
   - Set school name, academic year, timing configuration

2. **Add Subjects**:
   - Admin → Subjects → Add Subject
   - Or use CSV import: Admin → Subjects → Import from CSV

3. **Add Teachers**:
   - Admin → Teachers → Add Teacher
   - Assign subjects to each teacher
   - Or use CSV import

4. **Add Rooms**:
   - Admin → Rooms → Add Room
   - Specify room type and capacity

5. **Add Classes**:
   - Admin → Classes → Add Class
   - Assign subjects to the class
   - After saving, you'll be redirected to allocate teachers

6. **Allocate Teachers**:
   - For each class-subject combination, assign a qualified teacher
   - This creates the teacher-subject allocations needed by the solver

### Generate Timetable

1. Click **"Generate Timetable"** from the dashboard
2. Set the solver time limit (default: 60 seconds)
3. Click **"Generate Timetable"**
4. The solver will run and either:
   - Generate a timetable (redirect to Master Timetable)
   - Report conflicts if constraints cannot be satisfied

### View Timetables

- **Master Timetable**: View all classes in a grid
- **Teacher Timetable**: Individual teacher schedules
- **Class Timetable**: Individual class schedules
- **Room Timetable**: Room occupancy schedules

### Manual Editing

On the Master Timetable view:
- **Drag and drop** entries to different time slots
- The system validates constraints before saving
- Locked entries (marked in admin) won't be modified by the solver

### Export Timetables

From any timetable view, click the export buttons:
- **PDF**: Professional formatted timetable
- **Excel**: Editable spreadsheet
- **CSV**: Raw data export

### Conflict Resolution

If the solver cannot generate a timetable:
1. View the **Conflict Report**
2. Check for:
   - Insufficient rooms of required types
   - Teacher overallocation
   - Teacher availability mismatches
   - Room capacity issues
3. Adjust your data accordingly
4. Retry generation

## CSV Import Format

### Subjects CSV
```csv
name,weekly_periods,subject_type,difficulty,requires_room_type,requires_consecutive_periods
Mathematics,5,theory,difficult,classroom,False
Physics,4,practical,difficult,lab,True
```

### Teachers CSV
```csv
name,email,max_periods_week,subjects
Dr. Sarah Johnson,s.johnson@school.edu,25,"Mathematics,Physics"
```

### Classes CSV
```csv
name,student_count,subjects
Grade 10A,35,"Mathematics,Physics,Chemistry,English"
```

### Rooms CSV
```csv
name,room_type,capacity
Room 101,classroom,40
Physics Lab,lab,30
```

## OR-Tools Solver Details

The solver uses **CP-SAT (Constraint Programming - Satisfiability)** from Google OR-Tools:

### Decision Variables
- Binary variable for each possible assignment: `assignment[class, subject, teacher, room, timeslot]`

### Hard Constraints
1. Each required period must be scheduled exactly once
2. No teacher double-booking
3. No class double-booking
4. No room double-booking
5. Teacher availability respected
6. Room availability respected
7. Room capacity ≥ class size
8. Consecutive periods for subjects requiring them

### Soft Constraints (Optimization)
1. Minimize teacher idle gaps (gaps in daily schedule)
2. Schedule difficult subjects early in the day
3. Balance teacher workload across days

### Performance
- Small schools (2-3 classes): < 30 seconds
- Medium schools (5-10 classes): 1-2 minutes
- Large schools (20+ classes): 3-5 minutes
- Increase time limit for complex scenarios

## Deployment

### Production Checklist

1. **Security**:
   ```python
   # settings.py
   DEBUG = False
   SECRET_KEY = 'strong-random-key'
   ALLOWED_HOSTS = ['yourdomain.com']
   ```

2. **Database**: Use PostgreSQL in production (not SQLite)

3. **Static Files**:
   ```bash
   python manage.py collectstatic
   ```

4. **WSGI Server**: Use gunicorn or uWSGI:
   ```bash
   pip install gunicorn
   gunicorn timegrid.wsgi:application
   ```

### cPanel Deployment

1. **Upload Files**:
   - Upload entire `django_timetable` folder to your cPanel account

2. **Setup Python App**:
   - In cPanel, go to "Setup Python App"
   - Python version: 3.8+
   - Application root: `/home/username/django_timetable`
   - Application URL: Choose your domain/subdomain
   - Application startup file: `timegrid/wsgi.py`
   - Application entry point: `application`

3. **Install Dependencies**:
   - Enter the Python environment:
     ```bash
     source /home/username/virtualenv/django_timetable/3.8/bin/activate
     cd /home/username/django_timetable
     pip install -r requirements.txt
     ```

4. **Configure Database**:
   - Create PostgreSQL database in cPanel
   - Update `.env` with database credentials

5. **Run Migrations**:
   ```bash
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py collectstatic --noinput
   ```

6. **Restart App**:
   - In cPanel Python App interface, click "Restart"

### Environment Variables in cPanel

Add to `.htaccess` in application root:

```apache
SetEnv SECRET_KEY "your-secret-key"
SetEnv DEBUG "False"
SetEnv DB_NAME "your_db_name"
SetEnv DB_USER "your_db_user"
SetEnv DB_PASSWORD "your_db_password"
```

## Troubleshooting

### Solver Takes Too Long
- Reduce the number of classes
- Increase time limit
- Simplify constraints (reduce weekly periods)
- Check for overallocation

### Infeasible Timetable
- Review conflict report
- Ensure sufficient rooms of each type
- Check teacher workload vs. availability
- Verify room capacities

### Import Errors
- Check CSV format matches expected headers
- Ensure data types are correct
- Look for special characters or encoding issues

### Performance Issues
- Add database indexes:
  ```bash
  python manage.py migrate
  ```
- Use PostgreSQL instead of SQLite
- Optimize queries in views (already done with `select_related`)

## License

This project is provided as-is for educational and commercial use.

## Support

For issues or questions:
1. Check the Conflict Report for solver issues
2. Review Django logs: `python manage.py runserver --verbosity 3`
3. Check OR-Tools documentation: https://developers.google.com/optimization

## Credits

- **Django**: Web framework
- **Google OR-Tools**: Constraint programming solver
- **Bootstrap 5**: UI framework
- **ReportLab**: PDF generation
- **openpyxl**: Excel export
