FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY build_db.py .
COPY data/laws.db data/laws.db
ENV PORT=8000
# --proxy-headers: за прокси хостинга (Fly.io, Render и т.п.) берём настоящий IP посетителя
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
