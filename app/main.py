"""Qonunchi — база законов Узбекистана с ИИ-помощником."""
import math, os, re, time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from . import db, llm, rag_api
from .i18n import T, FORM_NAMES

HERE = os.path.dirname(__file__)
app = FastAPI(title="Qonunchi", docs_url=None, redoc_url=None)
app.include_router(rag_api.router)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
tpl = Jinja2Templates(directory=os.path.join(HERE, "templates"))
LANGS = ("uz", "ru")
RATE_LIMIT = int(os.environ.get("CHAT_LIMIT_PER_HOUR", "30"))
_hits = defaultdict(deque)
# общий лимит на всех за сутки (UTC, совпадает со сбросом бесплатной квоты OpenAI); 0 = без лимита
DAY_LIMIT = int(os.environ.get("CHAT_LIMIT_PER_DAY", "200"))
_day = {"date": "", "n": 0}


def _art_name(label, lang):
    """«543-modda» → «Статья 543» для русских документов."""
    m = re.fullmatch(r"(.+)-modda", label or "")
    return f"Статья {m[1]}" if m and lang == "ru" else label


def snip_html(s):
    return Markup(escape(s or "").replace("[[", Markup("<mark>")).replace("]]", Markup("</mark>")))


def paras(text):
    return Markup("".join(f"<p>{escape(p)}</p>" for p in (text or "").split("\n") if p.strip()))


tpl.env.filters["snip"] = snip_html
tpl.env.filters["paras"] = paras


def ctx(request, lang, **kw):
    if lang not in LANGS:
        raise HTTPException(404)
    base = dict(request=request, lang=lang, t=T[lang], forms=FORM_NAMES[lang], provider=llm.PROVIDER,
                other_lang="ru" if lang == "uz" else "uz", path=request.url.path)
    base.update(kw)
    return base


@app.get("/")
def root():
    return RedirectResponse("/uz/")


@app.get("/{lang}/", response_class=HTMLResponse)
def home(request: Request, lang: str):
    c = ctx(request, lang)
    return tpl.TemplateResponse(request, "home.html", ctx(
        request, lang, stats=db.stats(lang), codes=db.codes(lang), latest=db.latest(lang)))


@app.get("/{lang}/catalog", response_class=HTMLResponse)
def catalog(request: Request, lang: str, form: str = "", status: str = "active", year: str = "", q: str = "", page: int = 1):
    ctx(request, lang)
    page = max(1, page)
    rows, total = db.catalog(lang, form or None, status, year or None, q or None, page)
    return tpl.TemplateResponse(request, "catalog.html", ctx(
        request, lang, rows=rows, total=total, page=page, pages=max(1, math.ceil(total / 30)),
        f_form=form, f_status=status, f_year=year, q=q, years=db.years(lang)))


@app.get("/{lang}/search", response_class=HTMLResponse)
def search(request: Request, lang: str, q: str = "", page: int = 1, active: int = 0):
    ctx(request, lang)
    page = max(1, page)
    rows, total, docs = [], 0, []
    if q.strip():
        rows, total = db.search_articles(q, lang, limit=20, offset=(page - 1) * 20, active_only=bool(active))
        if page == 1:
            docs = db.search_docs(q, lang, limit=6)
    return tpl.TemplateResponse(request, "search.html", ctx(
        request, lang, q=q, rows=rows, total=total, docs=docs, page=page,
        pages=max(1, math.ceil(total / 20)), active=active))


@app.get("/{lang}/doc/{key}", response_class=HTMLResponse)
def document(request: Request, lang: str, key: int, q: str = ""):
    ctx(request, lang)
    d = db.doc(key, lang)
    if not d:
        langs = db.doc_langs(key)
        if langs:
            return RedirectResponse(f"/{langs[0]}/doc/{key}")
        raise HTTPException(404)
    arts = db.articles(key, lang)
    toc, last = [], None
    for a in arts:
        ch = a["chapter"] or ""
        if ch != last:
            toc.append({"chapter": ch, "items": []}); last = ch
        toc[-1]["items"].append(a)
    return tpl.TemplateResponse(request, "doc.html", ctx(
        request, lang, d=d, arts=arts, toc=toc, langs=db.doc_langs(key), q=q))


@app.get("/{lang}/assistant", response_class=HTMLResponse)
def assistant(request: Request, lang: str):
    return tpl.TemplateResponse(request, "assistant.html", ctx(request, lang))


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    q = str(body.get("question", "")).strip()[:1500]
    lang = body.get("lang") if body.get("lang") in LANGS else "uz"
    if not q:
        return JSONResponse({"error": "empty"}, 400)
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0]
    now, dq = time.time(), _hits[ip]
    while dq and now - dq[0] > 3600:
        dq.popleft()
    if len(dq) >= RATE_LIMIT:
        return JSONResponse({"error": T[lang]["rate_limited"]}, 429)
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    if _day["date"] != today:
        _day.update(date=today, n=0)
    if DAY_LIMIT and _day["n"] >= DAY_LIMIT:
        return JSONResponse({"error": T[lang]["day_limited"]}, 429)
    _day["n"] += 1
    dq.append(now)
    # тот же конвейер, что проходит оценку LEX_100: BM25 + e5-эмбеддинги, реранкинг, ответ с цитатами
    history = body.get("history") or []
    prev = [h.get("content", "") for h in history if h.get("role") == "user"][-1:]
    question = q if not prev or len(q) > 80 else f"{prev[0][:300]}\n{q}"   # короткое уточнение («а если…»)
    try:
        res = await run_in_threadpool(rag_api.answer_item, {"id": "site", "question": question},
                                      {"top_k": 5, "temperature": 0, "_site": True})
    except Exception as e:
        res = {"status": "error", "error": repr(e)}
    if res.get("status") in ("error", "timeout"):   # ключ не задан, нет денег на счёте, сеть и т. п.
        print("LLM error:", res.get("error"))
        return JSONResponse({"error": T[lang]["ai_error"]}, 502)
    text = res.get("answer") or ""
    sources = [{"n": c["ref"], "used": True, "heading": _art_name(c.get("article"), c.get("_lang", lang)) or c["doc_title"], "doc_title": c["doc_title"],
                "quote": c.get("quote") or "", "active": c.get("_active", True),
                "url": f"/{c.get('_lang', lang)}/doc/{c['doc_id'][4:]}#a{c['_aid']}" if c.get("_aid") else c["url"],
                "src_url": c["url"]} for c in res.get("citations") or []]
    return {"answer": text, "sources": sources, "disclaimer": llm.DISCLAIMER[lang], "mode": llm.PROVIDER}


@app.get("/health")
def health():
    return {"ok": True, "provider": llm.PROVIDER}
