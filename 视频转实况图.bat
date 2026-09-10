@echo off
rem 本文件保存为 GBK 编码（简体中文 Windows 的默认代码页）。
rem 请不要加 chcp 65001：中途切换代码页会让 cmd 解析不了后面的中文行。
setlocal enabledelayedexpansion
title 视频转实况图

rem ============================================================
rem   把一个或多个视频拖到本文件图标上，松手即可转成实况图
rem   输出：与视频同目录、同文件名的一对 .JPG + .MOV
rem ============================================================

rem 必须先记下来：下面的 shift 会把 %0 也顶掉
set "BATDIR=%~dp0"
set "SCRIPT=%BATDIR%livephoto.py"

if "%~1"=="" goto ask

set "OUTDIR=%~dp1"
set "OUTDIR=!OUTDIR:~0,-1!"
set "ARGS="
:collect
if "%~1"=="" goto run
set "ARGS=!ARGS! "%~1""
shift
goto collect

:ask
echo.
echo   把视频文件拖到本文件图标上松手即可。
echo   也可以直接粘贴视频路径：
echo.
set /p "ONE=  视频路径: "
if "!ONE!"=="" exit /b 1
set "ONE=!ONE:"=!"
for %%I in ("!ONE!") do set "OUTDIR=%%~dpI"
set "OUTDIR=!OUTDIR:~0,-1!"
set "ARGS="!ONE!""

:run
set "PY=python"
where python >nul 2>nul || set "PY=py"

if not exist "%SCRIPT%" goto noscript

echo.
echo   输出目录: !OUTDIR!
echo.
%PY% "%SCRIPT%" !ARGS! -o "!OUTDIR!"
echo.
echo   按任意键关闭窗口。
pause >nul
exit /b 0

:noscript
echo.
echo   找不到 livephoto.py，请确保它和本文件在同一个文件夹里。
echo   当前查找路径: %SCRIPT%
pause
exit /b 1
