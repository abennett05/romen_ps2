@echo off
REM ISObe-PS2 launcher (Windows)

cd /d "%~dp0"

REM 1. Check if venv exists
if not exist venv (
    echo First time setup: Creating virtual environment...
    python -m venv venv

    REM 2. Activate and Install
    call venv\Scripts\activate
    echo Installing dependencies...
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate
)

REM 3. Run the server
echo Starting ISObe...
python server.py
pause
