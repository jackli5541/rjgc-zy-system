@echo off
REM Build the frontend with the OSS URL as asset base. Output: dist\
REM Then upload dist\assets\* to OSS (lab/assets/) and copy the whole dist to the server.
cd /d "%~dp0"
set "VITE_CDN_BASE=https://cf-website.oss-cn-hangzhou.aliyuncs.com/lab/"
call npm run build
if errorlevel 1 (
    echo BUILD FAILED
) else (
    echo.
    echo BUILD OK: %~dp0dist
    echo Next: upload dist\assets\* to OSS lab/assets/, copy dist to server, restart backend
)
pause
