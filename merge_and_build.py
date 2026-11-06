#!/usr/bin/env python3
"""Добавляет новые JSON-документы в существующую базу Qonunchi, не удаляя старые.

Запуск из папки qonunchi:
  python merge_and_build.py ../lexuz_kit/data [data/laws.db]

Сначала build_db.py собирает временную SQLite-базу из новых JSON,
затем новые документы и статьи добавляются в существующую базу.
Перед изменением создаётся резервная копия laws.db.
"""
import os
import sys
import sqlite3
import shutil
import tempfile
import subprocess
import time
from datetime import datetime

from app.textnorm import norm

ROOT = os.path.dirname(os.path.abspath(__file__))


def main(source_dir, target_db):
    source_dir = os.path.abspath(source_dir)
    target_db = os.path.abspath(target_db)
    if not os.path.isdir(os.path.join(source_dir, "docs", "uz")):
        raise SystemExit(f"Не найдена папка {source_dir}/docs/uz")
    if not os.path.isfile(target_db):
        raise SystemExit(f"Не найдена существующая база: {target_db}")

    fd, new_db = tempfile.mkstemp(prefix="qonunchi_new_", suffix=".db",
                                  dir=os.path.dirname(target_db))
    os.close(fd)
    os.remove(new_db)
    try:
        print("1/4 Собираю временную базу из новых JSON…", flush=True)
        subprocess.run([sys.executable, os.path.join(ROOT, "build_db.py"),
                        source_dir, new_db], check=True)

        src = sqlite3.connect(f"file:{new_db}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        new_count = src.execute("SELECT count(*) FROM docs").fetchone()[0]
        if not new_count:
            raise SystemExit("В новых JSON не найдено документов. Существующая база не изменена.")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = target_db + f".backup_{stamp}"
        print(f"2/4 Создаю резервную копию: {backup}", flush=True)
        shutil.copy2(target_db, backup)

        dst = sqlite3.connect(target_db)
        dst.row_factory = sqlite3.Row
        dst.execute("PRAGMA foreign_keys=OFF")
        dst.execute("PRAGMA journal_mode=DELETE")
        dst.execute("ATTACH DATABASE ? AS newdb", (new_db,))

        added_docs = added_articles = skipped_docs = 0
        next_article_id = dst.execute("SELECT COALESCE(MAX(id),0)+1 FROM articles").fetchone()[0]
        try:
            print("3/4 Добавляю документы и статьи…", flush=True)
            dst.execute("BEGIN IMMEDIATE")
            source_docs = src.execute("SELECT * FROM docs ORDER BY key, lang").fetchall()
            for d in source_docs:
                exists = dst.execute("SELECT 1 FROM docs WHERE key=? AND lang=?",
                                     (d["key"], d["lang"])).fetchone()
                if exists:
                    skipped_docs += 1
                    continue

                cols = [r[1] for r in dst.execute("PRAGMA table_info(docs)")]
                dst.execute(
                    f"INSERT INTO docs ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                    tuple(d[c] for c in cols)
                )
                title_norm = norm(d["title"] or "")
                rowid = int(d["key"]) * 2 + (0 if d["lang"] == "ru" else 1)
                dst.execute("INSERT INTO doc_fts(rowid,title,number) VALUES(?,?,?)",
                            (rowid, title_norm, norm(d["number"] or "")))

                arts = src.execute(
                    "SELECT key,lang,pos,num,heading,chapter,anchor,src_url,text,chunk_id,article,parts "
                    "FROM articles WHERE key=? AND lang=? ORDER BY pos",
                    (d["key"], d["lang"])
                ).fetchall()
                for a in arts:
                    dst.execute(
                        "INSERT INTO articles(id,key,lang,pos,num,heading,chapter,anchor,src_url,text,chunk_id,article,parts) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (next_article_id, a["key"], a["lang"], a["pos"], a["num"], a["heading"],
                         a["chapter"], a["anchor"], a["src_url"], a["text"], a["chunk_id"],
                         a["article"], a["parts"])
                    )
                    dst.execute("INSERT INTO art_fts(rowid,heading,text,title) VALUES(?,?,?,?)",
                                (next_article_id, norm(a["heading"] or ""),
                                 norm(a["text"] or ""), title_norm))
                    next_article_id += 1
                    added_articles += 1
                added_docs += 1

            built = time.strftime("%Y-%m-%d %H:%M")
            dst.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('built',?)", (built,))
            new_snap = src.execute("SELECT v FROM meta WHERE k='snapshot'").fetchone()
            old_snap = dst.execute("SELECT v FROM meta WHERE k='snapshot'").fetchone()
            snapshots = [x[0] for x in (new_snap, old_snap) if x and x[0]]
            if snapshots:
                dst.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('snapshot',?)",
                            (max(snapshots),))
            dst.execute("INSERT INTO art_fts(art_fts) VALUES('optimize')")
            dst.commit()

            check = dst.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise RuntimeError(f"Проверка SQLite не пройдена: {check}")
            print("4/4 Проверка базы пройдена.", flush=True)
        except Exception:
            dst.rollback()
            dst.close()
            shutil.copy2(backup, target_db)
            raise
        finally:
            try:
                dst.execute("DETACH DATABASE newdb")
            except Exception:
                pass
            dst.close()
            src.close()

        counts = sqlite3.connect(f"file:{target_db}?mode=ro", uri=True)
        docs_total = counts.execute("SELECT count(*) FROM docs").fetchone()[0]
        arts_total = counts.execute("SELECT count(*) FROM articles").fetchone()[0]
        counts.close()
        print(f"Готово. Добавлено документов: {added_docs}; статей: {added_articles}; "
              f"уже существовало: {skipped_docs}.", flush=True)
        print(f"Всего в базе: {docs_total} записей документов, {arts_total} статей.")
        print(f"Резервная копия: {backup}")
    finally:
        if os.path.exists(new_db):
            os.remove(new_db)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Использование: python merge_and_build.py ПАПКА_С_JSON [data/laws.db]")
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "data", "laws.db"))
