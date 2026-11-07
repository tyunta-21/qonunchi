#!/usr/bin/env bash
# Выкладывает сайт в интернет на Fly.io (~$4–5 в месяц), чтобы он работал без вашего компьютера.
# Запуск (Mac/Linux), из папки qonunchi:   bash deploy_fly.sh
# Повторный запуск обновляет сайт и ключи (адрес сайта не меняется).
set -euo pipefail
cd "$(dirname "$0")"

fail() { echo; echo "ОШИБКА: $1"; echo; exit 1; }

[ -f data/laws.db ] || fail "Нет базы data/laws.db. Запускайте скрипт из той папки qonunchi, где сайт работает у вас локально."
[ -f .env ] || fail "Нет файла .env с ключами. Скопируйте .env.example в .env и впишите ключ ИИ и RAG_API_KEYS."
grep -Eq '^(OPENAI_API_KEY|ANTHROPIC_API_KEY)=.+' .env || fail "В .env не вписан ключ ИИ (OPENAI_API_KEY или ANTHROPIC_API_KEY)."
grep -Eq '^RAG_API_KEYS=.+' .env || echo "Внимание: в .env пустой RAG_API_KEYS, API /v1 для проверяющего работать не будет."

# 1. Программа flyctl
export PATH="$HOME/.fly/bin:$PATH"
if ! command -v flyctl >/dev/null 2>&1; then
  echo "Ставлю программу flyctl…"
  curl -fsSL https://fly.io/install.sh | sh || fail "Не удалось поставить flyctl. Попробуйте: brew install flyctl"
fi

# 2. Вход в аккаунт Fly.io (откроется браузер)
if ! flyctl auth whoami >/dev/null 2>&1; then
  echo "Сейчас откроется браузер: войдите в аккаунт Fly.io и вернитесь сюда."
  flyctl auth login
fi

# 3. Приложение (имя запоминается в файле .fly-app)
if [ -f .fly-app ]; then
  APP=$(cat .fly-app)
else
  APP="qonunchi-$(LC_ALL=C tr -dc 'a-z0-9' </dev/urandom | head -c 5)"
  echo "Создаю приложение $APP…"
  flyctl apps create "$APP" --org personal || fail "Не удалось создать приложение. Проверьте, что в Fly.io привязана карта (Billing)."
  echo "$APP" > .fly-app
fi

# 4. Ключи из .env -> секреты Fly.io (в код и в образ они не попадают)
echo "Передаю ключи из .env в секреты Fly.io…"
grep -E '^[A-Z][A-Z0-9_]*=.+' .env | grep -Ev '^(PORT|DB_PATH|API_DB_PATH)=' \
  | sed -e 's/\r$//' -e 's/^\([A-Z0-9_]*\)="\(.*\)"$/\1=\2/' -e "s/^\([A-Z0-9_]*\)='\(.*\)'\$/\1=\2/" \
  | flyctl secrets import --app "$APP" --stage

# 5. Сборка и запуск (первый раз база ~380 МБ загружается 5–15 минут)
echo "Загружаю сайт и базу законов. Первый раз это 5–15 минут, не закрывайте окно…"
flyctl deploy --app "$APP" --ha=false --remote-only

URL="https://$APP.fly.dev"
echo
echo "Проверяю сайт…"
for i in 1 2 3 4 5 6; do
  if curl -fsS "$URL/v1/health" >/dev/null 2>&1; then
    echo
    echo "ГОТОВО. Сайт работает: $URL"
    echo "API для проверки: $URL/v1   (ключ — из строки RAG_API_KEYS в .env)"
    exit 0
  fi
  sleep 10
done
echo "Сайт загружен, но пока не отвечает. Посмотрите логи: flyctl logs --app $APP"
