@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === ThreeFast: запуск ===
where python >nul 2>nul || (echo Установите Python 3.11+ с python.org & pause & exit /b 1)
if exist venv\Scripts\python.exe (venv\Scripts\python -c "import fastapi" >nul 2>nul || rmdir /s /q venv)
if not exist venv\Scripts\python.exe (python -m venv venv)
call venv\Scripts\activate.bat
python -c "import fastapi,uvicorn,sqlalchemy" >nul 2>nul || pip install -q -r requirements.txt
python -m tools.ensure_env
python -m app.init_db
if not exist data\.seeded (python -m tools.seed_demo_orders & echo. > data\.seeded)
start "" http://127.0.0.1:8000
echo Гость: http://127.0.0.1:8000   Кухня: /staff   Суперадмин: /super   API: /docs
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
