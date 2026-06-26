@echo off
echo ===================================================
echo  RefundAI - AI Customer Support Agent
echo ===================================================
echo.

REM Check if .env exists
if not exist .env (
    echo [ERROR] .env file not found!
    echo Please copy .env.example to .env and add your API keys.
    echo.
    echo   copy .env.example .env
    echo   Then edit .env with your COHERE_API_KEY and GROQ_API_KEY
    echo.
    pause
    exit /b 1
)

echo [OK] .env found
echo [OK] Starting server...
echo.
echo Customer Chat:   http://localhost:8000
echo Admin Dashboard: http://localhost:8000/admin
echo.
echo Press Ctrl+C to stop
echo.

venv\Scripts\python -m uvicorn backend.main:app --reload --port 8000 --host 0.0.0.0
