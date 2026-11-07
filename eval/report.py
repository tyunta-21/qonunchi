#!/usr/bin/env python3
"""Красивый HTML-отчёт по прогону run_eval.py.

  python3 eval/report.py eval/testset_100.csv            # последний прогон
  python3 eval/report.py eval/testset_100.csv RUN_ID     # конкретный прогон

Создаёт eval/runs/<run_id>/report.html и открывает его в браузере.
"""
import csv, glob, html, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGETS = [  # ключ, название, цель, «больше лучше»
    ("hit5_doc", "Hujjat topildi (Hit@5)", 0.9, True),
    ("hit5_article", "Modda topildi (Hit@5)", 0.8, True),
    ("mrr", "MRR", 0.7, True),
    ("no_answer_accuracy", "Javobsiz savollar", 0.9, True),
    ("latency_p50_ms", "Vaqt p50, ms", 5000, False),
    ("latency_p95_ms", "Vaqt p95, ms", 12000, False),
    ("error_rate", "Xatolar ulushi", 0.02, False),
    ("fabricated_citations", "Toʻqilgan manbalar", 0, False),
    ("stale_citations", "Eskirgan manbalar", 0, False),
]
CAT = {"faktik": "Faktik", "raqamlar": "Raqamlar", "kop_manba": "Bir nechta modda", "ozgargan": "Oʻzgargan norma",
       "rus_kirill": "Rus / kirill", "javobsiz": "Javobsiz", "noaniq": "Noaniq", "rus": "Rus"}


def art(a):
    return (a or "").split("-")[0].strip().lower()


def main():
    testset = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "testset_100.csv")
    runs = sorted(glob.glob(os.path.join(HERE, "runs", "*", "metrics.json")), key=os.path.getmtime)
    if len(sys.argv) > 2:
        run_dir = os.path.join(HERE, "runs", sys.argv[2])
    elif runs:
        run_dir = os.path.dirname(runs[-1])
    else:
        raise SystemExit("Прогонов нет: сначала запустите eval/run_eval.py")
    m = json.load(open(os.path.join(run_dir, "metrics.json"), encoding="utf-8"))
    rows = list(csv.DictReader(open(testset, encoding="utf-8")))
    res = {}
    system = {}
    for f in sorted(glob.glob(os.path.join(run_dir, "b*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        system = d.get("system") or system
        for r in d.get("results", []):
            res[r["id"]] = r

    cards = []
    for key, name, goal, higher in TARGETS:
        v = m.get(key)
        if key == "no_answer_accuracy" and isinstance(v, str) and "/" in v:
            a, b = v.split("/")
            shown, num = v, (int(a) / int(b) if int(b) else None)
        else:
            shown, num = v, v
        ok = None if num is None else (num >= goal if higher else num <= goal)
        if isinstance(num, float) and key not in ("error_rate",) and num <= 1 and key != "mrr":
            shown = f"{num * 100:.0f}%"
        if key == "error_rate" and isinstance(num, (int, float)):
            shown = f"{num * 100:.1f}%"
        gtxt = (f"≥ {goal * 100:.0f}%" if goal <= 1 and key not in ("mrr", "error_rate") and higher else
                f"≥ {goal}" if higher else (f"≤ {goal * 100:.0f}%" if key == "error_rate" else f"≤ {goal}"))
        cls = "na" if ok is None else ("ok" if ok else "bad")
        cards.append(f'<div class="card {cls}"><div class="v">{html.escape(str(shown))}</div>'
                     f'<div class="n">{name}</div><div class="g">maqsad {gtxt}</div></div>')
    passed = sum(c.count('class="card ok"') for c in cards)

    trs = []
    for r in rows:
        x = res.get(r["id"], {})
        ctx = x.get("contexts") or []
        if r.get("answerable") == "false":
            good = bool(x.get("no_answer"))
            mark = "✓" if good else "✗"
            where = "no_answer" if good else "javob toʻqidi"
        else:
            rank = next((c["rank"] for c in ctx if c["doc_id"] == r["expected_doc_id"]
                         and art(c.get("article")) == art(r["expected_article"])), None)
            good = rank is not None and rank <= 5
            mark = "✓" if good else ("~" if any(c["doc_id"] == r["expected_doc_id"] for c in ctx[:5]) else "✗")
            where = f"{rank}-oʻrin" if rank else "topilmadi"
        cites = ", ".join(sorted({c.get("article") or "" for c in x.get("citations") or []})) or "—"
        ms = (x.get("timing") or {}).get("total_ms")
        st = {"✓": "ok", "~": "mid", "✗": "bad"}[mark]
        trs.append(
            f'<tr class="{st}" data-cat="{html.escape(r.get("category", ""))}" data-st="{st}">'
            f'<td class="id">{r["id"]}</td><td><span class="chip">{html.escape(CAT.get(r.get("category"), r.get("category", "")))}</span></td>'
            f'<td class="q"><b>{html.escape(r["question"])}</b>'
            f'<div class="ans">{html.escape((x.get("answer") or x.get("status") or "")[:400])}</div>'
            f'<div class="exp">Kutilgan: {html.escape(r.get("expected_answer") or "javob yoʻq")} '
            f'{"· " + html.escape(r["expected_article"]) if r.get("expected_article") else ""}</div></td>'
            f'<td class="mk">{mark}<small>{where}</small></td><td class="c">{html.escape(cites)}</td>'
            f'<td class="t">{ms if ms is not None else "—"}</td></tr>')
    cats = sorted({r.get("category", "") for r in rows})
    opts = "".join(f'<option value="{c}">{html.escape(CAT.get(c, c))}</option>' for c in cats)

    page = TEMPLATE.format(run=html.escape(m.get("run_id", "")), n=m.get("questions", len(rows)),
                           passed=passed, total=len(TARGETS), cards="".join(cards), rows="".join(trs), opts=opts,
                           model=html.escape(str(system.get("llm_model", "—"))),
                           index=html.escape(str(system.get("index_version", "—"))),
                           snap=html.escape(str(system.get("lex_snapshot_date", "—"))))
    out = os.path.join(run_dir, "report.html")
    open(out, "w", encoding="utf-8").write(page)
    print("Otchyot:", out)
    try:  # на Mac просто «open», без модуля webbrowser (в Python 3.15 с Homebrew он падает)
        cmd = ["open"] if sys.platform == "darwin" else (["start", ""] if os.name == "nt" else ["xdg-open"])
        subprocess.run(cmd + [os.path.abspath(out)], check=False, shell=os.name == "nt")
    except Exception:
        print("Oching:", out)


TEMPLATE = """<!doctype html><html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Qonunchi test natijasi</title>
<style>
:root{{--bg:#f5f8f9;--s:#fff;--fg:#14262b;--mu:#5b6e73;--ln:#d3dee1;--ok:#1f8a4c;--oks:#e3f3e9;--bad:#c0392b;--bads:#fbe9e7;--mid:#b4661a;--mids:#fbf0e4;--ac:#0a8fa8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1a1d;--s:#16252a;--fg:#e3edef;--mu:#95a9ae;--ln:#2b4146;--ok:#4fc983;--oks:#16382a;--bad:#ff8a7a;--bads:#3d1f1b;--mid:#f0a85e;--mids:#3a2a17;--ac:#3fc0d8;color-scheme:dark}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:28px max(16px,4vw) 60px}}
.w{{max-width:1200px;margin:0 auto;display:grid;gap:22px}}
h1{{margin:0;font-size:28px}} .sub{{color:var(--mu)}}
.score{{font-size:15px;background:var(--s);border:1px solid var(--ln);border-radius:12px;padding:14px 18px;display:flex;flex-wrap:wrap;gap:8px 24px}}
.score b{{color:var(--ac)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}}
.card{{background:var(--s);border:1px solid var(--ln);border-radius:12px;padding:14px 16px;border-top:4px solid var(--ln)}}
.card.ok{{border-top-color:var(--ok)}} .card.bad{{border-top-color:var(--bad)}}
.card .v{{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums}}
.card.ok .v{{color:var(--ok)}} .card.bad .v{{color:var(--bad)}}
.card .n{{font-size:13.5px}} .card .g{{font-size:12px;color:var(--mu)}}
.bar{{display:flex;flex-wrap:wrap;gap:10px;align-items:center}}
select,input{{font:inherit;padding:6px 10px;border:1px solid var(--ln);border-radius:8px;background:var(--s);color:var(--fg)}}
.tw{{overflow-x:auto;background:var(--s);border:1px solid var(--ln);border-radius:12px}}
table{{border-collapse:collapse;width:100%;min-width:760px}}
th,td{{padding:10px 12px;border-bottom:1px solid var(--ln);text-align:left;vertical-align:top}}
th{{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--mu);font-weight:500}}
td.id{{font-family:ui-monospace,Menlo,monospace;font-size:13px;color:var(--mu)}}
.chip{{font-size:12px;background:var(--bg);border:1px solid var(--ln);border-radius:99px;padding:1px 8px;white-space:nowrap}}
.q b{{font-weight:600}} .ans{{margin-top:4px}} .exp{{margin-top:4px;font-size:13px;color:var(--mu)}}
td.mk{{font-size:20px;font-weight:700;text-align:center;white-space:nowrap}} td.mk small{{display:block;font-size:11.5px;font-weight:400;color:var(--mu)}}
tr.ok td.mk{{color:var(--ok)}} tr.bad td.mk{{color:var(--bad)}} tr.mid td.mk{{color:var(--mid)}}
tr.bad{{background:var(--bads)}} tr.mid{{background:var(--mids)}}
td.c,td.t{{font-size:13px;white-space:nowrap;font-variant-numeric:tabular-nums}}
</style></head><body><div class="w">
<header><h1>Qonunchi: test natijasi</h1><div class="sub">Run <b>{run}</b> · {n} ta savol · model {model} · indeks {index} · lex.uz {snap}</div></header>
<div class="score">TZ maqsadlari: <b>{passed} / {total}</b> bajarildi</div>
<div class="cards">{cards}</div>
<div class="bar"><select id="cat"><option value="">Barcha kategoriyalar</option>{opts}</select>
<select id="st"><option value="">Barcha natijalar</option><option value="ok">✓ toʻgʻri</option><option value="mid">~ hujjat topildi, modda yoʻq</option><option value="bad">✗ xato</option></select>
<input id="s" type="search" placeholder="Savoldan qidirish"></div>
<div class="tw"><table><thead><tr><th>ID</th><th>Kategoriya</th><th>Savol, javob va kutilgan javob</th><th>Natija</th><th>Manbalar</th><th>ms</th></tr></thead>
<tbody id="tb">{rows}</tbody></table></div></div>
<script>
const f=()=>{{const c=cat.value,t=st.value,q=s.value.toLowerCase();
for(const r of tb.rows){{r.hidden=(c&&r.dataset.cat!==c)||(t&&r.dataset.st!==t)||(q&&!r.textContent.toLowerCase().includes(q));}}}};
cat.onchange=st.onchange=f;s.oninput=f;
</script></body></html>"""

if __name__ == "__main__":
    main()
