@echo off
REM Document conversation, beside the reader. Pass "dev" for the no-model demo.
cd /d "%~dp0"
if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat
python -m talk.main %1
if errorlevel 1 pause
