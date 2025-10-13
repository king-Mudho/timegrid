#!/bin/bash

# TimeGrid Lite Installation Verification Script

echo "========================================"
echo "TimeGrid Lite - Installation Verification"
echo "========================================"
echo ""

# Check Python version
echo "1. Checking Python version..."
python3 --version
if [ $? -ne 0 ]; then
    echo "❌ Python 3 not found. Please install Python 3.8 or higher."
    exit 1
fi
echo "✅ Python found"
echo ""

# Check if virtual environment is activated
echo "2. Checking virtual environment..."
if [[ "$VIRTUAL_ENV" != "" ]]; then
    echo "✅ Virtual environment is active: $VIRTUAL_ENV"
else
    echo "⚠️  Virtual environment not activated. Run: source venv/bin/activate"
fi
echo ""

# Check if requirements are installed
echo "3. Checking dependencies..."
python3 -c "import django" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ Django installed"
else
    echo "❌ Django not found. Run: pip install -r requirements.txt"
    exit 1
fi

python3 -c "import ortools" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ OR-Tools installed"
else
    echo "❌ OR-Tools not found. Run: pip install -r requirements.txt"
    exit 1
fi
echo ""

# Check if .env file exists
echo "4. Checking configuration..."
if [ -f ".env" ]; then
    echo "✅ .env file exists"
else
    echo "⚠️  .env file not found. Copy .env.example to .env and configure it."
fi
echo ""

# Check if database is configured
echo "5. Checking database..."
python3 manage.py check --database default 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ Database configuration valid"
else
    echo "❌ Database configuration error. Check your .env settings or switch to SQLite."
fi
echo ""

# Check if migrations exist
echo "6. Checking migrations..."
if [ -d "timetable/migrations" ]; then
    echo "✅ Migrations directory exists"
else
    echo "⚠️  Migrations not found. Run: python manage.py makemigrations"
fi
echo ""

# Check project structure
echo "7. Checking project files..."
files=("manage.py" "timegrid/settings.py" "timetable/models.py" "timetable/solver.py" "timetable/views.py")
all_found=true
for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo "✅ $file"
    else
        echo "❌ $file not found"
        all_found=false
    fi
done
echo ""

# Summary
echo "========================================"
echo "Verification Complete!"
echo "========================================"
echo ""

if [ "$all_found" = true ]; then
    echo "✅ All critical files found"
    echo ""
    echo "Next steps:"
    echo "1. Activate venv: source venv/bin/activate"
    echo "2. Configure .env file (or use SQLite)"
    echo "3. Run migrations: python manage.py migrate"
    echo "4. Create superuser: python manage.py createsuperuser"
    echo "5. Load sample data: python manage.py loaddata timetable/fixtures/sample_data.json"
    echo "6. Start server: python manage.py runserver"
    echo ""
    echo "Visit: http://127.0.0.1:8000"
else
    echo "❌ Some files are missing. Please check the installation."
fi
