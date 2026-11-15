@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul 2>&1
set "PALM_MODE=packaged"
set "PALM_APP_ROOT=%~dp0"
if not defined PALM_DATA_DIR (
    if defined LOCALAPPDATA (
        set "PALM_DATA_DIR=%LOCALAPPDATA%\palm"
    ) else (
        set "PALM_DATA_DIR=%USERPROFILE%\AppData\Local\palm"
    )
)
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PALM_PYTHON=%~dp0python\python.exe"
if not exist "%PALM_PYTHON%" set "PALM_PYTHON=%~dp0python\Scripts\python.exe"
if not exist "%PALM_PYTHON%" (
    echo palm: embedded Python not found at "%~dp0python\python.exe" or "%~dp0python\Scripts\python.exe" 1>&2
    exit /b 1
)
"%PALM_PYTHON%" -m basseparate.launcher %*
exit /b %ERRORLEVEL%
