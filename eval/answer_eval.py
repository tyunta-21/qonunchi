#!/usr/bin/env python3
"""Автопроверка ОТВЕТОВ (нужен ключ ИИ в .env): прогоняет вопросы через тот же конвейер, что и API, без сервера.

  python eval/answer_eval.py eval/lex100_answers.csv [--out eval/runs/answers.csv] [--limit 20]

Что считается автоматически (без судьи-человека):
  cite      — у ответа есть ссылки [n] (если это не отказ);
  doc_ok    — хотя бы одна ссылка ведёт в правильный документ из разметки (gold);
  art_ok    — хотя бы одна ссылка ведёт в правильную статью;
  meta_ok   — на вопрос о законе целиком (overview=1) в ответе есть номер и год документа;
  refuse_ok — на вопрос-ловушку (expect=no_answer) бот отказался;
  false_no  — бот отказался, хотя ответ в базе есть (expect=answer);
  leak      — в тексте ответа служебные слова «kontekst/context».
Таблица с ответами пишется в --out, её удобно просмотреть глазами.
"""
import argparse, csv, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import rag_api, llm  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("testset"); ap.add_argument("--out", default=os.path.join("eval", "runs", "answers.csv"))
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if llm.PROVIDER == "mock":
        raise SystemExit("Нужен ключ ИИ в .env (OPENAI_API_KEY или ANTHROPIC_API_KEY): без него ответы не пишутся.")
    rows = list(csv.DictReader(open(a.testset, encoding="utf-8")))
    if a.limit:
        rows = rows[: a.limit]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    stat = dict(n=0, answered=0, cite=0, doc_ok=0, art_ok=0, gold_n=0, meta_ok=0, meta_n=0, refuse_ok=0, trap_n=0,
                false_no=0, ans_n=0, leak=0, tin=0, tout=0)
    out = csv.writer(open(a.out, "w", encoding="utf-8", newline=""))
    out.writerow(["id", "question", "no_answer", "answer", "cited", "doc_ok", "art_ok", "meta_ok"])
    t0 = time.time()
    for r in rows:
        res = rag_api.answer_item({"id": r["id"], "question": r["question"]}, {"top_k": 5, "temperature": 0, "seed": 42})
        ans, no = res.get("answer") or "", bool(res.get("no_answer"))
        u = res.get("usage") or {}
        stat["tin"] += u.get("input_tokens", 0); stat["tout"] += u.get("output_tokens", 0)
        if res.get("status") in ("error", "timeout"):
            print(r["id"], "ОШИБКА", res.get("error"), flush=True)
        cited = [(c["doc_id"], c["article"]) for c in res.get("citations") or []]
        gold = [(g.split("#")[0], g.split("#")[1]) for g in (r.get("gold") or "").split(";") if g]
        gd = {d for d, _ in gold}
        stat["n"] += 1
        doc_ok = art_ok = meta_ok = ""
        if not no:
            stat["answered"] += 1
            stat["cite"] += bool(re.search(r"\[\d+\]", ans))
        if gold and r["expect"] == "answer":
            stat["gold_n"] += 1; stat["ans_n"] += 1
            doc_ok = any(d in gd for d, _ in cited); art_ok = any((d, x) in gold for d, x in cited)
            stat["doc_ok"] += doc_ok; stat["art_ok"] += art_ok; stat["false_no"] += no
        if r.get("overview") == "1":
            stat["meta_n"] += 1
            meta_ok = (not no) and bool(re.search(r"\b(O[‘'ʻ`]?RQ-\d+|\d+-[IVX]+)", ans)) and bool(re.search(r"\b(19|20)\d\d\b", ans))
            stat["meta_ok"] += meta_ok
        if r["expect"] == "no_answer":
            stat["trap_n"] += 1; stat["refuse_ok"] += no
        stat["leak"] += bool(re.search(r"kontekst|context", ans, re.I))
        out.writerow([r["id"], r["question"], int(no), ans, " ".join(f"{d}#{x}" for d, x in cited), doc_ok, art_ok, meta_ok])
        print(r["id"], "NO" if no else "ok", ans[:90].replace("\n", " "), flush=True)
    p = lambda x, n: f"{100 * x / n:.1f}%" if n else "-"
    print(f"\nвопросов {stat['n']} за {time.time() - t0:.0f} с")
    print("ссылки [n] в ответах      ", p(stat["cite"], stat["answered"]))
    print("ссылка на верный документ ", p(stat["doc_ok"], stat["gold_n"]))
    print("ссылка на верную статью   ", p(stat["art_ok"], stat["gold_n"]))
    print("лишние отказы             ", p(stat["false_no"], stat["ans_n"]))
    print("номер+год у обзоров закона", p(stat["meta_ok"], stat["meta_n"]))
    print("отказ на ловушках         ", p(stat["refuse_ok"], stat["trap_n"]))
    print("утечки «kontekst»         ", stat["leak"])
    print(f"токены: вход {stat['tin']:,}, выход {stat['tout']:,} (модель {llm.OPENAI_MODEL})".replace(",", " "))


if __name__ == "__main__":
    main()
