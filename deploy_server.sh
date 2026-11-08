#!/usr/bin/env bash
# Запуск Qonunchi на любом сервере Ubuntu (AWS, Oracle, Hetzner…). Одна команда на сервере:
#   sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/tyunta-21/qonunchi/claude/project-thread-za60g1/deploy_server.sh)"
# Повторный запуск обновляет код и перезапускает сайт (ключи спрашивает только первый раз).
set -euo pipefail
BRANCH=${BRANCH:-claude/project-thread-za60g1}
DIR=/opt/qonunchi
fail() { echo; echo "ОШИБКА: $1"; echo; exit 1; }
[ "$(id -u)" = 0 ] || fail "Запустите через sudo."

echo "1/5 Ставлю Docker и git…"
export DEBIAN_FRONTEND=noninteractive
command -v docker >/dev/null || { apt-get update -qq && apt-get install -y -qq docker.io git >/dev/null; }
command -v git >/dev/null || apt-get install -y -qq git >/dev/null
systemctl enable --now docker >/dev/null 2>&1 || true

# swap 2 ГБ: на маленьких серверах (1 ГБ памяти) сборка без него может упасть
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile \
    && echo '/swapfile none swap sw 0 0' >> /etc/fstab || true
fi

echo "2/5 Скачиваю код…"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH" && git -C "$DIR" checkout -q -B "$BRANCH" "origin/$BRANCH"
else
  git clone -q -b "$BRANCH" https://github.com/tyunta-21/qonunchi "$DIR"
fi

echo "3/5 Ключи…"
ENVF=/etc/qonunchi.env
if [ ! -s "$ENVF" ]; then
  read -r -p "  Вставьте OPENAI_API_KEY (sk-…) и нажмите Enter: " OKEY
  read -r -p "  Вставьте RAG_API_KEYS (ключ для учителя из .env) и нажмите Enter: " RKEY
  [ -n "$OKEY" ] || fail "Пустой OPENAI_API_KEY."
  umask 077
  printf 'AI_PROVIDER=openai\nOPENAI_API_KEY=%s\nOPENAI_MODEL=gpt-4.1-mini\nRAG_API_KEYS=%s\nCHAT_LIMIT_PER_HOUR=30\n' "$OKEY" "$RKEY" > "$ENVF"
fi

echo "4/5 Собираю сайт и скачиваю базу законов (~1 ГБ, 5–10 минут)…"
docker build -q -t qonunchi -f "$DIR/Dockerfile.render" "$DIR" >/dev/null

echo "5/5 Запускаю…"
docker rm -f qonunchi >/dev/null 2>&1 || true
docker run -d --name qonunchi --restart=always -p 80:10000 --env-file "$ENVF" qonunchi >/dev/null

IP=$(curl -fsS -m 5 https://checkip.amazonaws.com 2>/dev/null || hostname -I | awk '{print $1}')
for i in $(seq 1 30); do curl -fsS -m 3 http://localhost/v1/health >/dev/null 2>&1 && break; sleep 2; done
echo
if curl -fsS -m 3 http://localhost/v1/health >/dev/null 2>&1; then
  echo "ГОТОВО. Сайт работает: http://$IP"
else
  echo "Сайт запущен, но пока не отвечает. Логи: sudo docker logs qonunchi"
fi
