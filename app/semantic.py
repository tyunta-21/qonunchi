"""Смысловой поиск: векторы статей (multilingual-e5-small, ONNX через fastembed, без ключей и без GPU).

Векторы считает build_embeddings.py и кладёт рядом с базой: data/emb_<lang>.npy (float16) и data/emb_<lang>_ids.npy.
Если fastembed не установлен или файлов нет, поиск просто работает без смысловой части.
"""
import os, re, threading

MODEL = os.environ.get("EMB_MODEL", "Xenova/multilingual-e5-small")
MODEL_FILE = os.environ.get("EMB_MODEL_FILE", "onnx/model_quantized.onnx")
DIM = 384
MAX_CHARS = 1500           # ~512 токенов модели
_lock = threading.Lock()
_model = None
_index = {}
_disabled = os.environ.get("SEMANTIC", "1") == "0"


def data_dir(db_path):
    return os.path.dirname(os.path.abspath(db_path))


def model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        from fastembed.common.model_description import PoolingType, ModelSource
        try:
            TextEmbedding.add_custom_model(model=MODEL, pooling=PoolingType.MEAN, normalization=True,
                                           sources=ModelSource(hf=MODEL), dim=DIM, model_file=MODEL_FILE)
        except ValueError:
            pass   # уже зарегистрирована
        _model = TextEmbedding(MODEL, cache_dir=os.environ.get("EMB_CACHE"))
    return _model


def passage_text(title, heading, text):
    t = re.sub(r"\[(Примечание|Izoh)[^\]]*\]", " ", text or "")
    return ("passage: " + " ".join(x for x in (title, heading, t) if x))[:MAX_CHARS]


def _load(lang, db_path):
    import numpy as np
    d = data_dir(db_path)
    p, pi = os.path.join(d, f"emb_{lang}.npy"), os.path.join(d, f"emb_{lang}_ids.npy")
    if not (os.path.exists(p) and os.path.exists(pi)):
        return None
    return np.load(p).astype("float32"), np.load(pi)


def search(query, lang, db_path, k=20):
    """[(id статьи, косинусная близость)] — k ближайших статей. Пусто, если смысловой поиск недоступен."""
    global _disabled
    if _disabled or not query:
        return []
    try:
        with _lock:
            if lang not in _index:
                _index[lang] = _load(lang, db_path)
            idx = _index[lang]
            if idx is None:
                return []
            import numpy as np
            q = np.asarray(next(iter(model().embed(["query: " + query]))), dtype="float32")
        mat, ids = idx
        sims = mat @ q
        top = np.argpartition(-sims, min(k, len(sims) - 1))[:k]
        top = top[np.argsort(-sims[top])]
        return [(int(ids[i]), float(sims[i])) for i in top]
    except Exception as e:   # нет fastembed / модели — продолжаем без смысловой части
        print("semantic search disabled:", repr(e))
        _disabled = True
        return []
