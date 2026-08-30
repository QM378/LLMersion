@echo off
rem  LLMersion-1 — double-click to run. No PATH changes, no cd, no conda prompt.
rem  Pass "dev" as an argument for the no-model test voice: start-windows.bat dev
setlocal

cd /d "%~dp0"

rem --- am I in the right folder? ------------------------------------------
if not exist "server\main.py" (
  echo.
  echo   This script is sitting in:
  echo       %CD%
  echo   but there is no  server\main.py  here, so this is the wrong folder.
  echo.
  echo   Move start-windows.bat into the folder that contains the
  echo   server\  and  web\  subfolders, and run it again.
  echo.
  pause
  exit /b 1
)

rem --- find conda, wherever the installer put it --------------------------
set "ACT="
for %%P in (
  "%USERPROFILE%\miniconda3\Scripts\activate.bat"
  "%USERPROFILE%\anaconda3\Scripts\activate.bat"
  "%LOCALAPPDATA%\miniconda3\Scripts\activate.bat"
  "%ProgramData%\miniconda3\Scripts\activate.bat"
  "%ProgramData%\anaconda3\Scripts\activate.bat"
) do if not defined ACT if exist %%P set "ACT=%%~P"

if defined ACT (
  call "%ACT%" reader
) else if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
) else (
  echo.
  echo   Could not find the "reader" conda environment or a .venv folder.
  echo   Run setup-windows.bat first.
  echo.
  pause
  exit /b 1
)

if /i "%~1"=="dev" set PR_DEV=1

python -m server.main

echo.
echo   The server stopped. Scroll up for the reason.
pause
