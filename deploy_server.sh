#!/usr/bin/env bash
# Установка и обновление Qonunchi на сервере Ubuntu (AWS и т.п.). Одна команда на сервере:
#   sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/tyunta-21/qonunchi/main/deploy_server.sh)"
# Повторный запуск обновляет код до ветки main и перезапускает сайт. Ключи спрашиваются только в первый раз
# и хранятся в /etc/qonunchi.env (в образ не попадают).
set -euo pipefail
BRANCH=${BRANCH:-main}
DIR=/opt/qonunchi
fail() { echo; echo "ОШИБКА: $1"; echo; exit 1; }
[ "$(id -u)" = 0 ] || fail "Запустите через sudo."

echo "1/5 Docker и git…"
export DEBIAN_FRONTEND=noninteractive
command -v docker >/dev/null || { apt-get update -qq && apt-get install -y -qq docker.io git >/dev/null; }
command -v git >/dev/null || apt-get install -y -qq git >/dev/null
systemctl enable --now docker >/dev/null 2>&1 || true
# swap 2 ГБ: на сервере с 1 ГБ памяти сборка без него может упасть
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile \
    && echo '/swapfile none swap sw 0 0' >> /etc/fstab || true
fi

echo "2/5 Код (ветка $BRANCH)…"
if [ -d "$DIR/.git" ]; then
  git config --global --add safe.directory "$DIR" || true
  git -C "$DIR" fetch -q origin "$BRANCH" && git -C "$DIR" checkout -q -f -B "$BRANCH" "origin/$BRANCH"
else
  git clone -q -b "$BRANCH" https://github.com/tyunta-21/qonunchi "$DIR"
fi
grep -m1 PIPELINE_VERSION "$DIR/app/rag_api.py" || true

echo "3/5 Ключи…"
ENVF=/etc/qonunchi.env
if [ ! -s "$ENVF" ]; then
  read -r -p "  Вставьте OPENAI_API_KEY (sk-…) и нажмите Enter: " OKEY
  read -r -p "  Вставьте RAG_API_KEYS (ключ для проверяющего из .env) и нажмите Enter: " RKEY
  [ -n "$OKEY" ] || fail "Пустой OPENAI_API_KEY."
  umask 077
  printf 'AI_PROVIDER=openai\nOPENAI_API_KEY=%s\nOPENAI_MODEL=gpt-4.1-mini\nRAG_API_KEYS=%s\nCHAT_LIMIT_PER_HOUR=30\nRAG_WORKERS=3\n' "$OKEY" "$RKEY" > "$ENVF"
fi

echo "4/5 Собираю образ: база законов ~1 ГБ и модель поиска, 5–15 минут. Старый сайт пока работает…"
docker build -q -t qonunchi:new -f "$DIR/Dockerfile.server" "$DIR" >/dev/null || fail "Сборка не удалась, старый сайт продолжает работать."

echo "5/5 Перезапускаю…"
docker tag qonunchi:latest qonunchi:prev >/dev/null 2>&1 || true
docker tag qonunchi:new qonunchi:latest
docker rm -f qonunchi >/dev/null 2>&1 || true
docker run -d --name qonunchi --restart=always -p 80:10000 --env-file "$ENVF" qonunchi:latest >/dev/null

IP=$(curl -fsS -m 5 https://checkip.amazonaws.com 2>/dev/null || hostname -I | awk '{print $1}')
for i in $(seq 1 60); do curl -fsS -m 3 http://localhost/v1/health >/dev/null 2>&1 && break; sleep 2; done
echo
if curl -fsS -m 3 http://localhost/v1/health >/dev/null 2>&1; then
  echo "ГОТОВО. Сайт работает: http://$IP"
  docker image prune -f >/dev/null 2>&1 || true
else
  echo "Сайт запущен, но пока не отвечает. Логи: sudo docker logs qonunchi"
  echo "Вернуть прошлую версию: sudo docker rm -f qonunchi && sudo docker run -d --name qonunchi --restart=always -p 80:10000 --env-file $ENVF qonunchi:prev"
fi
