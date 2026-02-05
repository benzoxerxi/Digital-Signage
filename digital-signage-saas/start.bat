@echo off
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

REM Install dependencies one by one
echo Installing dependencies...
pip install Flask --quiet
pip install Flask-CORS --quiet
pip install Flask-Login --quiet
pip install Flask-SQLAlchemy --quiet
pip install Werkzeug --quiet
pip install stripe --quiet
pip install python-dotenv --quiet
pip install bcrypt --quiet

REM Check if .env exists
if not exist ".env" (
    echo Creating .env file...
    echo SECRET_KEY=dev-secret-key-change-in-production > .env
    echo DATABASE_URL=sqlite:///signage.db >> .env
    echo STRIPE_PUBLIC_KEY=pk_test_your_key_here >> .env
    echo STRIPE_SECRET_KEY=sk_test_your_key_here >> .env
    echo STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret_here >> .env
)

REM Create data directories
echo Creating data directories...
if not exist "data\tenants\" mkdir data\tenants

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

REM Start the application directly
python app.py

pause
