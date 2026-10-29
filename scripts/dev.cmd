@echo off
setlocal
pushd "%~dp0..\frontend" || exit /b 1
if not exist node_modules\ (
    echo Dependencies missing. Run npm.cmd ci in frontend first.
    popd
    exit /b 1
)
if /I "%~1"=="preview" (
    call npm.cmd run preview
) else (
    call npm.cmd run dev
)
set "atlasExit=%errorlevel%"
popd
exit /b %atlasExit%
