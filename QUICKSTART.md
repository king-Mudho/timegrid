# Quick Start Guide

Get TimeGrid Lite running in 5 minutes!

## 1. Install Dependencies

```bash
cd django_timetable
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure Database

**Option A - SQLite (Easiest for testing)**:

Edit `timegrid/settings.py`, replace the DATABASES section with:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
```

**Option B - PostgreSQL**:

```bash
# Create database
psql -U postgres
CREATE DATABASE timegrid_db;
\q

# Create .env file
cp .env.example .env
# Edit .env with your database credentials
```

## 3. Initialize Database

```bash
python manage.py migrate
python manage.py createsuperuser  # Create admin account
python manage.py loaddata timetable/fixtures/sample_data.json  # Load demo data
```

## 4. Run Server

```bash
python manage.py runserver
```

Visit: **http://127.0.0.1:8000**

## 5. Initial Setup

1. Login to admin: http://127.0.0.1:8000/admin
2. Go to Dashboard: http://127.0.0.1:8000
3. If you loaded sample data:
   - Admin → Classes → Grade 10A → Allocate teachers
   - Assign teachers to subjects
   - Go to Dashboard → Generate Timetable
4. View the generated timetable!

## Sample Data Loaded

- **School**: Greenwood High School
- **Subjects**: Math, Physics, Chemistry, English, CS, PE
- **Teachers**: 6 teachers with various specializations
- **Rooms**: 6 rooms (classrooms, labs, gym)
- **Classes**: Grade 10A, Grade 10B

## Next Steps

- **Add More Data**: Admin interface → Add subjects, teachers, rooms, classes
- **CSV Import**: Admin → Subjects/Teachers/Classes/Rooms → Import from CSV
- **Generate Timetable**: Dashboard → Generate Timetable button
- **View Schedules**: Navigate to Teachers, Classes, or Rooms
- **Export**: Use PDF/Excel/CSV export buttons on any timetable view

## Troubleshooting

**ImportError: No module named 'ortools'**
```bash
pip install ortools==9.8.3296
```

**Database connection error**
- Check PostgreSQL is running
- Verify credentials in `.env`
- Or switch to SQLite (see Option A above)

**Static files not loading**
```bash
python manage.py collectstatic
```

**Permission denied on manage.py**
```bash
chmod +x manage.py
```

## Key URLs

- **Dashboard**: http://127.0.0.1:8000/
- **Admin**: http://127.0.0.1:8000/admin/
- **Master Timetable**: http://127.0.0.1:8000/master/
- **Generate**: http://127.0.0.1:8000/generate/
- **Teachers**: http://127.0.0.1:8000/teachers/
- **Classes**: http://127.0.0.1:8000/classes/
- **Rooms**: http://127.0.0.1:8000/rooms/

## Tips

- Start with **2-3 classes** for faster solving
- Each teacher should be assigned to their subjects in Admin
- Room types must match subject requirements
- If solver fails, check the Conflict Report for details
