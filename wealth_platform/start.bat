@echo off
title WealthFlow - FastAPI Server

cd /d "%~dp0"

echo.
echo ==========================================
echo          WealthFlow is starting...
echo ==========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Python virtual environment was not found.
    echo.
    echo Make sure this file is inside your WealthFlow project folder.
    echo.
    pause
    exit /b 1
)

echo Starting FastAPI server...
echo.
echo Open your browser at:
echo http://127.0.0.1:8000
echo.
echo Keep this window open while using WealthFlow.
echo Press Ctrl+C to stop the server.
echo.

".venv\Scripts\python.exe" -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

echo.
echo WealthFlow server stopped.
pause
