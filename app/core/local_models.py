"""Local model utilities: embeddings (sentence-transformers) + flan-t5-small generation."""
from typing import List
import threading
import numpy as np

_embed_lock = threading.Lock()
_gen_lock = threading.Lock()

_embed_model = None
_gen_tokenizer = None
_gen_model = None
_gen_pipeline = None


def _load_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    return _embed_model


def _load_gen_model():
    global _gen_tokenizer, _gen_model, _gen_pipeline
    if _gen_pipeline is None:
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        _gen_tokenizer = AutoTokenizer.from_pretrained('google/flan-t5-small')
        _gen_model = AutoModelForSeq2SeqLM.from_pretrained('google/flan-t5-small')
        _gen_pipeline = True
    return _gen_pipeline


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Return embeddings for a list of texts using sentence-transformers."""
    with _embed_lock:
        model = _load_embed_model()
        emb = model.encode(texts, convert_to_numpy=True)
        # ensure float32
        return [e.astype('float32').tolist() for e in emb]


def build_faiss_index(embeddings: List[List[float]]):
    """Create a FAISS IndexFlatL2 and add embeddings. Returns (index, np_array).
    """
    import faiss
    arr = np.array(embeddings).astype('float32')
    dim = arr.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(arr)
    return index, arr


def search_faiss(index, arr, query_embedding: List[float], top_k: int = 5):
    import numpy as _np
    q = _np.array(query_embedding).astype('float32').reshape(1, -1)
    D, I = index.search(q, top_k)
    return I[0].tolist(), D[0].tolist()


def generate_answer(prompt: str, max_length: int = 256) -> str:
    """Generate answer using flan-t5-small via transformers pipeline."""
    with _gen_lock:
        _load_gen_model()
        try:
            import torch
        except Exception:
            raise
        _gen_model.to('cpu')
        inputs = _gen_tokenizer(prompt, return_tensors='pt', truncation=True)
        input_device_inputs = {k: v.to('cpu') for k, v in inputs.items()}
        with torch.no_grad():
            outputs = _gen_model.generate(**input_device_inputs, max_length=max_length, do_sample=False)
        if outputs is None or len(outputs) == 0:
            return ''
        return _gen_tokenizer.decode(outputs[0], skip_special_tokens=True)
