#!/usr/bin/env python3
"""Задать список вопросов через RAG API и сохранить ответы в CSV (для ручной проверки, как делает учитель).

  python3 eval/ask_all.py savollar.csv --url http://localhost:8000 --key КЛЮЧ --out javoblar.csv

Во входном CSV нужен столбец с вопросом: question, Savol или savol. Вопросы идут батчами по 10.
В выходном CSV: No, вопрос, статус, ответ, источники (документ и статья).
"""
import argparse, csv, json, sys, time, urllib.error, urllib.request


def post(url, key, body):
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8",
                                          "Authorization": f"Bearer {key}"})
    for wait in (0, 5, 15, 45):
        time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503, 504):
                continue
            raise SystemExit(f"HTTP {e.code}: {e.read().decode('utf-8')[:300]}")
        except Exception:
            continue
    raise SystemExit("API не отвечает")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--key", required=True)
    ap.add_argument("--out", default="javoblar.csv")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.csv, encoding="utf-8-sig")))
    col = next((c for c in ("question", "Savol", "savol") if rows and c in rows[0]), None)
    if not col:
        raise SystemExit("В CSV нет столбца question / Savol")
    qs = [(r.get("No") or r.get("id") or str(i), r[col].strip()) for i, r in enumerate(rows, 1) if r[col].strip()]
    stamp = time.strftime("%Y%m%d%H%M%S")
    out = []
    for i in range(0, len(qs), 10):
        part = qs[i:i + 10]
        body = {"run_id": f"ask-{stamp}", "batch_id": f"ask-{stamp}-{i // 10:02d}",
                "items": [{"id": f"q{n}", "question": q} for n, q in part],
                "options": {"top_k": 5, "return_contexts": False}}
        resp = post(a.url.rstrip("/") + "/v1/rag/batch", a.key, body)
        res = {r["id"]: r for r in resp.get("results", [])}
        for n, q in part:
            r = res.get(f"q{n}", {})
            src = "; ".join(f"{c.get('doc_title', '')[:60]} {c.get('article') or ''}".strip()
                            for c in r.get("citations") or [])
            out.append({"No": n, "Savol": q, "status": r.get("status"), "answer": r.get("answer") or "",
                        "sources": src})
        print(f"{min(i + 10, len(qs))}/{len(qs)}", file=sys.stderr)
    with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["No", "Savol", "status", "answer", "sources"])
        w.writeheader(); w.writerows(out)
    na = sum(1 for r in out if r["status"] == "no_answer")
    print(f"Готово: {a.out}. Ответов: {len(out)}, «не найдено»: {na}, ошибок: "
          f"{sum(1 for r in out if r['status'] not in ('ok', 'no_answer'))}")


if __name__ == "__main__":
    main()
