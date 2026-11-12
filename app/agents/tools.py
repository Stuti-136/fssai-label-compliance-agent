"""Agent tools (A1): search_corpus, lookup_clause, get_request_field, extract_cross_references.
Every call is budgeted, traced and (for search) cached."""
from __future__ import annotations
import hashlib, json, re, time
from .. import obs


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, max_steps: int, max_tool_calls: int, deadline_s: float):
        self.max_steps, self.max_tools, self.deadline = max_steps, max_tool_calls, time.monotonic() + deadline_s
        self.steps = self.tools = 0

    def check(self):
        if self.steps >= self.max_steps:
            raise BudgetExceeded(f"step budget {self.max_steps} exhausted")
        if self.tools >= self.max_tools:
            raise BudgetExceeded(f"tool-call budget {self.max_tools} exhausted")
        if time.monotonic() > self.deadline:
            raise BudgetExceeded("wall-clock budget exhausted")

    def tick(self, tool=False):
        self.steps += 1
        self.tools += 1 if tool else 0


REF_RE = re.compile(r"\b(Schedule [IVX]+|Regulation \d+(?:\(\d+\))?|Reg\.? \d+(?:\(\d+\))?)", re.I)


class ToolBox:
    def __init__(self, index, request: dict, rec, budget: Budget, redis=None, use_cache=True):
        self.index, self.request, self.rec, self.budget, self.r, self.use_cache = index, request, rec, budget, redis, use_cache

    def _run(self, name, inputs, fn):
        self.budget.check()
        self.budget.tick(tool=True)
        with self.rec.step("tool", name, inputs) as st:
            out = fn()
            ps = out.get("passages", [])
            st.set(passage_ids=[p["chunk_id"] for p in ps], clause_ids=[p["clause_id"] for p in ps],
                   n=len(ps), **{k: v for k, v in out.items() if k not in ("passages",)})
            return out

    def search_corpus(self, query: str, mode: str = "hybrid", doc_id: str | None = None, k: int = 5) -> dict:
        def fn():
            key = None
            if self.r is not None and self.use_cache:
                key = "rc:%s:%s" % (self.index.version, hashlib.sha1(f"{query}|{mode}|{doc_id}|{k}".encode()).hexdigest())
                hit = self.r.get(key)
                obs.CACHE.labels("retrieval", "hit" if hit else "miss").inc()
                if hit:
                    return {"passages": [self.index._pass(c, score=s, mode=mode) for c, s in json.loads(hit)], "cache": "hit"}
            ps = self.index.search(query, mode, doc_id, k)
            if key:
                self.r.set(key, json.dumps([[p["chunk_id"], p["score"]] for p in ps]), ex=3600)
            return {"passages": ps, "cache": "miss"}
        return self._run("search_corpus", {"query": query, "mode": mode, "doc_id": doc_id, "k": k}, fn)

    def lookup_clause(self, refs: list[str]) -> dict:
        def fn():
            ps, missing = [], []
            for ref in refs:
                hit = self.index.lookup(ref)
                (ps.extend(hit) if hit else missing.append(ref))
            return {"passages": ps, "missing": missing}
        return self._run("lookup_clause", {"refs": refs}, fn)

    def get_request_field(self, path: str) -> dict:
        def fn():
            v = self.request
            for part in path.split("."):
                v = v.get(part) if isinstance(v, dict) else None
            return {"passages": [], "path": path, "value": v}
        return self._run("get_request_field", {"path": path}, fn)

    def extract_cross_references(self, passages: list[dict]) -> dict:
        def fn():
            refs = []
            for p in passages:
                doc = p["doc_id"]
                for m in REF_RE.findall(p["text"]):
                    m = re.sub(r"^(Regulation|Reg\.?)\s*", "Reg ", m, flags=re.I)
                    ref = f"{doc}:{m[0].upper() + m[1:] if m.lower().startswith('schedule') else m}"
                    if ref != p["clause_id"] and ref not in refs:
                        refs.append(ref)
            return {"passages": [], "refs": refs}
        return self._run("extract_cross_references", {"chunks": [p["chunk_id"] for p in passages]}, fn)
