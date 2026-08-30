@echo off
rem  One night of curation. Scheduled by schedule-windows.bat; also fine to
rem  double-click. Mirrors the reader's environment resolution.
setlocal
cd /d "%~dp0.."
set "ACT="
for %%P in (
  "%USERPROFILE%\miniconda3\Scripts\activate.bat"
  "%USERPROFILE%\anaconda3\Scripts\activate.bat"
  "%LOCALAPPDATA%\miniconda3\Scripts\activate.bat"
  "%ProgramData%\miniconda3\Scripts\activate.bat"
) do if not defined ACT if exist %%P set "ACT=%%~P"
if defined ACT (
  call "%ACT%" reader
) else if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
)
python -m curator.run >> "%LOCALAPPDATA%\ReadingDesk\curator\night.log" 2>&1
