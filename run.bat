@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  python -m venv .venv || goto :err
  .venv\Scripts\python -m pip install -r requirements.txt || goto :err
)
set PORT=8000
echo RepEng: http://localhost:%PORT%
start "" http://localhost:%PORT%
rem --host 0.0.0.0 makes it reachable from a phone on the same Wi-Fi.
rem Note: browsers allow the microphone only on localhost or https.
.venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port %PORT%
goto :eof
:err
echo Setup failed.
pause
