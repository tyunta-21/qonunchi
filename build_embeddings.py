#!/usr/bin/env python3
"""Считает векторы статей для смыслового поиска (один раз после build_db.py).

  pip install fastembed numpy
  python build_embeddings.py [data/laws.db] [uz ru]

~5 минут на язык на обычном 4-ядерном процессоре. Модель (~120 МБ) скачивается сама с Hugging Face.
"""
import os, sqlite3, sys, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import semantic


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "laws.db")
    langs = sys.argv[2:] or ["uz", "ru"]
    c = sqlite3.connect(db_path)
    m = semantic.model()
    for lang in langs:
        rows = c.execute("SELECT a.id, d.title, a.heading, a.text FROM articles a JOIN docs d ON d.key=a.key AND d.lang=a.lang "
                         "WHERE a.lang=? AND d.active=1 ORDER BY a.id", (lang,)).fetchall()
        t0 = time.time()
        texts = [semantic.passage_text(t, h, x) for _, t, h, x in rows]
        vecs = np.zeros((len(texts), semantic.DIM), dtype="float16")
        for i, v in enumerate(m.embed(texts, batch_size=32)):
            vecs[i] = v
            if i % 5000 == 0:
                print(lang, i, "/", len(texts), f"{time.time() - t0:.0f}s", flush=True)
        d = semantic.data_dir(db_path)
        np.save(os.path.join(d, f"emb_{lang}.npy"), vecs)
        np.save(os.path.join(d, f"emb_{lang}_ids.npy"), np.array([r[0] for r in rows], dtype="int64"))
        print(lang, len(rows), "статей,", f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
