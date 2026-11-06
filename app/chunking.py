"""Дробление длинных «статей» без номера (постановления, указы, приложения) на пункты или куски по длине.

Постановления делятся не на moddalar, а на пункты «1.», «2.» … и приложения. Если хранить их одной
статьёй, поиск находит огромный кусок, а модели уходит весь документ. Здесь такой текст режется:
  - по пунктам верхнего уровня («12. …», «12) …»), соседние короткие пункты склеиваются до ~1800 символов;
  - приложение (Ilova / Приложение) всегда начинает новый кусок;
  - если пунктов нет или пункт слишком длинный — по абзацам, ~1500 символов.
"""
import re

LONG = 2500          # длиннее — режем
TARGET = 1800        # примерный размер куска
HARD = 2400          # пункт длиннее — режем по абзацам
_POINT = re.compile(r"^\s*(\d{1,3})[.)]\s+\S")
_ANNEX = re.compile(r"^\s*(\d+[- ]?(son|сон)?\s*)?(ilova|илова|приложение)\b", re.I)


def _pieces(line, size):
    """Очень длинная строка (таблица, сплошной абзац) — режем по предложениям, в крайнем случае по пробелам."""
    if len(line) <= size:
        return [line]
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.;:!?])\s+", line):
        while len(sent) > size:
            cut = sent.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            parts.append((cur + " " + sent[:cut]).strip() if cur else sent[:cut]); cur = ""
            sent = sent[cut:].strip()
        if cur and len(cur) + len(sent) > size:
            parts.append(cur); cur = ""
        cur = (cur + " " + sent).strip()
    if cur:
        parts.append(cur)
    return parts


def _by_length(lines, size=1500):
    out, cur, n = [], [], 0
    lines = [p for l in lines for p in _pieces(l, size)]
    for l in lines:
        if cur and n + len(l) > size:
            out.append(cur); cur, n = [], 0
        cur.append(l); n += len(l) + 1
    if cur:
        out.append(cur)
    return out


def _segments(lines):
    """[(номер_пункта или None, признак_приложения, строки)]"""
    segs, cur, num, annex = [], [], None, False
    for l in lines:
        m = _POINT.match(l)
        a = bool(_ANNEX.match(l)) and len(l) < 200
        if (m or a) and cur:
            segs.append((num, annex, cur)); cur = []
        if a:
            num, annex = None, True
        elif m:
            num, annex = int(m.group(1)), False
        cur.append(l)
    if cur:
        segs.append((num, annex, cur))
    return segs


def _label(nums, lang):
    nums = [n for n in nums if n is not None]
    if not nums:
        return None
    a, b = nums[0], nums[-1]
    if lang == "ru":
        return f"пункт {a}" if a == b else f"пункты {a}–{b}"
    return f"{a}-band" if a == b else f"{a}–{b}-bandlar"


def split(text, lang, heading=""):
    """Возвращает список (заголовок_куска, метка_пункта_или_None, текст). Короткий текст — один кусок."""
    text = text or ""
    if len(text) <= LONG:
        return [(heading, None, text)]
    lines = [l for l in text.split("\n") if l.strip()]
    segs = _segments(lines)
    if sum(1 for n, _, _ in segs if n is not None) < 2:
        segs = [(None, False, ch) for ch in _by_length(lines)]
    chunks, cur, nums, size = [], [], [], 0
    state = {"annex": 0, "cur_annex": 0}

    def flush():
        if cur:
            chunks.append((list(nums), list(cur), state["cur_annex"]))

    for num, annex, ls in segs:
        seg_len = sum(len(l) + 1 for l in ls)
        if annex:
            flush(); cur, nums, size = [], [], 0
            state["annex"] += 1
            state["cur_annex"] = state["annex"]
        if seg_len > HARD:                       # длинный пункт — отдельно и по абзацам
            if cur:
                cur.extend(ls[:0])
            flush(); cur, nums, size = [], [], 0
            for part in _by_length(ls):
                chunks.append(([num], part, state["annex"]))
            continue
        if cur and not annex and size + seg_len > TARGET and size > 200:
            flush(); cur, nums, size = [], [], 0
        state["cur_annex"] = state["annex"]
        cur.extend(ls); nums.append(num); size += seg_len
    flush()

    out = []
    for i, (ns, ls, ann) in enumerate(chunks, 1):
        lab = _label(ns, lang)
        if ann:
            pre = (f"приложение {ann}" if lang == "ru" else f"{ann}-ilova")
            lab = f"{pre}, {lab}" if lab else pre
        suffix = lab or (f"часть {i}" if lang == "ru" else f"{i}-boʻlak")
        out.append((f"{heading} — {suffix}" if heading else suffix, lab, "\n".join(ls)))
    return out
