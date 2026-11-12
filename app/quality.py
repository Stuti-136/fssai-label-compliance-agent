"""L3/L6 metrics, computed without an LLM judge so they are reproducible and free.
(An LLM-judge / TruLens feedback function can be plugged in via `extra_scorers` in eval/run_eval.py.)

groundedness       = grounded atoms / atoms. Atoms: every citation (quote must be verbatim in the retrieved passage with
                     matching clause id) + every clause id and number asserted in the narrative summary.
context_relevance  = relevant retrieved passages / retrieved passages. Relevant = the clause grounds a rule that was
                     evaluated, a detected claim, or (offline) the scenario's gold clause.
faithfulness       = findings whose verdict is entailed by their cited text + request: re-derived independently
                     (claims: re-parse the cited quote and recompute; rules: re-run the checker) / findings.
hallucination_rate = asserted verdicts (met/unmet) that are unsupported (uncited or failing verification) or, offline,
                     contradict the gold status / asserted verdicts.
"""
from __future__ import annotations
import re
from . import claims as C, rules
from .verifier import norm, verify_summary


def _ev(bundle_passages):
    return bundle_passages


def score(result: dict, bundle: dict, request: dict, gold: dict | None = None) -> dict:
    ev = bundle["passages"]
    fs = result.get("findings", [])
    atoms = ok = 0
    for f in fs:
        for c in f["citations"]:
            atoms += 1
            p = ev.get(c["chunk_id"])
            ok += bool(p and p["clause_id"] == c["clause_id"] and c["quote"] and norm(c["quote"]) in norm(p["text"]))
    summ = result.get("summary") or ""
    if summ and result.get("summary_source") == "llm":
        atoms += 1
        ok += verify_summary(summ, result["route"], ev, fs, request)
    groundedness = ok / atoms if atoms else 1.0

    ref_clauses = {r.clause for r in rules.RULES} | {c.get("schedule") or c.get("support") for c in bundle["claims"]}
    if bundle["claims"]:
        ref_clauses |= set(rules.CLAIM_GENERAL) | {"ACR-2018:Schedule I/NRV", "LDR-2020:Reg 4"}
    if gold:
        ref_clauses |= set(gold.get("gold_clauses", []))
    def rel(p):
        return any(p["clause_id"] == c or p["clause_id"].startswith(str(c) + "/") for c in ref_clauses)
    ps = list(ev.values())
    context_relevance = sum(rel(p) for p in ps) / len(ps) if ps else 0.0

    verdict = [f for f in fs if f["status"] in ("met", "unmet")]
    faithful = 0
    for f in verdict:
        good = False
        if f["kind"] == "claim":
            cl = next((c for c in bundle["claims"] if f["id"] == "CLAIM:" + c["key"]), None)
            if cl and f["citations"]:
                cits = [{"chunk_id": c["chunk_id"], "doc_id": c["doc_id"], "clause_id": c["clause_id"], "text": c["quote"]} for c in f["citations"]]
                conds = C.extract_conditions(cits, cl)
                nrv = C.extract_nrv(cits, cl["nutrient"])
                if conds:
                    good = C.evaluate_claim(cl, request, conds, nrv)["status"] == f["status"]
        else:
            r = next((r for r in rules.RULES if r.id == f["id"]), None)
            good = bool(r and f["citations"] and r.check(request)[0] == f["status"])
        faithful += good
    faithfulness = faithful / len(verdict) if verdict else 1.0

    bad = 0
    for f in verdict:
        p_ok = f["citations"] and all((ev.get(c["chunk_id"]) and norm(c["quote"]) in norm(ev[c["chunk_id"]]["text"])) for c in f["citations"])
        contradict = bool(gold and f["id"] in gold.get("statuses", {}) and gold["statuses"][f["id"]] != f["status"])
        bad += (not p_ok) or contradict
    hallucination_rate = bad / len(verdict) if verdict else 0.0
    return {"groundedness": round(groundedness, 4), "context_relevance": round(context_relevance, 4),
            "faithfulness": round(faithfulness, 4), "hallucination_rate": round(hallucination_rate, 4)}
