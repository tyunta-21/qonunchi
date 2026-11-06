#!/usr/bin/env bash
# Запуск сайта на Mac/Linux:  bash start.sh   затем откройте http://localhost:8000
set -e
cd "$(dirname "$0")"

fail() { echo; echo "ОШИБКА: $1"; echo; exit 1; }
ok_ver() { "$1" -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" 2>/dev/null; }

# Ищем подходящий Python 3.10–3.13 (на самых новых версиях часть библиотек ещё не ставится)
PY=""
for c in python3.13 python3.12 python3.11 python3.10 \
         /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.13 /usr/local/bin/python3.12 \
         /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 python3; do
  if command -v "$c" >/dev/null 2>&1 && ok_ver "$c"; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  fail "Не найден Python 3.10–3.13 (у вас: $(python3 --version 2>&1)).
Установите Python 3.13 с https://www.python.org/downloads/ (файл для macOS, .pkg)
или командой:  brew install python@3.13
и запустите  bash start.sh  ещё раз."
fi
echo "Использую $PY ($("$PY" --version))"

# Если .venv создана неподходящей версией Python или сломана, пересоздаём её
if [ -d .venv ] && ! ok_ver .venv/bin/python; then
  echo "Пересоздаю папку .venv…"; rm -rf .venv
fi
if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv || fail "Не получилось создать папку .venv. Удалите её и запустите снова."
fi

echo "Ставлю библиотеки (первый раз 1–2 минуты)…"
.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt \
  || fail "Библиотеки не установились. Проверьте интернет и запустите снова."

if [ ! -f data/laws.db ]; then
  [ -d ../lexuz/data ] || fail "Нет базы data/laws.db и нет папки ../lexuz/data, из которой её можно собрать."
  .venv/bin/python build_db.py ../lexuz/data data/laws.db
fi

echo
echo "Сайт запущен: откройте http://localhost:8000   (остановить: Ctrl+C)"
echo
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
