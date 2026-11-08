"""Доступ к базе законов: каталог, поиск, документ, подбор статей для бота."""
import os, sqlite3, threading
from .textnorm import fts_query, terms, norm

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "laws.db"))
_local = threading.local()

FORMS = ["Конституция", "Кодекс", "Закон"]


def conn():
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
        c.row_factory = sqlite3.Row
        _local.c = c
    return c


def stats(lang):
    rows = conn().execute("SELECT form, count(*) n FROM docs WHERE lang=? GROUP BY form", (lang,)).fetchall()
    by = {r["form"]: r["n"] for r in rows}
    total_art = conn().execute("SELECT count(*) FROM articles WHERE lang=?", (lang,)).fetchone()[0]
    built = conn().execute("SELECT v FROM meta WHERE k='built'").fetchone()
    return {"by_form": by, "docs": sum(by.values()), "articles": total_art, "built": built[0] if built else ""}


def codes(lang):
    return conn().execute(
        "SELECT * FROM docs WHERE lang=? AND form IN ('Конституция','Кодекс') AND active=1 "
        "ORDER BY form='Кодекс', title", (lang,)).fetchall()


def latest(lang, limit=8):
    return conn().execute(
        "SELECT * FROM docs WHERE lang=? AND active=1 ORDER BY substr(date,7,4)||substr(date,4,2)||substr(date,1,2) DESC LIMIT ?",
        (lang, limit)).fetchall()


def years(lang):
    return [r[0] for r in conn().execute(
        "SELECT DISTINCT year FROM docs WHERE lang=? AND year IS NOT NULL ORDER BY year DESC", (lang,))]


def catalog(lang, form=None, status="active", year=None, q=None, page=1, per=30):
    where, args = ["d.lang=?"], [lang]
    if form:
        where.append("d.form=?"); args.append(form)
    if status == "active":
        where.append("d.active=1")
    elif status == "inactive":
        where.append("d.active=0")
    if year:
        where.append("d.year=?"); args.append(int(year))
    join = ""
    if q:
        fq = fts_query(q, "AND")
        if fq:
            join = "JOIN doc_fts f ON f.rowid = d.key*2 + (CASE d.lang WHEN 'ru' THEN 0 ELSE 1 END)"
            where.append("doc_fts MATCH ?"); args.append(fq)
    sql_where = " AND ".join(where)
    total = conn().execute(f"SELECT count(*) FROM docs d {join} WHERE {sql_where}", args).fetchone()[0]
    rows = conn().execute(
        f"SELECT d.* FROM docs d {join} WHERE {sql_where} "
        "ORDER BY d.form='Закон', substr(d.date,7,4)||substr(d.date,4,2)||substr(d.date,1,2) DESC LIMIT ? OFFSET ?",
        args + [per, (page - 1) * per]).fetchall()
    return rows, total


_HAS_MAP = None


def _has_map():
    global _HAS_MAP
    if _HAS_MAP is None:
        _HAS_MAP = bool(conn().execute("SELECT 1 FROM sqlite_master WHERE name='art_map'").fetchone())
    return _HAS_MAP


def search_articles(q, lang, limit=20, offset=0, active_only=False, key=None, mode="OR", count=True):
    fq = fts_query(q, mode)
    if not fq:
        return [], 0
    # a = маленькая art_map (id, key, lang), если есть: сортировка не трогает тексты статей
    src = "art_map" if _has_map() else "articles"
    where = "art_fts MATCH ? AND a.lang=?"
    args = [fq, lang]
    if active_only:
        where += " AND d.active=1"
    if key:
        where += " AND a.key=?"; args.append(int(key))
    base = (f"FROM art_fts JOIN {src} a ON a.id=art_fts.rowid "
            f"JOIN docs d ON d.key=a.key AND d.lang=a.lang WHERE {where}")
    # count(*) — лишний полный проход по совпадениям; для ИИ-поиска он не нужен
    total = conn().execute(f"SELECT count(*) {base}", args).fetchone()[0] if count else None
    top = (f"SELECT art_fts.rowid rid, snippet(art_fts, 1, '[[', ']]', ' … ', 28) snip, "
           f"bm25(art_fts, 4.0, 1.0, 2.5) - (CASE WHEN d.active=1 THEN 3 ELSE 0 END) "
           f"- (CASE d.form WHEN 'Конституция' THEN 2.0 WHEN 'Кодекс' THEN 2.0 "
           f"WHEN 'Закон' THEN 1.2 WHEN 'Постановление' THEN -0.5 ELSE 0 END) score "
           f"{base} ORDER BY score LIMIT ? OFFSET ?")
    rows = conn().execute(
        f"SELECT a.*, d.title doc_title, d.form, d.date, d.number, d.active, d.status_warning, d.amending, "
        f"d.doc_status, d.edition_date, s.snip, s.score FROM ({top}) s "
        f"JOIN articles a ON a.id=s.rid JOIN docs d ON d.key=a.key AND d.lang=a.lang ORDER BY s.score",
        args + [limit, offset]).fetchall()
    return rows, total


def search_docs(q, lang, limit=8):
    rows, _ = catalog(lang, status="all", q=q, per=limit)
    return rows


def doc(key, lang):
    return conn().execute("SELECT * FROM docs WHERE key=? AND lang=?", (key, lang)).fetchone()


def doc_langs(key):
    return [r[0] for r in conn().execute("SELECT lang FROM docs WHERE key=?", (key,))]


def articles(key, lang):
    return conn().execute("SELECT * FROM articles WHERE key=? AND lang=? ORDER BY pos", (key, lang)).fetchall()


def article(aid):
    return conn().execute(
        "SELECT a.*, d.title doc_title, d.active, d.form, d.date, d.number FROM articles a "
        "JOIN docs d ON d.key=a.key AND d.lang=a.lang WHERE a.id=?", (aid,)).fetchone()


def _rerank(rows, query, k):
    """Поднимаем статьи, где встречается больше слов вопроса (особенно в заголовке)."""
    ts = terms(query)
    if not ts:
        return rows[:k]
    def cover(r):
        h, t = norm(r["heading"]), norm(r["text"])
        return sum(2.0 if w in h else (1.0 if w in t else 0) for w in ts) / len(ts)
    ranked = sorted(enumerate(rows), key=lambda x: (-(cover(x[1]) * 3 - x[0] * 0.08)))
    return [r for _, r in ranked][:k]


def retrieve(question, lang, k=8, extra_query=None):
    """Статьи-кандидаты для ИИ-бота: действующие акты; extra_query — ключевые слова от ИИ."""
    pool, seen = [], set()
    for q in [extra_query, question]:
        if not q:
            continue
        rows, _ = search_articles(q, lang, limit=40, active_only=True)
        for r in _rerank(list(rows), q, k):
            if r["id"] not in seen:
                seen.add(r["id"]); pool.append(r)
    if len(pool) < 3:
        other = "ru" if lang == "uz" else "uz"
        rows, _ = search_articles(extra_query or question, other, limit=20, active_only=True)
        pool += _rerank(list(rows), extra_query or question, k - len(pool))
    # чередуем: лучшие по ключевым словам ИИ и по исходному вопросу
    return pool[: k + (2 if extra_query else 0)]


_ART_SELECT = ("SELECT a.*, d.title doc_title, d.form, d.date, d.number, d.active, d.status_warning, d.amending, "
               "d.doc_status, d.edition_date, '' snip, 0.0 score FROM articles a "
               "JOIN docs d ON d.key=a.key AND d.lang=a.lang ")


def articles_by_ids(ids):
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    return conn().execute(_ART_SELECT + f"WHERE a.id IN ({q})", list(ids)).fetchall()


_chapters = {}
_chap_lock = threading.Lock()


def code_chapters(lang):
    """Главы и разделы действующих кодексов и Конституции: [(norm(название главы), [id статей])]. Кэш в памяти."""
    if lang in _chapters:
        return _chapters[lang]
    with _chap_lock:   # строим один раз, даже если сразу пришло 10 вопросов
        if lang not in _chapters:
            by = {}
            for r in conn().execute("SELECT a.id, a.chapter FROM articles a JOIN docs d ON d.key=a.key AND d.lang=a.lang "
                                    "WHERE a.lang=? AND d.active=1 AND d.form IN ('Кодекс','Конституция') "
                                    "AND a.chapter IS NOT NULL AND a.chapter<>''", (lang,)):
                by.setdefault(norm(r["chapter"]), []).append(r["id"])
            _chapters[lang] = list(by.items())
    return _chapters[lang]
