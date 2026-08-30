@echo off
rem  LLMersion-1 — one-time setup for Windows.
rem  Finds conda (or falls back to venv), builds the environment, installs the
rem  right PyTorch for this machine, then the reader and its default models.
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo   LLMersion-1 setup
echo   ------------------------------------------------------------

if not exist "server\main.py" (
  echo   Wrong folder: %CD% has no server\main.py
  echo   Put setup-windows.bat in the folder that contains server\ and web\.
  pause
  exit /b 1
)

rem ---------------------------------------------------------------- conda?
set "ACT="
for %%P in (
  "%USERPROFILE%\miniconda3\Scripts\activate.bat"
  "%USERPROFILE%\anaconda3\Scripts\activate.bat"
  "%LOCALAPPDATA%\miniconda3\Scripts\activate.bat"
  "%ProgramData%\miniconda3\Scripts\activate.bat"
  "%ProgramData%\anaconda3\Scripts\activate.bat"
) do if not defined ACT if exist %%P set "ACT=%%~P"

if defined ACT (
  echo   conda      found
  call "%ACT%"
  conda env list | findstr /b /c:"reader " >nul
  if errorlevel 1 (
    echo   creating environment "reader" with Python 3.12 ...
    call conda create -n reader python=3.12 -y || goto :fail
  ) else (
    echo   environment "reader" already exists
  )
  call conda activate reader || goto :fail
) else (
  echo   conda      not found, using a local .venv instead
  where python >nul 2>&1
  if errorlevel 1 (
    echo.
    echo   No Python either. Install Python 3.12 from python.org and tick
    echo   "Add python.exe to PATH", then run this again in a NEW terminal.
    pause
    exit /b 1
  )
  if not exist ".venv\Scripts\activate.bat" python -m venv .venv || goto :fail
  call ".venv\Scripts\activate.bat" || goto :fail
)

python -m pip install --upgrade pip --quiet

rem ---------------------------------------------------------------- torch
echo.
nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo   GPU        none detected — installing CPU PyTorch
  echo              Kokoro still works, roughly 1-3x realtime
  pip install torch || goto :fail
) else (
  set "IDX=cu128"
  for /f "tokens=*" %%i in ('nvidia-smi ^| findstr /c:"CUDA Version"') do set "SMI=%%i"
  echo !SMI! | findstr /c:"CUDA Version: 13" >nul && set "IDX=cu130"
  echo   GPU        NVIDIA detected — installing PyTorch !IDX!
  echo              this is ~2 GB and takes a few minutes
  pip install torch --index-url https://download.pytorch.org/whl/!IDX! || goto :fail
)

rem ---------------------------------------------------------------- the app
echo.
echo   installing the reader ...
pip install -r requirements\core.txt --quiet || goto :fail
echo   installing Kokoro (the voice) ...
pip install -r requirements\voice.txt --quiet || goto :fail
echo   installing the small translation model and pronunciation scoring ...
pip install -r requirements\translate.txt --quiet || goto :fail
rem optional speed-up; there is a working fallback if the wheel is unavailable
pip install blingfire --quiet 2>nul

rem ---------------------------------------------------------------- check
echo.
echo   ------------------------------------------------------------
python -c "import torch;d='cuda' if torch.cuda.is_available() else 'cpu';print('  torch     ',torch.__version__,'on',d);x=torch.randn(512,512,device=d);float((x@x).sum());print('  kernel     ok')" || goto :fail
python -c "import fitz,fastapi,soundfile;print('  reader     ok')" || goto :fail
python -c "import kokoro;print('  kokoro     ok')" || goto :fail
python -c "import transformers;print('  translate  ok (opus-mt, downloads on first use)')" || goto :fail
echo   ------------------------------------------------------------
echo.
echo   Done. Double-click start-windows.bat to run it.
echo   For better Chinese, see docs\INSTALL.md for Ollama.
echo.
pause
exit /b 0

:fail
echo.
echo   Setup failed on the step above. The error is printed there.
pause
exit /b 1
