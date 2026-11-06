#!/usr/bin/env python3
"""Прогон тестового набора через RAG API и подсчёт метрик из ТЗ (раздел 6).

  python eval/run_eval.py eval/sample_testset.csv --url http://localhost:8000 --key ВАШ_ТЕСТОВЫЙ_КЛЮЧ

Ответы сохраняются в eval/runs/<run_id>/bNN.json, метрики печатаются и пишутся в metrics.json.
Считаются автоматически: Hit@5 (документ и статья), MRR, no-answer, выдуманные ссылки, ссылки на утратившие силу
акты, доля ошибок, латентность p50/p95. Correctness и faithfulness нужно оценивать вручную или LLM-судьёй.
"""
import argparse, csv, datetime, json, os, statistics, sys, time, urllib.request


def post(url, key, body):
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8",
                                          "Authorization": f"Bearer {key}"})
    for wait in (0, 5, 15, 45):
        time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503, 504):
                continue
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            continue
    raise SystemExit("API не отвечает")


def get(url, key):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def art(a):
    return (a or "").replace(" ", "").lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("testset"); ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--key", default=os.environ.get("RAG_TEST_KEY", "")); ap.add_argument("--run-id")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.testset, encoding="utf-8")))
    run_id = a.run_id or "eval-" + datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out_dir = os.path.join(os.path.dirname(__file__), "runs", run_id); os.makedirs(out_dir, exist_ok=True)
    batches = {}
    for r in rows:
        batches.setdefault(r["batch"], []).append(r)
    results = {}
    for i, (b, items) in enumerate(sorted(batches.items()), 1):
        body = {"run_id": run_id, "batch_id": f"{run_id}-{b}", "batch_index": i, "total_batches": len(batches),
                "options": {"top_k": 5, "return_contexts": True, "return_debug": True, "temperature": 0, "seed": 42},
                "items": [{"id": r["id"], "question": r["question"]} for r in items]}
        code, resp = post(a.url + "/v1/rag/batch", a.key, body)
        while code == 202:
            time.sleep(5); resp = get(f"{a.url}/v1/rag/batch/{body['batch_id']}", a.key)
            code = 200 if resp.get("status") == "completed" else 202
        if code != 200:
            raise SystemExit(f"batch {b}: HTTP {code} {resp}")
        json.dump(resp, open(os.path.join(out_dir, f"{b}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        for res in resp["results"]:
            results[res["id"]] = res
        print(f"{b}: {resp['summary']}  {resp['timing']['total_ms']} ms")

    hit_doc = hit_art = rr = n = 0; na_ok = na_total = 0; fake = stale = errors = 0; lat = []; report = []
    for r in rows:
        res = results.get(r["id"], {})
        ctx = res.get("contexts") or []
        ctx_ids = {c["chunk_id"] for c in ctx}
        for c in res.get("citations") or []:
            fake += c["chunk_id"] not in ctx_ids
            stale += c.get("doc_status") != "amalda"
        errors += res.get("status") in ("error", "timeout")
        if res.get("timing"):
            lat.append(res["timing"]["total_ms"])
        answerable = r["answerable"].strip().lower() == "true"
        if not answerable:
            na_total += 1; na_ok += bool(res.get("no_answer"))
            report.append((r["id"], "no_answer" if res.get("no_answer") else "ОТВЕТИЛ (ошибка)", "")); continue
        n += 1
        top5 = ctx[:5]
        hd = any(c["doc_id"] == r["expected_doc_id"] for c in top5)
        rank = next((c["rank"] for c in ctx if c["doc_id"] == r["expected_doc_id"]
                     and (not r["expected_article"] or art(c["article"]) == art(r["expected_article"]))), None)
        ha = rank is not None and rank <= 5 if r["expected_article"] else hd
        hit_doc += hd; hit_art += ha; rr += 1 / rank if rank else 0
        report.append((r["id"], f"doc {'+' if hd else '-'} art {'+' if ha else '-'} rank {rank}", (res.get("answer") or "")[:120]))
    m = {"run_id": run_id, "questions": len(rows),
         "hit5_doc": round(hit_doc / n, 3) if n else None, "hit5_article": round(hit_art / n, 3) if n else None,
         "mrr": round(rr / n, 3) if n else None, "no_answer_accuracy": f"{na_ok}/{na_total}",
         "fabricated_citations": fake, "stale_citations": stale, "error_rate": round(errors / len(rows), 3),
         "latency_p50_ms": int(statistics.median(lat)) if lat else None,
         "latency_p95_ms": int(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)]) if lat else None}
    for line in report:
        print(*line, sep="  |  ")
    print(json.dumps(m, ensure_ascii=False, indent=1))
    json.dump(m, open(os.path.join(out_dir, "metrics.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
