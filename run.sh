#!/bin/bash

echo "Starting Trading Bot System..."

# 1. Setup Python Virtual Environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python -m venv venv
fi

# Activate venv (Handle Windows/Linux paths)
if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi

# 2. Install requirements
echo "Installing dependencies..."
pip install -r requirements.txt

# 3. Start Backend Server
echo "Starting Backend API..."
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

# 4. Start Frontend Dev Server
echo "Starting Frontend..."
cd frontend
npm run dev &
FRONTEND_PID=$!

# Cleanup on exit
trap "kill $BACKEND_PID $FRONTEND_PID" EXIT

wait
