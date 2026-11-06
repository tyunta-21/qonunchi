#!/usr/bin/env python3
"""Собирает базу законов (SQLite) из скачанных JSON-файлов.

Запуск:  python build_db.py  ПАПКА_С_ДАННЫМИ  [ПУТЬ_К_БАЗЕ]
Пример:  python build_db.py ../lexuz/data data/laws.db
Папка с данными должна содержать docs/ru/*.json и docs/uz/*.json.
"""
import glob, json, os, sqlite3, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.textnorm import norm
from app.chunking import split as split_long

SCHEMA = """
CREATE TABLE docs(
  key INTEGER, lang TEXT, src_id INTEGER, title TEXT, number TEXT, date TEXT,
  effective_date TEXT, form TEXT, active INTEGER, amending INTEGER,
  status_warning TEXT, src_url TEXT, n_articles INTEGER, year INTEGER, edition_date TEXT, doc_status TEXT,
  PRIMARY KEY(key, lang));
CREATE TABLE articles(
  id INTEGER PRIMARY KEY, key INTEGER, lang TEXT, pos INTEGER, num TEXT,
  heading TEXT, chapter TEXT, anchor TEXT, src_url TEXT, text TEXT,
  chunk_id TEXT, article TEXT, parts TEXT);
CREATE INDEX art_doc ON articles(key, lang, pos);
CREATE VIRTUAL TABLE art_fts USING fts5(heading, text, title, content='', tokenize='unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE doc_fts USING fts5(title, number, content='', tokenize='unicode61 remove_diacritics 2');
CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
"""


FORM = {"qonun": "Закон", "kodeks": "Кодекс", "konstitutsiya": "Конституция"}


def add_article(db, aid, key, lang, pos, num, heading, chapter, anchor, url, text, chunk_id, article, parts, title_n):
    """Пишет статью; длинную статью без номера (постановления, приложения) — несколькими кусками.
    Возвращает, сколько строк записано (id идут подряд с aid+1, позиции — с pos)."""
    already = bool(chunk_id) and "#c" in chunk_id.rsplit("#", 1)[-1]   # уже разделённый кусок
    pieces = [(heading, None, text)] if (num or article or already) else split_long(text, lang, heading)
    for i, (h, lab, t) in enumerate(pieces):
        cid = chunk_id
        if len(pieces) > 1:
            cid = f"{chunk_id or f'lex:{key}#{lang}#p{pos}'}#c{i + 1}"
        db.execute("INSERT INTO articles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            aid + i + 1, key, lang, pos + i, num, h, chapter, anchor, url, t, cid,
            article if len(pieces) == 1 else lab, parts if len(pieces) == 1 else None))
        db.execute("INSERT INTO art_fts(rowid,heading,text,title) VALUES(?,?,?,?)",
                   (aid + i + 1, norm(h), norm(t), title_n))
    return len(pieces)


def _dmy(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if iso and len(iso) >= 10 else (iso or "")


def load_jsonl(db, src):
    """Новый формат: data/articles_{uz,ru}.jsonl — статья на строку, с частями (parts) и статусом."""
    aid, n_docs, docs, snaps = 0, 0, {}, set()
    for lang in ("ru", "uz"):
        fn = os.path.join(src, f"articles_{lang}.jsonl")
        pos = {}
        for line in open(fn, encoding="utf-8"):
            a = json.loads(line)
            if not (a.get("text") or "").strip():
                continue
            key = int(a["doc_id"].split(":")[1])
            dk = (key, lang)
            if dk not in docs:
                st = a.get("doc_status") or "amalda"
                date = _dmy(a.get("adoption_date"))
                docs[dk] = [key, lang, a.get("lex_page_id"), a.get("doc_title") or "", a.get("doc_number") or "",
                            date, _dmy(a.get("edition_date")), FORM.get(a.get("doc_type"), a.get("doc_type") or ""),
                            1 if st == "amalda" else 0, 1 if a.get("amending_act") else 0, a.get("status_warning"),
                            (a.get("url") or "").split("#")[0], 0, int(date[-4:]) if date[-4:].isdigit() else None,
                            a.get("edition_date"), st]
                title_n = norm(a.get("doc_title") or "")
            docs[dk][12] += 1
            if a.get("lex_snapshot_date"):
                snaps.add(a["lex_snapshot_date"])
            p = pos.get(dk, 0)
            before = aid
            n = add_article(db, aid, key, lang, p, a.get("article_num"), a.get("heading") or "",
                            (a.get("chapter") or "").replace("\n", " "),
                            (a.get("url") or "").split("#")[-1] if "#" in (a.get("url") or "") else "", a.get("url"),
                            a["text"], a.get("chunk_id"), a.get("article"),
                            json.dumps(a.get("parts") or [], ensure_ascii=False), norm(a.get("doc_title") or ""))
            aid += n; pos[dk] = p + n
            docs[dk][12] += n - 1
            if aid // 5000 != before // 5000:
                print(f"  {aid} статей…", flush=True); db.commit()
    for d in docs.values():
        db.execute("INSERT OR REPLACE INTO docs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", d)
        db.execute("INSERT INTO doc_fts(rowid,title,number) VALUES(?,?,?)",
                   (d[0] * 2 + (0 if d[1] == "ru" else 1), norm(d[3]), norm(d[4])))
    return len(docs), aid, snaps


def main(src, out):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    t0, n_docs, n_art, aid = time.time(), 0, 0, 0
    snaps = set()
    use_jsonl = all(os.path.exists(os.path.join(src, f"articles_{l}.jsonl")) for l in ("ru", "uz"))
    if use_jsonl:
        print("Читаю articles_ru.jsonl и articles_uz.jsonl")
        n_docs, n_art, snaps = load_jsonl(db, src)
    for lang in (() if use_jsonl else ("ru", "uz")):
        files = sorted(glob.glob(os.path.join(src, "docs", lang, "*.json")))
        for fn in files:
            try:
                d = json.load(open(fn, encoding="utf-8"))
            except Exception as e:
                print("пропуск", fn, e); continue
            m = d.get("meta", {})
            key = int(os.path.basename(fn).split(".")[0])
            arts = [a for a in d.get("articles", []) if (a.get("text") or "").strip()]
            date = m.get("date") or ""
            year = int(date[-4:]) if date[-4:].isdigit() else None
            rowid = key * 2 + (0 if lang == "ru" else 1)
            db.execute("INSERT OR REPLACE INTO docs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                key, lang, m.get("doc_id"), m.get("title") or m.get("page_title") or "", m.get("number") or "",
                date, m.get("effective_date") or "", m.get("form") or "", 1 if m.get("active", True) else 0,
                1 if m.get("amending_act") else 0, m.get("status_warning"), m.get("url"), len(arts), year,
                m.get("edition_date"), "amalda" if m.get("active", True) else "kuchini_yoqotgan"))
            if m.get("snapshot_date"):
                snaps.add(m["snapshot_date"])
            db.execute("INSERT INTO doc_fts(rowid,title,number) VALUES(?,?,?)",
                       (rowid, norm(m.get("title") or ""), norm(m.get("number") or "")))
            title_n = norm(m.get("title") or "")
            pos, start = 0, n_art
            for a in arts:
                n = add_article(db, aid, key, lang, pos, str(a["article"]) if a.get("article") is not None else None,
                                a.get("heading") or "", (a.get("chapter") or "").replace("\n", " "),
                                str(a.get("anchor") or ""), a.get("url"), a["text"], None, None, None, title_n)
                aid += n; pos += n; n_art += n
            db.execute("UPDATE docs SET n_articles=? WHERE key=? AND lang=?", (n_art - start, key, lang))
            n_docs += 1
            if n_docs % 200 == 0:
                print(f"  {n_docs} документов, {n_art} статей…", flush=True)
                db.commit()
    db.execute("INSERT INTO meta VALUES('built', ?)", (time.strftime("%Y-%m-%d %H:%M"),))
    if snaps:
        db.execute("INSERT INTO meta VALUES('snapshot', ?)", (max(snaps),))
    db.commit()
    db.execute("INSERT INTO art_fts(art_fts) VALUES('optimize')")
    db.commit(); db.close()
    os.replace(tmp, out)
    print(f"Готово: {n_docs} документов, {n_art} статей за {time.time()-t0:.0f} c -> {out}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "data/laws.db")
