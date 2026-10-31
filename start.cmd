@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Library Atlas
if not defined ATLAS_PORT set "ATLAS_PORT=8765"
set "atlasUrl=http://127.0.0.1:%ATLAS_PORT%/"

if not exist backend\.venv\Scripts\python.exe goto not_installed
if not exist frontend\dist\index.html goto not_installed

curl.exe -fs -o nul "%atlasUrl%api/v1/health" 2>nul
if not errorlevel 1 goto already_running

if /I not "%~1"=="--no-browser" start "" /b cmd /c scripts\open-when-ready.cmd "%atlasUrl%"
echo.
echo   Library Atlas 正在运行：%atlasUrl%
echo   使用期间不要关闭这个窗口。用完后直接关掉它就行。
echo.
call scripts\serve.cmd
exit /b %errorlevel%

:already_running
echo   Library Atlas 已经在运行了，正在打开页面。
if /I not "%~1"=="--no-browser" start "" "%atlasUrl%"
exit /b 0

:not_installed
echo.
echo   还没有安装。请先双击 install.cmd，装好后再双击 start.cmd。
echo.
pause
exit /b 1
