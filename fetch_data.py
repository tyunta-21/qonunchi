"""Скачивает базу законов и смысловой индекс из GitHub Release (для Dockerfile.server).

  python fetch_data.py https://github.com/tyunta-21/qonunchi/releases/download/db-v1 data
Файлов индекса emb_*.npy в релизе может не быть: тогда сайт работает без смыслового поиска.
"""
import os, sqlite3, sys, urllib.request

rel, out = sys.argv[1].rstrip("/"), sys.argv[2] if len(sys.argv) > 2 else "data"
os.makedirs(out, exist_ok=True)
urllib.request.urlretrieve(rel + "/laws.db", os.path.join(out, "laws.db"))
n = sqlite3.connect(os.path.join(out, "laws.db")).execute("select count(*) from docs").fetchone()[0]
print("laws.db:", n, "документов")
for f in ("emb_uz.npy", "emb_uz_ids.npy", "emb_ru.npy", "emb_ru_ids.npy"):
    try:
        urllib.request.urlretrieve(f"{rel}/{f}", os.path.join(out, f))
        print("ok", f)
    except Exception as e:
        print("нет", f, "- смысловой поиск для этого языка будет выключен:", e)
