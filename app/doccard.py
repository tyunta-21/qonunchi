"""Карточка документа и обязательные статьи Конституции для RAG.

1) Вопросы о самом документе («Mehnat kodeksi?», «“Kiberxavfsizlik toʻgʻrisida”gi Qonun?») — ответ это паспорт
   документа: полное название, номер, дата принятия, статус. Обычный поиск по статьям этого не даёт, поэтому
   находим документ по названию и отдаём модели «карточку» (паспорт + первая статья документа).
2) Простые вопросы о государстве (Президент, Oliy Majlis, собственность, Qoraqalpogʻiston) — статьи Конституции
   без заголовков проигрывают длинным законам в BM25. Ищем отдельно внутри Конституции и добавляем лучшие статьи.
"""
import re

from . import db
from .textnorm import norm, terms

# Названия видов документов в вопросе -> form в базе
_KIND = [
    (r"kodeks|кодекс", ("Кодекс",)),
    (r"konstitutsiya|конституц", ("Конституция",)),
    (r"qonun|закон|қонун", ("Закон",)),
    (r"strategiya|стратеги", ("Указ", "Постановление")),
    (r"farmon|указ|фармон", ("Указ",)),
    (r"qaror|постановлен|қарор", ("Постановление",)),
]
_QUOTED = re.compile(r"[«\"“„]([^»\"”“]{4,160})[»\"”“]")
# «… kodeksi», «… qonuni/qonunlari», «… strategiyasi» без кавычек
_NAMED = re.compile(r"([\w'ʻʼ‘’`\- –—]{3,80}?)\s+(kodeksi|qonuni|qonunlari|strategiyasi|кодекс\w*|закон\w*|стратеги\w*)\b"
                    r"|([\w'ʻʼ‘’`\- –—]{3,80}?\s+to['ʻ‘’`]?g['ʻ‘’`]?risidagi)\s+(?:amaldagi\s+|yangi\s+)?qonun", re.I)
_ARTICLE_NO = re.compile(r"\d+\s*-?\s*(modda|moddasi|статья|статьи|статье|модда)", re.I)
_DOC_WORDS = set("togrisida togrisidagi toʻgʻrisida haqida qonun qonuni qonunlari kodeks kodeksi strategiya strategiyasi "
                 "farmon qaror ozbekiston respublikasi respublikasining amaldagi amaldami hozir yangi eski asosiy "
                 "закон кодекс республики узбекистан о об стратегия".split())
_LABELS = {
    "uz": ("HUJJAT KARTASI (lex.uz maʼlumotlari)", "Hujjat", "Turi", "Raqami", "Qabul qilingan sana",
           "Kuchga kirgan sana", "Holati", "amalda", "kuchini yoʻqotgan", "Havola", "Hujjatning birinchi moddasi",
           "AMALDAGI HUJJAT", "ESKI HUJJAT (kuchini yoʻqotgan)",
           "Izoh: lex.uz da qonunning amaldagi yangi tahriri shu hujjat sifatida joylashtirilgan"),
    "ru": ("КАРТОЧКА ДОКУМЕНТА (данные lex.uz)", "Документ", "Вид", "Номер", "Дата принятия",
           "Дата вступления в силу", "Статус", "действует", "утратил силу", "Ссылка", "Первая статья документа",
           "ДЕЙСТВУЮЩИЙ ДОКУМЕНТ", "СТАРЫЙ ДОКУМЕНТ (утратил силу)",
           "Примечание: на lex.uz действующая новая редакция закона размещена как этот документ"),
}
_FORM_NAME = {"uz": {"Закон": "Qonun", "Кодекс": "Kodeks", "Конституция": "Konstitutsiya", "Указ": "Prezident farmoni",
                     "Постановление": "Qaror"},
              "ru": {}}


# Сокращения и варианты написания в названиях документов
_ABBR = [(r"\boav\b", "ommaviy axborot vositalari"), (r"\bсми\b", "средства массовой информации"),
         (r"\bdxsh\b", "davlat-xususiy sheriklik"), (r"\bгчп\b", "государственно-частное партнерство"),
         (r"\bbyudjet", "budjet"), (r"\bnogironlar\b", "nogironligi boʻlgan shaxslar"),
         (r"\bинвалид\w*", "лиц с инвалидностью")]


def _canon(name):
    n = name.lower()
    for pat, rep in _ABBR:
        n = re.sub(pat, rep, n)
    return n


_SKIP4 = ("togr", "ozbe", "resp", "qonu", "kode", "stra", "зако", "коде", "респ", "узбе", "huqu", "прав")


def _name_terms(name, keep_digits=False):
    all_t = [t for t in terms(_canon(name), limit=12) if t not in _DOC_WORDS and not t.startswith("yil")
             and (keep_digits or not t.isdigit())]
    ts = [t for t in all_t if t[:4] not in _SKIP4]
    return ts or [t for t in all_t if t[:4] in ("huqu", "прав")]


def _kinds(text):
    forms = []
    for pat, fs in _KIND:
        if re.search(pat, norm(text)):
            forms += [f for f in fs if f not in forms]
    return forms


def _core(title):
    t = norm(_canon(title)).replace("ozbekiston respublikasining ", "")
    return re.sub(r"\W+", " ", t).strip()


_AMEND_T = re.compile(r"ozgarti?sh|qoshimcha|kiritish|изменени|дополнени")


def _find(name, lang, forms, year=None, limit=30, quoted=False, strategy=False):
    ts = _name_terms(name, keep_digits=quoted)
    if not ts:
        return []
    must = list(ts)
    if "Кодекс" in forms:
        must.append("kodeks" if lang == "uz" else "кодекс")
    elif strategy:
        must.append("strategiya" if lang == "uz" else "стратеги")
    fq = " AND ".join(f'"{t}"*' for t in dict.fromkeys(must))
    rows = db.conn().execute(
        "SELECT d.* FROM doc_fts f JOIN docs d ON f.rowid = d.key*2 + (CASE d.lang WHEN 'ru' THEN 0 ELSE 1 END) "
        "WHERE doc_fts MATCH ? AND d.lang=? ORDER BY d.amending, d.active DESC, length(d.title) LIMIT 3000",
        (fq, lang)).fetchall()
    nn = norm(_canon(name)).replace("ozbekiston respublikasining ", "")
    tset = set(ts)

    def rank(d):
        t = norm(d["title"])
        tw = [w for w in _name_terms(d["title"])]
        extra = len([w for w in tw if not any(w.startswith(x) or x.startswith(w) for x in tset)])
        return (
            0 if (not quoted or all(x in t for x in ts)) else 1,
            0 if (year and str(d["year"]) == str(year)) else 1,
            0 if not forms or d["form"] in forms else 1,
            1 if (d["amending"] or _AMEND_T.search(norm(d["title"]))) else 0,   # «о внесении изменений»
            1 if re.match(r"^[“«\"][^”»\"]+[”»\"]\s?gi\b", d["title"]) else 0,   # «“X”gi Qonuniga …» — о другом документе
            0 if _core(d["title"]) == _core(nn) else 1,    # название совпало целиком
            0 if (quoted and _core(nn) in _core(d["title"])) else 1,   # «…» из вопроса есть в названии
            extra if quoted else 0,                          # для «…»: самое близкое название
            0 if d["active"] else 1,
            0 if (nn and nn in t) else 1,
            extra,                                           # лишние слова в названии
            -int(d["year"] or 0),
        )
    rows = sorted(rows, key=rank)
    return rows[:limit]


def _successor(d, lang):
    """Действующий документ вместо утратившего силу: новая редакция («“X”gi Qonunini yangi tahrirda…»,
    в т.ч. оформленная как закон о внесении изменений) или кодекс, который заменил закон (Suv kodeksi)."""
    ts = _name_terms(d["title"])
    if not ts:
        return None
    words = [w for w in re.findall(r"[^\W\d]+", d["title"]) if not re.search(r"[ʻʼ‘’'`]", w)]
    words = [w for w in words if norm(w) not in ("ozbekiston", "respublikasining")][:6]
    fq = '"' + " ".join(words) + '"' if len(words) >= 2 else " AND ".join(f'"{t}"*' for t in ts)
    base = norm(d["title"]).replace("ozbekiston respublikasining ", "")
    rows = db.conn().execute(
        "SELECT d.* FROM doc_fts f JOIN docs d ON f.rowid = d.key*2 + (CASE d.lang WHEN 'ru' THEN 0 ELSE 1 END) "
        "WHERE doc_fts MATCH ? AND d.lang=? AND d.active=1 AND d.form IN ('Закон','Кодекс') LIMIT 400",
        (fq, lang)).fetchall()
    same = [r for r in rows if base in norm(r["title"])]
    if same:
        def dkey(r):
            m = re.match(r"(\d\d)\.(\d\d)\.(\d{4})", r["date"] or "")
            return (m[3] + m[2] + m[1]) if m else ""
        return max(same, key=dkey)
    first = ts[0]
    code = db.conn().execute(
        "SELECT d.* FROM doc_fts f JOIN docs d ON f.rowid = d.key*2 + (CASE d.lang WHEN 'ru' THEN 0 ELSE 1 END) "
        "WHERE doc_fts MATCH ? AND d.lang=? AND d.active=1 AND d.form='Кодекс' ORDER BY length(d.title) LIMIT 1",
        (f'"{first}"* AND "{"kodeks" if lang == "uz" else "кодекс"}"*', lang)).fetchone()
    return code


_CONST_DOC_Q = re.compile(r"(konstitutsiya|конституц)\w*.*(qabul|kuchga|tahrir|qachon|принят|вступил|редакц|когда)|"
                          r"(qabul|kuchga|tahrir|qachon|принят|вступил|редакц|когда).*(konstitutsiya|конституц)", re.I)


def doc_question(question):
    """(название, виды, год, в кавычках?, стратегия?) если вопрос — о документе как таковом, иначе None."""
    q = question.strip()
    if _ARTICLE_NO.search(q):
        return None
    if _CONST_DOC_Q.search(norm(q)):
        return "Konstitutsiya", ["Конституция"], None, False, False
    m = _QUOTED.search(q)
    name = None
    if m:
        name = m.group(1)
    else:
        m = _NAMED.search(q)
        if m:
            name = re.sub(r"to['ʻ‘’`]?g['ʻ‘’`]?risidagi$", "toʻgʻrisida", m.group(3)) if m.group(3) else m.group(0)
    if not name:
        return None
    # длинный вопрос с цитатой — это вопрос о норме, а не о документе; карточка всё равно полезна (ст. 1),
    # но её не ставим, если в названии нет значимых слов
    if not _name_terms(name, keep_digits=bool(_QUOTED.search(q))) and not re.search(r"kodeks|кодекс|konstitu|конститу", norm(name)):
        return None
    if m.re is _QUOTED and not (re.search(r"to['ʻ‘’`]?g['ʻ‘’`]?risida|haqida|^о |^об ", norm(name) + " " + name.lower())
                                or _kinds(q.replace(name, ""))):
        return None
    y = re.search(r"\b(19[89]\d|20[0-2]\d)\b", q.replace(name, "") if m.re is _QUOTED else q)
    return name, _kinds(q.replace(name, "") if m.re is _QUOTED else q), (y.group(1) if y else None), \
        m.re is _QUOTED, bool(re.search(r"strateg|стратеги", norm(q)))


def _first_article(key, lang):
    return db.conn().execute(
        "SELECT a.*, d.title doc_title, d.form, d.date, d.number, d.active, d.status_warning, d.amending, "
        "d.doc_status, d.edition_date, '' snip, 0.0 score FROM articles a JOIN docs d ON d.key=a.key AND d.lang=a.lang "
        "WHERE a.key=? AND a.lang=? ORDER BY a.pos LIMIT 1", (key, lang)).fetchone()


def card_rows(question, lang):
    """Строки-«карточки» (dict, как строка статьи) для вопроса о документе. Пусто, если вопрос не о документе."""
    dq = doc_question(question)
    if not dq:
        return []
    name, forms, year, quoted, strategy = dq
    if forms == ["Конституция"] and name == "Konstitutsiya":
        k = const_key()
        found = [db.doc(k, lang)] if k else []
    else:
        if re.search(r"kodeks|кодекс", norm(name)) and not _name_terms(name):
            return []
        found = _find(name, lang, forms, year, quoted=quoted, strategy=strategy)
    if not found:
        return []
    best = found[0]
    out = [best]
    # Если лучший найденный документ утратил силу — покажем и действующий с тем же названием (и наоборот:
    # для «… hozir amaldami?» нужен и старый, и новый).
    same = [d for d in found[1:] if d["form"] == best["form"] and not d["amending"]
            and norm(d["title"]).replace("ozbekiston respublikasining ", "") ==
            norm(best["title"]).replace("ozbekiston respublikasining ", "")]
    if same:
        out.append(same[0])
    if not any(d["active"] for d in out):
        nxt = _successor(best, lang)
        if nxt is not None:
            out = [best, nxt]
    rows = []
    L = _LABELS[lang]
    multi = len(out) > 1
    if multi:   # действующий документ — первым
        out = sorted(out, key=lambda d: 0 if d["active"] else 1)
    for d in out:
        a = _first_article(d["key"], lang)
        if a is None:
            continue
        status = L[7] if d["active"] else L[8]
        if d["status_warning"]:
            status += f" ({d['status_warning']})"
        head = L[0] + ((" — " + (L[11] if d["active"] else L[12])) if multi else "")
        lines = [head, f"{L[1]}: {d['title']}", f"{L[2]}: {_FORM_NAME[lang].get(d['form'], d['form'])}",
                 f"{L[3]}: {(d['number'] or '').replace('-сон', '')}", f"{L[4]}: {d['date']}",
                 f"{L[5]}: {d['effective_date'] or d['date']}", f"{L[6]}: {status}", f"{L[9]}: {d['src_url']}",
                 f"{L[10]}:"]
        if d["active"] and d["amending"] and d["title"][:1] in "“«\"" or (d["active"] and d["amending"] and lang == "ru"):
            lines.insert(-1, L[13])
        r = dict(a)
        r["text"] = "\n".join(lines) + "\n" + (a["text"] or "")
        r["doc_card"] = True
        rows.append(r)
    return rows


# ---------------------------------------------------------------- Конституция
_CONST = {}
STATE_WORDS = re.compile(
    r"prezident|президент|oliy majlis|олий мажлис|олий мажлис|senat|сенат|qonunchilik palata|законодательн\w* палат|"
    r"konstitutsiya|конституц|davlat tili|государственн\w* язык|fuqarolig|гражданств|qoraqalpog|каракалпак|"
    r"suveren|суверен|mulk|собственност|hokimiyat|власт|hokim\b|hokimi|хоким|mahalla|махалл|fuqarolar yig|"
    r"inson huquq|прав\w* человек|sud hokimiyat|судебн\w* власт|referendum|референдум|davlat ramz|gerb|bayroq|madhiya|"
    r"сайлов|saylov|выбор|deputat|депутат|vazirlar mahkamasi|кабинет министров|oʻlim jazosi|smertn|ommaviy axborot|сми",
    re.I)


def const_key():
    if "k" not in _CONST:
        r = db.conn().execute("SELECT key FROM docs WHERE form='Конституция' AND active=1 AND lang='uz' "
                              "AND title LIKE 'O%zbekiston Respublikasi Konstitutsiyasi%' LIMIT 1").fetchone()
        _CONST["k"] = r[0] if r else None
    return _CONST["k"]


def const_rows(question, lang, rewritten=None, n=3):
    """Лучшие статьи Конституции для «государственных» вопросов (не больше n)."""
    if not STATE_WORDS.search(norm(question) + " " + question.lower()):
        return []
    key = const_key()
    if not key:
        return []
    ts = terms(question + " " + (rewritten or ""))
    cand = {}
    for q in (question, rewritten):
        if not q:
            continue
        rows = db.search_articles(q, lang, limit=10, active_only=True, key=key, count=False)[0]
        for i, r in enumerate(rows):
            chap = norm((r["chapter"] or "").split("/")[-1])
            text = norm(r["text"] or "")
            sc = (1 - i / 10) + 0.6 * sum(1 for t in ts if t in chap) + 0.4 * sum(1 for t in ts if t in text) / max(1, len(ts))
            if r["id"] not in cand or cand[r["id"]][0] < sc:
                cand[r["id"]] = (sc, r)
    return [r for _, r in sorted(cand.values(), key=lambda x: -x[0])][:n]


def merge(ctxs, cards, consts, limit):
    """Карточки — в начало, статьи Конституции — сразу после 4 лучших статей; всего не больше limit + карточки."""
    card_ids = {r["id"] for r in cards}
    base = [c for c in ctxs if c[2]["id"] not in card_ids]
    have = {c[2]["id"] for c in base}
    add = [(round(0.5, 4), 0.5, r) for r in consts if r["id"] not in have]
    if add:
        keep = max(0, limit - len(add))
        base = base[:4] + add + base[4:keep]
    return [(1.0, 1.0, r) for r in cards] + base[:limit]
