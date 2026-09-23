@echo off
setlocal
cd /d "%~dp0"
set "PCSPACE_PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PCSPACE_PY%" set "PCSPACE_PY=python"
"%PCSPACE_PY%" -m pcspace --open
if errorlevel 1 pause
endlocal
