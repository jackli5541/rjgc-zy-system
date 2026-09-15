@echo off
setlocal EnableExtensions

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "BACKEND_ROOT=%PROJECT_ROOT%\backend"
set "FRONTEND_ROOT=%PROJECT_ROOT%\frontend"
set "PYTHON=%BACKEND_ROOT%\.venv\Scripts\python.exe"
set "VITE=%FRONTEND_ROOT%\node_modules\vite\bin\vite.js"

if not exist "%PYTHON%" (
    echo Python virtual environment not found. Run scripts\init-local.ps1 first.
    exit /b 1
)
where node >nul 2>&1
if errorlevel 1 (
    echo Node.js was not found in PATH.
    exit /b 1
)
if not exist "%VITE%" (
    echo Frontend dependencies not found. Run scripts\init-local.ps1 first.
    exit /b 1
)

echo Starting API, worker and frontend...
pushd "%BACKEND_ROOT%"
start "coursework-api" /b "%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
start "coursework-worker" /b "%PYTHON%" -m app.worker
popd

pushd "%FRONTEND_ROOT%"
start "coursework-frontend" /b node "%VITE%" --host 0.0.0.0 --port 8080
popd

echo.
echo Services are running:
echo   Web: http://localhost:8080
echo   API: http://localhost:8000
echo Close this CMD window to stop all services.
echo.

:keep_alive
timeout /t 1 /nobreak >nul
goto keep_alive
