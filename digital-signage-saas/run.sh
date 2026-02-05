#!/bin/bash

echo "🎬 Digital Signage SaaS - Quick Start"
echo "======================================"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "✨ Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -q -r requirements.txt

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚙️  Creating .env file..."
    cp .env.example .env
    echo "⚠️  Please edit .env with your configuration!"
fi

# Create data directories
echo "📁 Creating data directories..."
mkdir -p data/tenants

# Initialize database
echo "🗄️  Initializing database..."
if [ ! -f "signage.db" ]; then
    python -c "from app import app, db; app.app_context().push(); db.create_all(); print('✅ Database created!')"
fi

# Start application
echo ""
echo "🚀 Starting Digital Signage SaaS..."
echo "======================================"
echo ""
echo "🌐 Access your application at:"
echo "   - Local: http://localhost:5000"
echo "   - Network: http://$(hostname -I | awk '{print $1}'):5000"
echo ""
echo "👤 Default admin login:"
echo "   Username: admin"
echo "   Password: admin123"
echo ""
echo "⚠️  Press Ctrl+C to stop the server"
echo ""

python app.py
