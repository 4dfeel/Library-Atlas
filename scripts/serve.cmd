@echo off
setlocal
pushd "%~dp0..\backend" || exit /b 1
if not exist .venv\Scripts\python.exe (
    echo Local service is not installed. Run scripts\setup-backend.cmd first.
    popd
    exit /b 1
)
.venv\Scripts\python.exe -m app serve %*
set "atlasExit=%errorlevel%"
popd
exit /b %atlasExit%
