"""A3: every citation must resolve to retrieved text; numbers in claim findings must come from cited text."""
from __future__ import annotations
import re
from . import obs

STATUSES = {"met", "unmet", "needs_human", "not_applicable"}


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", t.lower()).strip()


def _num_in(n, text: str) -> bool:
    s = str(int(n)) if float(n).is_integer() else str(n)
    return re.search(r"(?<![\d.])" + re.escape(s) + r"(?![\d])", text) is not None


def verify_findings(findings: list[dict], evidence: dict, request: dict) -> list[dict]:
    fails = []
    for f in findings:
        fid = f["id"]
        if f["status"] not in STATUSES:
            fails.append({"finding_id": fid, "code": "bad_status", "message": f["status"]})
            continue
        if f["status"] in ("met", "unmet") and not f["citations"]:
            fails.append({"finding_id": fid, "code": "uncited_verdict", "message": "verdict without citation", "clause_id": f.get("clause_ref")})
        joined = ""
        for c in f["citations"]:
            p = evidence.get(c.get("chunk_id"))
            if not p:
                fails.append({"finding_id": fid, "code": "citation_not_retrieved", "clause_id": c.get("clause_id"),
                              "message": f"chunk {c.get('chunk_id')} was not retrieved"})
                continue
            if p["clause_id"] != c.get("clause_id"):
                fails.append({"finding_id": fid, "code": "clause_mismatch", "clause_id": c.get("clause_id"),
                              "message": "citation clause differs from retrieved chunk"})
            if norm(c.get("quote", "")) not in norm(p["text"]) or not c.get("quote"):
                fails.append({"finding_id": fid, "code": "quote_not_in_passage", "clause_id": c.get("clause_id"),
                              "message": "quoted text does not appear in the retrieved passage"})
            joined += " " + p["text"]
        comp = f.get("computed") or {}
        if f.get("kind") == "claim" and f["status"] in ("met", "unmet"):
            nut = f.get("nutrient")
            if comp.get("declared") is not None and (request.get("nutrition") or {}).get(nut) != comp["declared"]:
                fails.append({"finding_id": fid, "code": "declared_value_mismatch", "message": "declared value differs from request"})
            for key in ("pct_nrv", "nrv_g", "limit"):
                if key in comp and not _num_in(comp[key], joined):
                    fails.append({"finding_id": fid, "code": "number_not_in_citations", "message": f"{key}={comp[key]} not found in cited text"})
    obs.VERIFY.labels("fail" if fails else "pass").inc()
    return fails


def verify_summary(summary: str, route: str, evidence: dict, findings: list[dict], request: dict) -> bool:
    """LLM narrative is accepted only if it names the route, and every clause id / number in it is grounded."""
    if route.lower() not in summary.lower():
        return False
    allowed_clauses = {p["clause_id"] for p in evidence.values()}
    for m in re.findall(r"(?:LDR|ACR)-\d{4}:[A-Za-z0-9 ()/.]+?(?=[,.;:)\s]|$)", summary):
        if not any(a == m.strip() or a.startswith(m.strip()) for a in allowed_clauses):
            return False
    pool = " ".join(p["text"] for p in evidence.values()) + " " + str(request) + " " + str([f.get("computed") for f in findings]) + " " + " ".join(f["detail"] for f in findings)
    for n in re.findall(r"(?<![\w:])\d+(?:\.\d+)?", re.sub(r"(?:LDR|ACR)-\d{4}:[^\s,;]+", "", summary)):
        if not re.search(r"(?<![\d.])" + re.escape(n) + r"(?![\d])", pool):
            return False
    return True
