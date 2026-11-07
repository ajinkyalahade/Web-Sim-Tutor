@echo off
setlocal
cd /d "%~dp0"
title WebSim

where uv >nul 2>nul
if errorlevel 1 (
    echo WebSim: installing uv ^(one-time, no admin password needed^)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

echo WebSim: preparing dependencies ^(first run downloads Python and packages^)...
uv sync
if errorlevel 1 goto error

echo WebSim: starting...
uv run websim %*
if errorlevel 1 goto error
exit /b 0

:error
echo.
echo WebSim stopped with an error. The message above explains why.
echo Full log: %CD%\.websim\logs\websim.log
echo.
pause
exit /b 1
