"""Embedding backends behind LangChain's Embeddings interface. Local only (no paid API)."""
from __future__ import annotations
import logging, re, threading, zlib
from functools import lru_cache
import numpy as np
from langchain_core.embeddings import Embeddings
from ..config import get_settings

logger = logging.getLogger(__name__)


class HashEmbeddings(Embeddings):
    """Dependency-free hashing bag-of-words(+bigrams) embedder. Fallback and test backend."""
    dim = 512
    id = "hash-512"

    def _v(self, text: str) -> list[float]:
        toks = re.findall(r"[a-z0-9]+", text.lower())
        grams = toks + [a + "_" + b for a, b in zip(toks, toks[1:])]
        v = np.zeros(self.dim, dtype="float32")
        for g in grams:
            h = zlib.crc32(g.encode())
            v[h % self.dim] += 1.0 if (h >> 16) & 1 else -1.0 if False else 1.0
        v = np.sqrt(v)
        n = np.linalg.norm(v)
        return (v / n if n else v).tolist()

    def embed_documents(self, texts):
        return [self._v(t) for t in texts]

    def embed_query(self, text):
        return self._v(text)


class STEmbeddings(Embeddings):
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer
        self.m = SentenceTransformer(model_name)
        self.id = f"st:{model_name}"
        self.lock = threading.Lock()

    def embed_documents(self, texts):
        with self.lock:
            return self.m.encode(list(texts), normalize_embeddings=True, batch_size=32).tolist()

    def embed_query(self, text):
        return self.embed_documents([text])[0]


@lru_cache
def make_embedder() -> Embeddings:
    s = get_settings()
    if s.embedding_backend == "st" and s.embedding_model:
        try:
            return STEmbeddings(s.embedding_model)
        except Exception as e:  # graceful degradation: keep serving with the hash embedder (index records which one)
            logger.warning("sentence-transformers unavailable (%r); falling back to hash embedder", e)
    return HashEmbeddings()
