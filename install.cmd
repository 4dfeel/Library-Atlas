@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Library Atlas 安装

echo.
echo   正在安装 Library Atlas，大约需要几分钟。
echo   过程中可能闪过很多英文，不用管，等它结束就好。
echo.

py -3.14 --version >nul 2>nul
if errorlevel 1 goto no_python
where npm.cmd >nul 2>nul
if errorlevel 1 goto no_node

echo   [1/3] 安装本地服务...
call scripts\setup-backend.cmd
if errorlevel 1 goto failed

echo   [2/3] 安装页面组件...
pushd frontend
call npm.cmd ci
if errorlevel 1 goto failed_in_frontend

echo   [3/3] 构建页面...
call npm.cmd run build
if errorlevel 1 goto failed_in_frontend
popd

echo.
echo   安装完成！以后双击 start.cmd 就能打开 Library Atlas。
echo.
pause
exit /b 0

:no_python
echo   还没有安装 Python 3.14。请先安装它，然后重新双击 install.cmd。
echo   下载地址：https://www.python.org/ftp/python/3.14.3/python-3.14.3-amd64.exe
goto stop

:no_node
echo   还没有安装 Node.js。请先安装它，然后重新双击 install.cmd。
echo   下载地址：https://nodejs.org/dist/v22.22.1/node-v22.22.1-x64.msi
goto stop

:failed_in_frontend
popd
:failed
echo.
echo   安装没有成功，请看上面最后几行提示。重新双击 install.cmd 可以再试一次。
goto stop

:stop
echo.
pause
exit /b 1
