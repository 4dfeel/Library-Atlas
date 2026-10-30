@echo off
setlocal
pushd "%~dp0..\backend" || exit /b 1
if not exist .venv\Scripts\python.exe (
    py -3.14 -m venv .venv || (popd & exit /b 1)
)
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock || (popd & exit /b 1)
if /I "%~1"=="dev" (
    .venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock || (popd & exit /b 1)
)
popd
exit /b 0
