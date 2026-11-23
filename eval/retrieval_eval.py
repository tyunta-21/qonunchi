#!/usr/bin/env python3
"""Офлайн-проверка поиска (без ИИ и без API): Hit@k, Recall@k, Precision@k, MRR.

  python eval/retrieval_eval.py eval/lex100_retrieval.csv [--k 5]

CSV: id, question, gold («lex:<номер>#<статья>;...»), overview (1 = вопрос о законе целиком: засчитывается любая
статья нужного документа). Переписывание запроса ИИ здесь выключено, поэтому цифры ниже, чем у живого API,
но изменения поиска сравниваются честно: тот же вопрос, та же база.
"""
import argparse, csv, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["AI_PROVIDER"] = "mock"
from app import rag_api  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("testset"); ap.add_argument("--k", type=int, default=5); ap.add_argument("--lang", default="uz")
    ap.add_argument("-v", action="store_true", help="печатать промахи")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.testset, encoding="utf-8")))
    hit = rec = prec = mrr = doc_hit = 0.0
    for r in rows:
        gold = [(int(g.split("#")[0].split(":")[1]), g.split("#")[1]) for g in r["gold"].split(";") if g]
        gs, gd, ov = set(gold), {k for k, _ in gold}, r.get("overview") == "1"
        ctx, _ = rag_api.retrieve(rag_api.expand(r["question"]), a.lang, None, max(a.k, rag_api.GEN_CONTEXTS))
        top = [(c[2]["key"], c[2]["article"]) for c in ctx][: a.k]
        rel = [(t in gs) or (ov and t[0] in gd) for t in top]
        hit += any(rel); doc_hit += any(t[0] in gd for t in top)
        rec += 1.0 if (ov and any(rel)) else len(gs & set(top)) / len(gs)
        prec += sum(rel) / len(top) if top else 0
        mrr += next((1 / (i + 1) for i, x in enumerate(rel) if x), 0)
        if a.v and not any(rel):
            print("MISS", r["id"], r["question"][:70], "->", top[:3])
    n = len(rows)
    print(f"n={n}  Hit@{a.k}={100 * hit / n:.1f}  DocHit@{a.k}={100 * doc_hit / n:.1f}  "
          f"Recall@{a.k}={100 * rec / n:.1f}  Precision@{a.k}={100 * prec / n:.1f}  MRR={mrr / n:.3f}")


if __name__ == "__main__":
    main()
