#!/usr/bin/env bash
# Запуск ThreeFast одной командой: ./start.sh
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
if [ -d venv ] && [ ! -x venv/bin/python ]; then rm -rf venv; fi   # venv с другой ОС
[ -d venv ] || $PY -m venv venv
. venv/bin/activate
python -c "import fastapi,uvicorn,sqlalchemy" 2>/dev/null || pip install -q -r requirements.txt
python -m tools.ensure_env
python -m app.init_db
mkdir -p data
if [ ! -f data/.seeded ]; then python -m tools.seed_demo_orders || true; touch data/.seeded; fi
PORT=${PORT:-8000}
echo "Гость: http://127.0.0.1:$PORT   Кухня: /staff   Суперадмин: /super   API: /docs"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
