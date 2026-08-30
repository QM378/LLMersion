@echo off
rem  Register the curator as a nightly Task Scheduler job (02:30, wakes only if
rem  the machine is on). Run once. Remove with:
rem      schtasks /Delete /TN "ReadingDesk Curator" /F
schtasks /Create /F /SC DAILY /ST 02:30 /TN "ReadingDesk Curator" ^
  /TR "\"%~dp0nightly-windows.bat\""
if errorlevel 1 (
  echo   Could not create the task ^(needs a normal user session^).
) else (
  echo   Scheduled: every night at 02:30. Log: %%LOCALAPPDATA%%\ReadingDesk\curator\night.log
)
pause
