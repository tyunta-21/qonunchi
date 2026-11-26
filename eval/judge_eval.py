#!/usr/bin/env python3
"""Оценка «верно / частично / неверно / нет ответа» по LEX_100, как в официальной таблице (нужен ключ OpenAI в .env).

  python eval/judge_eval.py eval/runs/answers_0.3.7.csv          # оценить наш прогон answer_eval.py
  python eval/judge_eval.py --calibrate Qonunchi,Dalil           # сверить судью с оценками людей

Судья (по умолчанию gpt-4.1, переменная JUDGE_MODEL) видит вопрос, примерный эталон и до трёх ответов
других ботов, которые люди оценили «верно» (eval/lex100_graded.csv, в git не хранится:
в нём ответы других команд). Балл как в таблице: верно = 1, частично = 0.5.
При --calibrate судья оценивает ответы названных ботов из той же таблицы, а ответ самого бота в образцы не берёт;
печатается совпадение с оценками людей и балл судьи рядом с официальным.
"""
import argparse, collections, csv, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import llm  # noqa: E402,F401  (читает .env)

GRADED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lex100_graded.csv")
MODEL = os.environ.get("JUDGE_MODEL", "gpt-4.1")
GRADES = ["верно", "частично", "неверно", "нет ответа"]
POINTS = {"верно": 1.0, "частично": 0.5}

PROMPT = """You grade answers of legal question-answering bots about the legislation of Uzbekistan, the way human
graders did for the LEX_100 table. Grades:
- "верно": answers every part of the question correctly; the key facts (numbers, terms, conditions, which law)
  agree with the reference; small extra details are fine.
- "частично": correct as far as it goes, but misses a part of the question or a key fact/condition that the good
  answers give, or is too vague to be fully useful.
- "неверно": states a wrong key fact, wrong number or wrong law, or answers a different question.
- "нет ответа": a refusal ("not found", "cannot answer") or no substantive answer.
If the good reference answers are themselves refusals (the question has no answer in the law base, or asks for
something the bot must not do), then a clear refusal is "верно" and an invented answer is "неверно".
The approximate reference may be incomplete or marked ⚠ (unverified); trust the good answers more when they agree
with each other. Do not reward length: a short answer that has every key fact is "верно".
Reply with JSON only: {"grade": "<one of the four>", "missing": "<what is missing or wrong, in a few words>"}"""


def load_graded():
    by_q = collections.defaultdict(list)
    for r in csv.DictReader(open(GRADED, encoding="utf-8")):
        by_q[r["id"]].append(r)
    return by_q


def references(rows, skip_bot=None, n=3):
    good = [r for r in rows if r["grade"] == "верно" and r["bot"] != skip_bot and r["answer"].strip()]
    good.sort(key=lambda r: (r["bot"] != "LexRAG-Haiku", r["bot"]))
    return [r["answer"][:1500] for r in good[:n]]


def judge(question, etalon, refs, answer):
    from openai import OpenAI
    msg = [f"Question: {question}", f"Approximate reference: {etalon or '-'}"]
    msg += [f"Good answer {i} (graded верно by humans):\n{a}" for i, a in enumerate(refs, 1)] or ["Good answers: none"]
    msg.append(f"ANSWER TO GRADE:\n{(answer or '').strip()[:3000] or '(empty)'}")
    for attempt in range(4):
        try:
            r = OpenAI().chat.completions.create(
                model=MODEL, temperature=0, seed=42, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": "\n\n".join(msg)}])
            d = json.loads(r.choices[0].message.content or "{}")
            g = d.get("grade", "").strip().lower()
            return (g if g in GRADES else "неверно"), d.get("missing", "")
        except Exception as e:  # сеть, лимиты
            if attempt == 3:
                return "error", str(e)[:200]
            time.sleep(2 * (attempt + 1))


def score(grades):
    """Балл по оценённым ответам; сбои вызова судьи («error») не считаются ни плюсом, ни минусом."""
    return sum(POINTS.get(g, 0.0) for g in grades if g != "error")


def run(items, workers):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda it: judge(*it), items))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("answers", nargs="?", help="CSV из eval/answer_eval.py")
    ap.add_argument("--calibrate", help="боты из таблицы через запятую, например Qonunchi,Dalil")
    ap.add_argument("--out", default="")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Нужен OPENAI_API_KEY в .env")
    if not os.path.exists(GRADED):
        raise SystemExit(f"Нет файла {GRADED}: его кладут рядом вручную (в git его нет)")
    by_q = load_graded()
    t0 = time.time()

    if a.calibrate:
        for bot in a.calibrate.split(","):
            rows = [r for qid in sorted(by_q, key=int) for r in by_q[qid] if r["bot"] == bot]
            if not rows:
                print(f"бот {bot!r} не найден в {GRADED}"); continue
            res = run([(r["question"], r["etalon"], references(by_q[r["id"]], skip_bot=bot), r["answer"])
                       for r in rows], a.workers)
            pairs = [(r["grade"], g) for r, (g, _) in zip(rows, res) if g != "error"]
            if len(pairs) < len(rows):
                print(f"{bot}: судья не ответил на {len(rows) - len(pairs)} из {len(rows)}, они не считаются")
            rows = [r for r, (g, _) in zip(rows, res) if g != "error"]
            human = [h for h, _ in pairs]; mine = [m for _, m in pairs]
            agree = sum(h == m for h, m in zip(human, mine))
            near = sum(h == m or {h, m} <= {"верно", "частично"} for h, m in zip(human, mine))
            print(f"\n{bot}: совпадение {agree}/{len(rows)}, верно/частично спутаны ещё в {near - agree}")
            print(f"  балл людей {score(human):.1f}, балл судьи {score(mine):.1f}")
            cm = collections.Counter(zip(human, mine))
            print("  люди \\ судья  " + "  ".join(f"{g[:8]:>8}" for g in GRADES))
            for h in GRADES:
                print(f"  {h:13} " + "  ".join(f"{cm[(h, m)]:8}" for m in GRADES))
        print(f"\n{time.time() - t0:.0f} с, модель судьи {MODEL}")
        return

    if not a.answers:
        ap.error("укажите CSV с ответами или --calibrate")
    ours = list(csv.DictReader(open(a.answers, encoding="utf-8")))
    items = []
    for r in ours:
        rows = by_q.get(r["id"], [])
        ans = "(refusal) " + r["answer"] if r.get("no_answer") == "1" else r["answer"]
        items.append((r["question"], rows[0]["etalon"] if rows else "", references(rows, skip_bot="Qonunchi"), ans))
    res = run(items, a.workers)
    out = a.out or a.answers.replace(".csv", "_judged.csv")
    w = csv.writer(open(out, "w", encoding="utf-8", newline=""))
    w.writerow(["id", "question", "grade", "missing", "old_grade", "answer"])
    old = {qid: next((x["grade"] for x in rows if x["bot"] == "Qonunchi"), "") for qid, rows in by_q.items()}
    for r, (g, miss) in zip(ours, res):
        w.writerow([r["id"], r["question"], g, miss, old.get(r["id"], ""), r["answer"]])
    c = collections.Counter(g for g, _ in res)
    oc = collections.Counter(old.get(r["id"], "") for r in ours)
    print(f"вопросов {len(ours)} за {time.time() - t0:.0f} с, модель судьи {MODEL}")
    for g in GRADES + (["error"] if c["error"] else []):
        print(f"{g:12} {c[g]:4}   (в официальной таблице было {oc[g]})")
    ok = [(r, g) for r, (g, _) in zip(ours, res) if g != "error"]
    print(f"балл {score([g for _, g in ok]):.1f} из {len(ok)}   (было {score([old.get(r['id'], '') for r, _ in ok]):.1f} "
          f"на тех же вопросах)")
    print(f"таблица по вопросам: {out}")


if __name__ == "__main__":
    main()
