@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "BACKEND_ROOT=%~dp0"
if "%BACKEND_ROOT:~-1%"=="\" set "BACKEND_ROOT=%BACKEND_ROOT:~0,-1%"
set "PYTHON=%BACKEND_ROOT%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Python executable not found: %PYTHON%
    exit /b 1
)

REM Start the background worker. ZIP exports, auto peer-review and attachment
REM cleanup all run there; without it export jobs stay PENDING forever.
REM Set COURSEWORK_SKIP_WORKER=1 if the worker is already running elsewhere.
set "WORKER_PID="
if not defined COURSEWORK_SKIP_WORKER (
    for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "(Start-Process -FilePath '%PYTHON%' -ArgumentList '-m','app.worker' -WorkingDirectory '%BACKEND_ROOT%' -WindowStyle Hidden -PassThru).Id"`) do set "WORKER_PID=%%P"
    echo Background worker started, PID !WORKER_PID!
)

pushd "%BACKEND_ROOT%"
"%PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port 9006
set "EXIT_CODE=%ERRORLEVEL%"
popd

if defined WORKER_PID taskkill /PID !WORKER_PID! /T /F >nul 2>&1
exit /b %EXIT_CODE%
