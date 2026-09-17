@echo off
setlocal EnableExtensions

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "BACKEND_ROOT=%PROJECT_ROOT%\backend"

if defined PYTHON_EXE (
    set "PYTHON=%PYTHON_EXE%"
) else (
    set "PYTHON=%BACKEND_ROOT%\.venv\Scripts\python.exe"
)

if "%~1"=="" (
    set "FRONTEND_DIST=%PROJECT_ROOT%\frontend\dist"
) else (
    for %%I in ("%~1") do set "FRONTEND_DIST=%%~fI"
)

if not exist "%PYTHON%" (
    echo Python executable not found: %PYTHON%
    echo Set PYTHON_EXE or create backend\.venv first.
    exit /b 1
)

if not exist "%FRONTEND_DIST%\index.html" (
    echo Frontend build not found: %FRONTEND_DIST%\index.html
    echo Run npm run build before deploying, or pass the dist directory as the first argument.
    exit /b 1
)

if not defined COURSEWORK_HOST set "COURSEWORK_HOST=0.0.0.0"
if not defined COURSEWORK_PORT set "COURSEWORK_PORT=8000"
if not defined COURSEWORK_WORKERS set "COURSEWORK_WORKERS=2"

echo Serving frontend from: %FRONTEND_DIST%
echo Listening on: %COURSEWORK_HOST%:%COURSEWORK_PORT%

pushd "%BACKEND_ROOT%"
"%PYTHON%" -m uvicorn app.main:app --host "%COURSEWORK_HOST%" --port "%COURSEWORK_PORT%" --workers "%COURSEWORK_WORKERS%"
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
