"""Qonunchi — база законов Узбекистана с ИИ-помощником."""
import math, os, re, time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
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
    dq.append(now)
    # вопрос для поиска: добавляем прошлый вопрос, чтобы уточнения («а если…») находили ту же тему
    history = body.get("history") or []
    prev = [h.get("content", "") for h in history if h.get("role") == "user"][-1:]
    try:
        kw = llm.search_keywords(q, lang, history)
        srcs = db.retrieve(q + " " + " ".join(prev)[:300], lang, extra_query=kw)
        text, used = llm.answer(q, lang, history, srcs)
    except Exception as e:  # ключ не задан, нет денег на счёте, сеть и т. п.
        print("LLM error:", repr(e))
        return JSONResponse({"error": T[lang]["ai_error"]}, 502)
    sources = []
    for i, s in enumerate(srcs, 1):
        sources.append({"n": i, "used": i in used, "heading": s["heading"], "doc_title": s["doc_title"],
                        "active": bool(s["active"]), "url": f"/{s['lang']}/doc/{s['key']}#a{s['id']}",
                        "src_url": s["src_url"]})
    if used:
        sources = [s for s in sources if s["used"]] + [s for s in sources if not s["used"]][:2]
    return {"answer": text, "sources": sources, "disclaimer": llm.DISCLAIMER[lang], "mode": llm.PROVIDER}


@app.get("/health")
def health():
    return {"ok": True, "provider": llm.PROVIDER}
