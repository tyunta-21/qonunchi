#!/usr/bin/env bash
# Дробит длинные постановления в уже готовой базе на пункты. Запуск:  bash update_chunking.sh
set -e
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || { echo "Сначала один раз запустите  bash start.sh  (он создаст .venv), потом этот файл."; exit 1; }
[ -f data/laws.db ] || { echo "Нет базы data/laws.db"; exit 1; }
echo "Остановите сайт (Ctrl+C в его окне), если он запущен. Начинаю через 3 секунды…"; sleep 3
"$PY" rechunk_db.py data/laws.db
echo "Готово. Запустите сайт снова:  bash start.sh"
