"""Определение языка вопроса и перевод узбекской кириллицы в латиницу (база хранит uz на латинице)."""
import re

_UZ_CYR_ONLY = set("ўқғҳЎҚҒҲ")
_CYR = re.compile(r"[а-яёўқғҳ]", re.I)
_LAT = re.compile(r"[a-z]", re.I)
_UZ_LAT_HINTS = re.compile(r"(o['ʻ‘’`]|g['ʻ‘’`]|\bsh|\bch|ning\b|lar\b|dagi\b|moddа|modda|qonun|kodeks|mumkin|qancha|necha|kerak)", re.I)
_RU_HINTS = re.compile(r"\b(что|как|какой|какая|какие|сколько|если|или|для|при|это|кодекс|закон|статья|ли)\b", re.I)
_UZ_CYR_HINTS = re.compile(r"(нинг\b|лар\b|даги\b|учун\b|қонун|модда|қанча|неча|керак|мумкин|бўл)", re.I)

_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "ʼ", "ы": "i", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "ў": "oʻ", "қ": "q", "ғ": "gʻ", "ҳ": "h",
}


def detect(text: str) -> str:
    """'uz-Latn', 'uz-Cyrl' или 'ru'."""
    cyr, lat = len(_CYR.findall(text)), len(_LAT.findall(text))
    if lat > cyr:
        return "uz-Latn"
    if any(c in _UZ_CYR_ONLY for c in text) or len(_UZ_CYR_HINTS.findall(text)) > len(_RU_HINTS.findall(text)):
        return "uz-Cyrl"
    return "ru"


def cyr_to_lat(text: str) -> str:
    out, prev = [], ""
    for ch in text:
        low = ch.lower()
        if low in _MAP:
            v = _MAP[low]
            # «е» в начале слова или после гласной -> «ye»
            if low == "е" and (not prev or not prev.isalpha() or prev.lower() in "аеёиоуўэюяъь"):
                v = "ye"
            if ch.isupper() and v:
                v = v[0].upper() + v[1:]
            out.append(v)
        else:
            out.append(ch)
        prev = ch
    return "".join(out)


def db_lang(language: str) -> str:
    return "ru" if language == "ru" else "uz"
