"""Query side of the index: semantic (LangChain FAISS), lexical (BM25) and hybrid (RRF) search + clause lookup."""
from __future__ import annotations
import json, math, re, threading, time
from collections import Counter
from functools import lru_cache
from pathlib import Path
from langchain_community.vectorstores import FAISS
from ..config import get_settings
from .embedders import make_embedder


def _tok(t: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", t.lower())


class CorpusIndex:
    def __init__(self, index_dir: str | None = None):
        self.dir = Path(index_dir or get_settings().index_dir)
        self.lock = threading.RLock()
        self._mtime = 0.0
        self.meta, self.chunks, self.vs = {}, {}, None
        self.load()

    def load(self):
        with self.lock:
            mp = self.dir / "index_meta.json"
            self.meta = json.loads(mp.read_text())
            self._mtime = mp.stat().st_mtime
            self.emb = make_embedder()
            if getattr(self.emb, "id", None) != self.meta["embedder"]:
                raise RuntimeError(f"index built with {self.meta['embedder']} but runtime embedder is "
                                   f"{self.emb.id}; re-run ingest")
            rows = [json.loads(l) for l in (self.dir / "chunks.jsonl").read_text().splitlines()]
            self.chunks = {r["chunk_id"]: r for r in rows}
            self.vs = FAISS.load_local(str(self.dir / "faiss"), self.emb, allow_dangerous_deserialization=True)
            self._build_bm25()

    def reload_if_changed(self):
        try:
            if (self.dir / "index_meta.json").stat().st_mtime != self._mtime:
                self.load()
        except FileNotFoundError:
            pass

    @property
    def version(self) -> str:
        return self.meta.get("index_version", "none")

    def _build_bm25(self):
        self.ids = list(self.chunks)
        self.docs = [Counter(_tok(c["title"] + " " + c["title"] + " " + c["clause"] + " " + c["text"]))
                     for c in self.chunks.values()]
        self.dl = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.dl) / max(len(self.dl), 1)
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + .5) / (f + .5)) for t, f in df.items()}

    def _pass(self, cid, **extra):
        c = self.chunks[cid]
        return {"chunk_id": cid, "doc_id": c["doc_id"], "clause_id": c["clause_id"], "title": c["title"],
                "text": c["text"], **extra}

    @lru_cache(maxsize=512)
    def _qvec(self, q: str):  # embedding cache (D7)
        return tuple(self.emb.embed_query(q))

    def semantic(self, q: str, k: int, doc_id: str | None):
        flt = {"doc_id": doc_id} if doc_id else None
        res = self.vs.similarity_search_with_score_by_vector(list(self._qvec(q)), k=k, filter=flt,
                                                             fetch_k=max(len(self.chunks), k))
        return [(d.metadata["chunk_id"], 1 - float(s) / 2) for d, s in res]

    def lexical(self, q: str, k: int, doc_id: str | None):
        qt = _tok(q)
        out = []
        for i, cid in enumerate(self.ids):
            if doc_id and self.chunks[cid]["doc_id"] != doc_id:
                continue
            d, sc = self.docs[i], 0.0
            for t in set(qt):
                f = d.get(t, 0)
                if f:
                    sc += self.idf.get(t, 0) * f * 2.5 / (f + 1.5 * (.25 + .75 * self.dl[i] / self.avg))
            if sc > 0:
                out.append((cid, sc))
        return sorted(out, key=lambda x: -x[1])[:k]

    def search(self, q: str, mode: str = "hybrid", doc_id: str | None = None, k: int = 5) -> list[dict]:
        self.reload_if_changed()
        with self.lock:
            if mode == "semantic":
                return [self._pass(c, score=round(s, 4), mode=mode) for c, s in self.semantic(q, k, doc_id)]
            if mode == "lexical":
                return [self._pass(c, score=round(s, 4), mode=mode) for c, s in self.lexical(q, k, doc_id)]
            fused: dict[str, float] = {}
            for lst in (self.semantic(q, 20, doc_id), self.lexical(q, 20, doc_id)):
                for r, (c, _) in enumerate(lst):
                    fused[c] = fused.get(c, 0) + 1 / (60 + r)
            top = sorted(fused.items(), key=lambda x: -x[1])[:k]
            return [self._pass(c, score=round(s, 4), mode="hybrid") for c, s in top]

    def lookup(self, ref: str) -> list[dict]:
        """Exact 'DOC:Clause' or prefix 'DOC:Schedule I' (matches 'DOC:Schedule I/Protein'). Case-insensitive."""
        self.reload_if_changed()
        r = ref.strip().lower()
        with self.lock:
            hits = [cid for cid, c in self.chunks.items()
                    if c["clause_id"].lower() == r or c["clause_id"].lower().startswith(r + "/")]
            return [self._pass(c, score=1.0, mode="lookup") for c in hits]


_idx: CorpusIndex | None = None
_l = threading.Lock()


def get_index() -> CorpusIndex:
    global _idx
    with _l:
        if _idx is None:
            _idx = CorpusIndex()
        return _idx
