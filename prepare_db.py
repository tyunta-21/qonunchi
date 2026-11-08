"""Добавляет в базу маленькую таблицу art_map(id, key, lang).

Поиск сортирует тысячи совпадений, и раньше для каждого читал строку из большой таблицы
articles (~770 МБ с текстами). На медленном диске хостинга это десятки секунд.
С art_map сортировка идёт по таблице в ~3 МБ, а тексты читаются только для top-N.
Запуск: python prepare_db.py data/laws.db   (повторный запуск ничего не меняет)
"""
import sqlite3, sys

path = sys.argv[1] if len(sys.argv) > 1 else "data/laws.db"
c = sqlite3.connect(path)
if not c.execute("SELECT 1 FROM sqlite_master WHERE name='art_map'").fetchone():
    c.execute("CREATE TABLE art_map(id INTEGER PRIMARY KEY, key INTEGER, lang TEXT)")
    c.execute("INSERT INTO art_map SELECT id, key, lang FROM articles")
    c.commit()
print("art_map:", c.execute("SELECT count(*) FROM art_map").fetchone()[0])
c.close()
