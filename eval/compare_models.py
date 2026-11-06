#!/usr/bin/env python3
"""Сравнение моделей: одни и те же вопросы задаются нескольким моделям, ответы сохраняются рядом.

  python eval/compare_models.py eval/sample_testset.csv --models claude-haiku-5-5 claude-sonnet-5-5 gpt-4.1-mini

Модели с «claude» в названии идут через ANTHROPIC_API_KEY, остальные через OPENAI_API_KEY (ключи из .env).
Работает без запущенного сайта: берёт базу data/laws.db и тот же код поиска и ответа, что и RAG API.
Результат: eval/compare/<дата>.csv (для Excel) и .md (читать глазами). Цена считается по таблице PRICES ниже,
сверяйте её с сайтами провайдеров.
"""
import argparse, csv, datetime, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import llm, rag_api  # noqa: E402

# $ за 1 млн токенов: (вход, выход). Модели нет в таблице — цена не считается.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "gpt-4.1-mini": (0.40, 1.60),
}


def use_model(model):
    if "claude" in model:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit(f"{model}: впишите ANTHROPIC_API_KEY в .env")
        llm.PROVIDER, llm.CLAUDE_MODEL = "claude", model
    else:
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit(f"{model}: впишите OPENAI_API_KEY в .env")
        llm.PROVIDER, llm.OPENAI_MODEL, llm.OPENAI_KW_MODEL = "openai", model, model


def cost(model, usage):
    p = PRICES.get(model)
    if not p:
        return None
    return (usage["input_tokens"] * p[0] + usage["output_tokens"] * p[1]) / 1e6


def art(a):
    return (a or "").replace(" ", "").lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("testset", help="CSV как eval/sample_testset.csv (нужны колонки id, question)")
    ap.add_argument("--models", nargs="+", default=["claude-haiku-5-5", "gpt-4.1-mini"])
    ap.add_argument("--limit", type=int, default=0, help="взять только первые N вопросов")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.testset, encoding="utf-8")))
    if a.limit:
        rows = rows[:a.limit]

    results = {}  # (model, id) -> res
    for model in a.models:
        use_model(model)
        print(f"\n== {model}")
        for r in rows:
            try:
                res = rag_api.answer_item({"id": r["id"], "question": r["question"]}, {"top_k": 5})
            except Exception as e:
                res = {"status": "error", "answer": None, "error": {"message": repr(e)[:300]},
                       "citations": [], "usage": {"input_tokens": 0, "output_tokens": 0}}
            results[(model, r["id"])] = res
            print(f"  {r['id']}: {res['status']}")
            time.sleep(0.2)

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out_dir = os.path.join(os.path.dirname(__file__), "compare"); os.makedirs(out_dir, exist_ok=True)
    csv_path, md_path = os.path.join(out_dir, stamp + ".csv"), os.path.join(out_dir, stamp + ".md")

    summary = {m: {"ok": 0, "hit": 0, "has_exp": 0, "cost": 0.0, "ms": []} for m in a.models}
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f, open(md_path, "w", encoding="utf-8") as md:
        w = csv.writer(f)
        w.writerow(["id", "question", "expected_answer", "expected_article", "model", "status", "answer",
                    "cited_articles", "article_found", "input_tokens", "output_tokens", "cost_usd", "time_ms"])
        md.write(f"# Сравнение моделей {stamp}\n\n")
        for r in rows:
            md.write(f"## {r['id']}. {r['question']}\n\nОжидается: {r.get('expected_answer', '')} "
                     f"({r.get('expected_article', '')})\n\n")
            for model in a.models:
                res = results[(model, r["id"])]
                s = summary[model]
                cited = [c.get("article") for c in res.get("citations") or []]
                exp = art(r.get("expected_article"))
                found = "" if not exp else ("да" if any(art(c) == exp for c in cited) else "нет")
                c = cost(model, res["usage"])
                ms = (res.get("timing") or {}).get("total_ms")
                s["ok"] += res["status"] in ("ok", "no_answer")
                s["has_exp"] += bool(exp); s["hit"] += found == "да"
                s["cost"] += c or 0
                if ms:
                    s["ms"].append(ms)
                answer = res.get("answer") or (res.get("error") or {}).get("message", "")
                w.writerow([r["id"], r["question"], r.get("expected_answer", ""), r.get("expected_article", ""),
                            model, res["status"], answer, "; ".join(x or "" for x in cited), found,
                            res["usage"]["input_tokens"], res["usage"]["output_tokens"],
                            "" if c is None else f"{c:.5f}", ms or ""])
                md.write(f"**{model}** ({res['status']}, статья найдена: {found or '—'}, "
                         f"{'' if c is None else f'${c:.4f}, '}{ms or '—'} мс)\n\n{answer}\n\n")
        md.write("## Итог\n\n| Модель | Без ошибок | Нужная статья | Цена всего | Цена за 1000 вопросов | Время (медиана) |\n"
                 "|---|---|---|---|---|---|\n")
        print("\nИтог:")
        for m, s in summary.items():
            n = len(rows)
            med = sorted(s["ms"])[len(s["ms"]) // 2] if s["ms"] else 0
            line = (f"| {m} | {s['ok']}/{n} | {s['hit']}/{s['has_exp']} | ${s['cost']:.4f} | "
                    f"${s['cost'] / max(n, 1) * 1000:.2f} | {med} мс |")
            md.write(line + "\n"); print(line)
    print(f"\nОтветы: {csv_path}\n        {md_path}")


if __name__ == "__main__":
    main()
