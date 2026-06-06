@echo off
chcp 65001 >nul
cd /d "%~dp0.."

echo Watching for changes in %CD%...
echo Press Ctrl+C to stop.

:loop
echo [%date% %time%] Starting uvicorn...
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --no-reload

echo [%date% %time%] Server stopped, restarting in 2 seconds...
timeout /t 2 /nobreak >nul
goto loop
