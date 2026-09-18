@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  set "PY=py -3"
  goto have_py
)
where python >nul 2>&1
if %ERRORLEVEL%==0 (
  set "PY=python"
  goto have_py
)
echo 需要先安装 Python 3.10+ ：https://www.python.org/downloads/
pause
exit /b 1

:have_py
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
  if errorlevel 1 goto fail
  ".venv\Scripts\python.exe" -m pip install -U pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto fail
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m witch
) else (
  start "" ".venv\Scripts\python.exe" -m witch
)
exit /b 0

:fail
echo 启动失败
pause
exit /b 1
