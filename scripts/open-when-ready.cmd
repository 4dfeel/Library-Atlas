@echo off
setlocal
set /a tries=0
:wait
curl.exe -fs -o nul "%~1api/v1/health" 2>nul
if not errorlevel 1 goto open
set /a tries+=1
if %tries% geq 60 exit /b 1
ping -n 2 127.0.0.1 >nul
goto wait
:open
start "" "%~1"
exit /b 0
