@echo off
chcp 65001 >nul
REM Zapusk saita na Windows: dvazhdy shelknite po etomu failu, zatem otkroite http://localhost:8000
cd /d "%~dp0"
set PY=
for %%v in (3.13 3.12 3.11 3.10) do (if not defined PY (py -%%v -c "1" >nul 2>&1 && set PY=py -%%v))
if not defined PY (python -c "import sys;sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)" >nul 2>&1 && set PY=python)
if not defined PY (echo OSHIBKA: nuzhen Python 3.10-3.13 s https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv\Scripts\python.exe (%PY% -m venv .venv || (echo OSHIBKA: ne sozdalas papka .venv & pause & exit /b 1))
.venv\Scripts\python -m pip install -q -r requirements.txt || (echo OSHIBKA: biblioteki ne ustanovilis & pause & exit /b 1)
if not exist data\laws.db .venv\Scripts\python build_db.py ..\lexuz\data data\laws.db
echo Sait zapushen: http://localhost:8000
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
