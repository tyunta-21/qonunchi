#!/usr/bin/env python3
"""Переделывает уже готовую базу: длинные документы без статей (постановления, приложения)
делятся на пункты «1.», «2.» или куски по ~1,5 тыс. символов. Скачивать ничего заново не нужно.

Запуск из папки qonunchi:   python rechunk_db.py            (база data/laws.db)
                            python rechunk_db.py ПУТЬ_К_БАЗЕ
Перед заменой делается резервная копия laws.db.backup_ДАТА. Повторный запуск ничего не портит:
уже разделённые куски короче порога и не режутся снова.
"""
import os, shutil, sqlite3, sys, time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.textnorm import norm
from build_db import SCHEMA, add_article


def main(path):
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise SystemExit(f"Не найдена база {path}")
    t0 = time.time()
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    doc_cols = [r[1] for r in src.execute("PRAGMA table_info(docs)")]
    art_cols = {r[1] for r in src.execute("PRAGMA table_info(articles)")}
    before = src.execute("SELECT count(*) FROM articles").fetchone()[0]

    tmp = path + ".rechunk.tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    dst = sqlite3.connect(tmp)
    dst.executescript(SCHEMA)
    new_cols = [r[1] for r in dst.execute("PRAGMA table_info(docs)")]
    for k, v in src.execute("SELECT k, v FROM meta"):
        dst.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, v))

    aid = 0
    docs = src.execute("SELECT * FROM docs ORDER BY key, lang").fetchall()
    for n, d in enumerate(docs, 1):
        vals = [d[c] if c in doc_cols else None for c in new_cols]
        dst.execute(f"INSERT INTO docs VALUES({','.join('?' * len(new_cols))})", vals)
        dst.execute("INSERT INTO doc_fts(rowid,title,number) VALUES(?,?,?)",
                    (d["key"] * 2 + (0 if d["lang"] == "ru" else 1), norm(d["title"] or ""), norm(d["number"] or "")))
        title_n = norm(d["title"] or "")
        pos = 0
        for a in src.execute("SELECT * FROM articles WHERE key=? AND lang=? ORDER BY pos", (d["key"], d["lang"])):
            g = lambda c: a[c] if c in art_cols else None
            k = add_article(dst, aid, d["key"], d["lang"], pos, g("num"), g("heading") or "", g("chapter") or "",
                            g("anchor") or "", g("src_url"), g("text") or "", g("chunk_id"), g("article"),
                            g("parts"), title_n)
            aid += k; pos += k
        dst.execute("UPDATE docs SET n_articles=? WHERE key=? AND lang=?", (pos, d["key"], d["lang"]))
        if n % 2000 == 0:
            print(f"  {n}/{len(docs)} документов…", flush=True); dst.commit()
    dst.execute("INSERT OR REPLACE INTO meta VALUES('built', ?)", (time.strftime("%Y-%m-%d %H:%M"),))
    dst.commit()
    dst.execute("INSERT INTO art_fts(art_fts) VALUES('optimize')")
    dst.commit()
    ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
    dst.close(); src.close()
    if ok != "ok":
        os.remove(tmp)
        raise SystemExit(f"Проверка новой базы не прошла ({ok}). Старая база не изменена.")
    backup = path + ".backup_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, backup)
    os.replace(tmp, path)
    print(f"Готово за {time.time() - t0:.0f} c: было {before} статей, стало {aid}.")
    print(f"Резервная копия: {backup}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "laws.db"))
