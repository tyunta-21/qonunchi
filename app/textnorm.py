"""Нормализация текста для поиска (узбекская латиница/кириллица и русский)."""
import re

_APOS = dict.fromkeys(map(ord, "ʻʼ‘’`'´ʹ"), None)
_WORD = re.compile(r"\w+", re.UNICODE)

STOP = set("""и в во на не что как по к ко из у за о об от до для с со а но или ли же бы это то
тот та те при сколько какой какая какое какие каков положено положен должен должна могу может мож нужен надо если ли разве почему зачем без над под между про чем где когда если можно нужно ли мне меня мой моя я ты вы мы он она они
kora boyicha haqida qayerda hali hozir degan deb necha qancha qaysi qanday nega kerakmi mumkinmi boʻladi bo'ladi boladi ва ҳам ham bilan uchun va yoki emas bu shu qanday nima qachon kim mumkin kerak men biz siz u ular edi
""".split())


def norm(text: str) -> str:
    """Нижний регистр, убираем апострофы (oʻzbek -> ozbek), ё -> е."""
    return (text or "").lower().translate(_APOS).replace("ё", "е")


def terms(query: str, limit: int = 12):
    out = []
    for w in _WORD.findall(norm(query)):
        if w in STOP or len(w) < 2:
            continue
        if w.isdigit():
            out.append(w)
            continue
        # грубый «стемминг»: обрезаем окончание и ищем по префиксу
        if len(w) >= 5:
            w = w[: max(4, len(w) - 3)]
        out.append(w)
    seen, res = set(), []
    for w in out:
        if w not in seen:
            seen.add(w); res.append(w)
    return res[:limit]


def fts_query(query: str, mode: str = "OR"):
    ts = terms(query)
    if not ts:
        return None
    parts = [f'"{t}"*' if not t.isdigit() else f'"{t}"' for t in ts]
    return f" {mode} ".join(parts)
