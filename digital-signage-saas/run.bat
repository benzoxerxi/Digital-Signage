@echo off
echo.
echo ========================================
echo   Digital Signage SaaS - Quick Start
echo ========================================
echo.

REM Check if virtual environment exists
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
if exist "requirements.txt" (
    pip install -q -r requirements.txt
) else (
    echo requirements.txt not found, installing manually...
    pip install Flask Flask-CORS Flask-Login Flask-SQLAlchemy Werkzeug stripe python-dotenv bcrypt
)

REM Check if .env exists
if not exist ".env" (
    echo Creating .env file...
    if exist ".env.example" (
        copy .env.example .env
    ) else (
        echo SECRET_KEY=change-this-to-a-random-secret-key-in-production > .env
        echo DATABASE_URL=sqlite:///signage.db >> .env
    )
    echo Please edit .env with your configuration!
)

REM Create data directories
echo Creating data directories...
if not exist "data\tenants\" mkdir data\tenants

REM Set Python path to current directory
set PYTHONPATH=%CD%

REM Initialize database
echo Initializing database...
if not exist "signage.db" (
    python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Database created!')"
)

REM Start application
echo.
echo ========================================
echo   Starting Digital Signage SaaS...
echo ========================================
echo.
echo Access your application at:
echo    - Local: http://localhost:5000
echo.
echo Default admin login:
echo    Username: admin
echo    Password: admin123
echo.
echo Press Ctrl+C to stop the server
echo.

python app.py

pause
