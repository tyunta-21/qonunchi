#!/usr/bin/env bash
# Выкладывает сайт в Google Cloud Run. При нагрузке учебного проекта это укладывается в бесплатный лимит
# (нужна карта для аккаунта Google Cloud). Запуск из папки qonunchi:   bash deploy_cloudrun.sh
# Повторный запуск обновляет сайт (адрес не меняется).
set -euo pipefail
cd "$(dirname "$0")"
fail() { echo; echo "ОШИБКА: $1"; echo; exit 1; }

[ -f data/laws.db ] || fail "Нет базы data/laws.db. Запускайте из папки qonunchi, где сайт работает локально."
[ -f .env ] || fail "Нет файла .env с ключами."
grep -Eq '^(OPENAI_API_KEY|ANTHROPIC_API_KEY)=.+' .env || fail "В .env не вписан ключ ИИ."
command -v gcloud >/dev/null 2>&1 || fail "Нет программы gcloud. Поставьте:  brew install --cask google-cloud-sdk
затем закройте и откройте Терминал и запустите скрипт снова."

# 1. Вход
if [ -z "$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null)" ]; then
  echo "Сейчас откроется браузер: войдите в Google-аккаунт."
  gcloud auth login
fi

# 2. Проект (имя запоминается в .gcp-project)
if [ -f .gcp-project ]; then
  PROJECT=$(cat .gcp-project)
else
  PROJECT="qonunchi-$(LC_ALL=C tr -dc 'a-z0-9' </dev/urandom | head -c 6)"
  echo "Создаю проект $PROJECT…"
  gcloud projects create "$PROJECT" --name="Qonunchi" || fail "Не удалось создать проект."
  BILLING=$(gcloud billing accounts list --filter=open=true --format='value(name)' | head -n1)
  [ -n "$BILLING" ] || fail "Нет платёжного аккаунта. Откройте https://console.cloud.google.com/billing, привяжите карту и запустите скрипт снова."
  gcloud billing projects link "$PROJECT" --billing-account="$BILLING" >/dev/null
  echo "$PROJECT" > .gcp-project
fi
gcloud config set project "$PROJECT" >/dev/null
echo "Включаю нужные сервисы (1–2 минуты)…"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

# 3. Ключи из .env -> настройки Cloud Run (во временный файл, который сразу удаляется)
ENVF=$(mktemp)
trap 'rm -f "$ENVF"' EXIT
grep -E '^[A-Z][A-Z0-9_]*=.+' .env | grep -Ev '^(PORT|DB_PATH|API_DB_PATH)=' \
  | sed -e 's/\r$//' -e 's/^\([A-Z0-9_]*\)="\(.*\)"$/\1=\2/' -e "s/^\([A-Z0-9_]*\)='\(.*\)'\$/\1=\2/" \
  | while IFS='=' read -r k v; do v=${v//\\/\\\\}; v=${v//\"/\\\"}; printf '%s: "%s"\n' "$k" "$v"; done > "$ENVF"

# 4. Сборка и запуск. max-instances 1: один экземпляр, чтобы батчи /v1 не терялись и счёт не рос.
echo "Загружаю сайт и базу (~380 МБ). Первый раз 10–20 минут, не закрывайте окно…"
gcloud run deploy qonunchi --source . --region europe-west1 --allow-unauthenticated \
  --memory 1Gi --cpu 1 --min-instances 0 --max-instances 1 --timeout 300 \
  --env-vars-file "$ENVF" --quiet

URL=$(gcloud run services describe qonunchi --region europe-west1 --format='value(status.url)')
echo
curl -fsS "$URL/v1/health" >/dev/null 2>&1 && echo "ГОТОВО. Сайт работает: $URL" || echo "Сайт загружен: $URL (первый ответ может занять ~10 секунд)"
echo "API для проверки: $URL/v1   (ключ — из строки RAG_API_KEYS в .env)"
