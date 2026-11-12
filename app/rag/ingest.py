"""D2: idempotent corpus pipeline  read -> parse -> chunk -> embed -> index, from the CLI.

  python -m app.rag.ingest [--corpus DIR] [--out DIR] [--reembed] [--reembed-doc DOC_ID]

* Idempotent: chunk ids and content hashes are deterministic; an unchanged corpus+embedder is a no-op.
* Incremental re-embedding (L1): vectors are cached by (content_hash, embedder id). Changing the embedder or a
  document re-embeds only the stale chunks; the FAISS index is then rebuilt from stored vectors (milliseconds).
* Freshness (D2): index_meta.json records build time, document versions + hashes, chunk count, throughput.
"""
from __future__ import annotations
import argparse, hashlib, json, logging, os, shutil, sys, time
from pathlib import Path
import numpy as np
from langchain_community.vectorstores import FAISS
from ..config import get_settings
from ..logging_setup import setup_logging, log
from .chunking import parse_file
from .embedders import make_embedder

logger = logging.getLogger("ingest")


def _load_prev(out: Path):
    try:
        chunks = [json.loads(l) for l in (out / "chunks.jsonl").read_text().splitlines()]
        vecs = np.load(out / "vectors.npy")
        meta = json.loads((out / "index_meta.json").read_text())
        return chunks, vecs, meta
    except Exception:
        return [], None, {}


def run_ingest(corpus: str | None = None, out: str | None = None, reembed: bool = False,
               reembed_doc: str | None = None) -> dict:
    s = get_settings()
    corpus_dir, out_dir = Path(corpus or s.corpus_dir), Path(out or s.index_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t_all = time.perf_counter()
    files = sorted(p for p in corpus_dir.iterdir() if p.suffix in (".md", ".txt", ".pdf") and p.name != "README.md")
    if not files:
        raise SystemExit(f"no corpus files in {corpus_dir}")
    chunks, docs = [], {}
    for f in files:
        cs = parse_file(f)
        if not cs:
            raise SystemExit(f"{f.name}: parsed 0 chunks")
        chunks += cs
        docs[cs[0].doc_id] = {"file": f.name, "version": cs[0].doc_version, "title": cs[0].doc_title,
                              "sha256": hashlib.sha256(f.read_bytes()).hexdigest(), "chunks": len(cs)}
    emb = make_embedder()
    eid = getattr(emb, "id", "unknown")
    version = hashlib.sha1((eid + "|" + "|".join(sorted(c.content_hash for c in chunks))).encode()).hexdigest()[:12]
    prev_chunks, prev_vecs, prev_meta = _load_prev(out_dir)
    if prev_meta.get("index_version") == version and not reembed and not reembed_doc \
            and (out_dir / "faiss" / "index.faiss").exists():
        prev_meta["last_checked_at"] = time.time()
        (out_dir / "index_meta.json").write_text(json.dumps(prev_meta, indent=2))
        log(logger, "index unchanged; no-op", version=version)
        return {**prev_meta, "noop": True}

    cache = {}
    if prev_vecs is not None and prev_meta.get("embedder") == eid and not reembed:
        for pc, v in zip(prev_chunks, prev_vecs):
            if reembed_doc and pc["doc_id"] == reembed_doc:
                continue
            cache[pc["content_hash"]] = v
    todo = [c for c in chunks if c.content_hash not in cache]
    t_emb = time.perf_counter()
    if todo:
        new = emb.embed_documents([c.embed_text for c in todo])
        for c, v in zip(todo, new):
            cache[c.content_hash] = np.asarray(v, dtype="float32")
    emb_s = max(time.perf_counter() - t_emb, 1e-9)
    vecs = np.vstack([cache[c.content_hash] for c in chunks]).astype("float32")

    tmp = out_dir / ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    vs = FAISS.from_embeddings([(c.embed_text, vecs[i].tolist()) for i, c in enumerate(chunks)], emb,
                               metadatas=[c.to_dict() for c in chunks], ids=[c.chunk_id for c in chunks])
    vs.save_local(str(tmp / "faiss"))
    np.save(tmp / "vectors.npy", vecs)
    (tmp / "chunks.jsonl").write_text("\n".join(json.dumps(c.to_dict()) for c in chunks))
    total_s = time.perf_counter() - t_all
    meta = {"index_version": version, "built_at": time.time(), "last_checked_at": time.time(), "embedder": eid,
            "chunks": len(chunks), "chunks_embedded_this_run": len(todo), "documents": docs,
            "embed_seconds": round(emb_s, 3), "total_seconds": round(total_s, 3),
            "throughput_chunks_per_s": round(len(chunks) / total_s, 2), "retrieval_ready": True}
    (tmp / "index_meta.json").write_text(json.dumps(meta, indent=2))
    for name in ("faiss", "vectors.npy", "chunks.jsonl", "index_meta.json"):  # swap in; meta last = readiness marker
        dst = out_dir / name
        if dst.is_dir():
            shutil.rmtree(dst)
        elif dst.exists():
            dst.unlink()
        shutil.move(str(tmp / name), str(dst))
    shutil.rmtree(tmp, ignore_errors=True)
    check_rule_clauses(chunks)
    log(logger, "index built", **{k: meta[k] for k in ("index_version", "chunks", "chunks_embedded_this_run", "embedder")})
    return meta


def check_rule_clauses(chunks) -> list[str]:
    """Warn when a clause id referenced by the rule catalogue / claim catalogue is absent from the index."""
    from ..rules import all_referenced_clauses
    have = {c.clause_id for c in chunks}
    missing = [c for c in all_referenced_clauses() if not any(h == c or h.startswith(c + "/") for h in have)]
    for m in missing:
        log(logger, "RULE CLAUSE MISSING FROM INDEX - update app/rules.py or the corpus", logging.WARNING, clause=m)
    return missing


if __name__ == "__main__":
    setup_logging("indexer")
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus"), ap.add_argument("--out")
    ap.add_argument("--reembed", action="store_true", help="re-embed every chunk (e.g. new embedding model)")
    ap.add_argument("--reembed-doc", help="re-embed only this doc id")
    a = ap.parse_args()
    print(json.dumps(run_ingest(a.corpus, a.out, a.reembed, a.reembed_doc), indent=2))
