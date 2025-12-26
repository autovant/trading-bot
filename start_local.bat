@echo off
echo ===================================================
echo   Trading Bot - No-Docker Monolith Mode
echo ===================================================
echo.
echo [1/3] Environment Setup...
echo Database: data/trading.db
echo Messaging: In-Memory
echo.

echo [2/3] Starting Backend (Monolith)...
start "Trading Bot Backend" cmd /k "venv\Scripts\activate && python src/monolith.py"

echo [3/3] Starting Frontend...
cd frontend
start "Trading Bot Frontend" cmd /k "npm run dev"
cd ..

echo.
echo ===================================================
echo   App is starting!
echo   API: http://localhost:8000
echo   UI:  http://localhost:3000
echo ===================================================
echo.
echo Check the two new terminal windows for logs.
echo Press any key to exit this launcher (terminals will stay open).
pause
