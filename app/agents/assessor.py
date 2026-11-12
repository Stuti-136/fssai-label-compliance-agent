r"""Agent 2 - ASSESSOR (LangGraph). Responsibility: turn the evidence bundle into findings, VERIFY them against the
retrieved passages, route, and narrate. Separate process/queue from the researcher; the only hand-off is the
EvidenceBundle (see docs/ARCHITECTURE.md).

  draft -> verify --ok--> route -> narrate
              \--fail, attempts left--> repair (different strategy: exact clause lookup / lexical search) -> draft
              \--fail, no attempts--> escalate -> narrate
"""
from __future__ import annotations
import re, logging
from typing import TypedDict, Any
from langgraph.graph import StateGraph, END
from .. import claims as C, rules, prompts, guardrails
from ..config import get_settings
from ..llm import LLMUnavailable, parse_json_loose
from ..runs import DISCLAIMER
from ..verifier import verify_findings, verify_summary
from .tools import ToolBox, BudgetExceeded

logger = logging.getLogger("assessor")
MAX_REPAIRS = 1
FAKE_QUOTE = "The label may be printed without any nutrition declaration."


class AState(TypedDict, total=False):
    findings: list
    failures: list
    attempt: int
    route: str
    reason: str
    escalations: list
    forced: str
    summary: str
    summary_source: str
    degraded: str | None


def best_sentence(text: str, keywords: list[str]) -> str:
    sents = [s.strip() for s in re.split(r"(?<=[.;])\s+|\n", text) if s.strip()]
    def score(s):
        return sum(1 for k in keywords if k.lower() in s.lower())
    return max(sents, key=score) if sents else text[:200]


def cite(p: dict, quote: str) -> dict:
    return {"doc_id": p["doc_id"], "clause_id": p["clause_id"], "chunk_id": p["chunk_id"], "quote": quote}


def by_clause(evidence: dict, clause_id: str) -> list[dict]:
    return [p for p in evidence.values() if p["clause_id"] == clause_id or p["clause_id"].startswith(clause_id + "/")]


def draft_findings(req: dict, bundle: dict, evidence: dict) -> list[dict]:
    out = []
    for r in rules.RULES:
        status, detail = r.check(req)
        ps = by_clause(evidence, r.clause)
        if r.id == "R13_small_pack":
            if not ps:
                if req["package_surface_area_cm2"] < 100:
                    out.append({"id": r.id, "kind": "rule", "title": r.title, "status": "needs_human", "clause_ref": r.clause,
                                "detail": "Package surface area is under 100 cm2 but the exemption provision was not retrieved; human review required.",
                                "citations": []})
                continue
            m = re.search(r"less than\s+(\d+)\s+square", ps[0]["text"], re.I)
            thr = float(m.group(1)) if m else 100.0
            if req["package_surface_area_cm2"] < thr:
                out.append({"id": r.id, "kind": "rule", "title": r.title, "status": "needs_human", "clause_ref": r.clause,
                            "detail": f"Package surface area {req['package_surface_area_cm2']} cm2 is below {thr:g} cm2, so a small-package exemption may apply to some declarations. The provision leaves applicability to the analyst or authority.",
                            "citations": [cite(ps[0], best_sentence(ps[0]["text"], r.keywords))]})
            continue
        f = {"id": r.id, "kind": "rule", "title": r.title, "status": status, "detail": detail, "clause_ref": r.clause, "citations": []}
        if status == "not_applicable":
            if ps:
                f["citations"] = [cite(ps[0], best_sentence(ps[0]["text"], r.keywords))]
        elif ps:
            f["citations"] = [cite(ps[0], best_sentence(ps[0]["text"], r.keywords))]
        else:
            f["status"], f["detail"] = "needs_human", detail + " (No supporting provision was retrieved, so no determination is made.)"
        out.append(f)
    # ---- claims: one finding each, citing the claims regulation AND the labelling regulation
    for cl in bundle["claims"]:
        fid = f"CLAIM:{cl['key']}"
        base = {"id": fid, "kind": "claim", "title": f"Claim \"{cl['claim_text']}\"", "nutrient": cl.get("nutrient"),
                "clause_ref": cl.get("schedule") or cl.get("support")}
        if cl["type"] != "nutrient":
            ps = by_clause(evidence, cl["support"])
            out.append({**base, "status": "needs_human", "citations": [cite(ps[0], best_sentence(ps[0]["text"], ["approved", "substantiat", "cannot"]))] if ps else [],
                        "detail": f"'{cl['claim_text']}' is a {cl['type']} claim; its validity cannot be established from label values and requires human review."})
            continue
        allp = list(evidence.values())
        conds = C.extract_conditions(allp, cl)
        if not conds:
            out.append({**base, "status": "needs_human", "citations": [],
                        "detail": f"The condition for the claim '{cl['claim_text']}' was not found in the retrieved provisions, so no determination is made."})
            continue
        nrv = C.extract_nrv(allp, cl["nutrient"]) if conds[0].kind == "min_nrv" else None
        ev = C.evaluate_claim(cl, req, conds, nrv)
        cits = [cite(evidence[conds[0].chunk_id], conds[0].quote)]
        if nrv:
            cits.append(cite(nrv[1], nrv[2]))
        for p in by_clause(evidence, "LDR-2020:Reg 5(3)")[:1]:
            cits.append(cite(p, best_sentence(p["text"], ["claim", "declared"])))
        out.append({**base, **ev, "citations": cits})
    return out


def build_assessor(ctx):
    s = ctx.settings
    bundle, req = ctx.bundle, ctx.request
    evidence = bundle["passages"]
    tb = ToolBox(ctx.index, req, ctx.rec, ctx.budget, ctx.redis)

    def draft(state):
        with ctx.rec.step("compute", "draft_findings", {"attempt": state["attempt"]}) as st:
            fs = draft_findings(req, bundle, evidence)
            fault = ctx.fault
            if fault and (state["attempt"] == 0 or fault == "persistent") and fs:
                tgt = next((f for f in fs if f["citations"]), None)
                if tgt:
                    tgt["citations"][0] = {**tgt["citations"][0], "quote": FAKE_QUOTE}
                    st.set(fault_injected=tgt["id"])
            st.set(findings=len(fs), statuses={f["id"]: f["status"] for f in fs})
        return {"findings": fs}

    def verify(state):
        with ctx.rec.step("verify", "verify_findings", {"attempt": state["attempt"]}) as st:
            fails = verify_findings(state["findings"], evidence, req)
            st.set(ok=not fails, failures=fails)
        return {"failures": fails}

    def after_verify(state):
        if not state["failures"]:
            return "route"
        return "repair" if state["attempt"] < MAX_REPAIRS else "escalate"

    def repair(state):
        """Different strategy from the researcher's: exact clause lookup of every failed clause, then lexical search."""
        clauses = sorted({f.get("clause_id") or f.get("clause_ref") for f in state["failures"] if f.get("clause_id") or f.get("clause_ref")})
        try:
            if clauses:
                res = tb.lookup_clause(clauses)
                for p in res["passages"]:
                    evidence.setdefault(p["chunk_id"], p)
            gaps = [f for f in state["failures"] if f["code"] == "uncited_verdict"]
            for f in gaps[:2]:
                title = next((x["title"] for x in state["findings"] if x["id"] == f["finding_id"]), "")
                for p in tb.search_corpus(title, mode="lexical", k=2)["passages"]:
                    evidence.setdefault(p["chunk_id"], p)
        except BudgetExceeded:
            pass
        return {"attempt": state["attempt"] + 1}

    def escalate(state):
        return {"forced": "verification_failed"}

    def route(state):
        fs, esc = state["findings"], []
        cat = bundle["category"]
        if bundle.get("stop_reason") in ("category_outside_corpus", "category_conflict") or not cat["in_corpus"]:
            esc.append({"trigger": "category_outside_corpus" if not cat["conflict"] else "category_conflict",
                        "detail": f"Product classified as '{cat['category']}'; the corpus covers biscuits and bakery snacks only."
                        if not cat["conflict"] else "Declared category conflicts with the product description."})
            fs = []
        if state.get("forced") == "verification_failed":
            esc.append({"trigger": "verification_failed", "detail": "Findings could not be verified against retrieved text after a repair attempt."})
        nh = [f["id"] for f in fs if f["status"] == "needs_human"]
        if nh:
            esc.append({"trigger": "needs_human_judgement", "detail": "Exemption, health/descriptor claim, conflict or missing provision for: " + ", ".join(nh)})
        if any(f["status"] == "needs_human" and "different conditions" in f["detail"] for f in fs):
            esc.append({"trigger": "regulatory_conflict", "detail": "Retrieved provisions disagree."})
        if bundle.get("stop_reason") and bundle["stop_reason"] not in ("category_outside_corpus", "category_conflict"):
            esc.append({"trigger": "research_incomplete", "detail": f"Research stopped early: {bundle['stop_reason']}."})
        unres = [u for u in bundle.get("unresolved", []) if u["kind"] in ("claim_condition",)]
        if unres and not any(e["trigger"] == "needs_human_judgement" for e in esc):
            esc.append({"trigger": "evidence_not_found", "detail": "Could not retrieve provisions for: " + ", ".join(u["key"] for u in unres)})
        unmet = [f["id"] for f in fs if f["status"] == "unmet"]
        if esc:
            r, why = "regulatory-review", "; ".join(f"{e['trigger']}: {e['detail']}" for e in esc)
        elif unmet:
            r, why = "revise-and-recheck", "Unmet requirement(s): " + ", ".join(unmet) + "."
        else:
            r, why = "clear-for-print", "All applicable requirements are met on the supplied label data. This is a recommendation, not an approval."
        return {"route": r, "reason": why, "escalations": esc, "findings": fs}

    def narrate(state):
        fs = state["findings"]
        tmpl = f"Recommended route: {state['route']}. " + (
            "Open items: " + ", ".join(f"{f['id']} ({f['status']}, {f.get('clause_ref')})" for f in fs if f["status"] in ("unmet", "needs_human")) + "."
            if any(f["status"] in ("unmet", "needs_human") for f in fs) else "No open items among the checked requirements.")
        summary, src, degraded = tmpl, "template", bundle.get("degraded")
        try:
            ctx.budget.check()
            ctx.budget.tick()
            brief = [{"id": f["id"], "status": f["status"], "clause": f.get("clause_ref")} for f in fs if f["status"] != "met"]
            system, user, v = prompts.render("justify", route=state["route"], findings=str(brief)[:1500])
            with ctx.rec.step("llm", "justify", {"route": state["route"]}) as st:
                res = ctx.llm.chat(system, user, "justify", max_tokens=160)
                d = parse_json_loose(res.text) or {}
                cand, changed = guardrails.filter_output(str(d.get("summary", "")))
                ok = bool(cand) and verify_summary(cand, state["route"], evidence, fs, req)
                st.set(prompt_tokens=res.prompt_tokens, completion_tokens=res.completion_tokens, cost_usd=res.cost_usd,
                       retries=res.retries, accepted=ok, output_filtered=changed)
                if changed:
                    from ..obs import GUARD
                    GUARD.labels("output_filtered").inc()
                if ok:
                    summary, src = cand, "llm"
        except (LLMUnavailable, BudgetExceeded) as e:
            if isinstance(e, LLMUnavailable) and ctx.llm.enabled:
                degraded = "llm_unavailable"
        return {"summary": summary, "summary_source": src, "degraded": degraded}

    g = StateGraph(AState)
    for n, f in [("draft", draft), ("verify", verify), ("repair", repair), ("escalate", escalate), ("route", route), ("narrate", narrate)]:
        g.add_node(n, f)
    g.set_entry_point("draft")
    g.add_edge("draft", "verify")
    g.add_conditional_edges("verify", after_verify, {"route": "route", "repair": "repair", "escalate": "escalate"})
    g.add_edge("repair", "draft")
    g.add_edge("escalate", "route")
    g.add_edge("route", "narrate")
    g.add_edge("narrate", END)
    return g.compile()


def run_assess(ctx) -> dict:
    graph = build_assessor(ctx)
    st = graph.invoke({"attempt": 0, "findings": [], "failures": []}, config={"recursion_limit": 40})
    bundle = ctx.bundle
    assert st["route"] in guardrails.ALLOWED_ROUTES
    # when verification ultimately failed, findings are not trustworthy: strip them (an unverified answer is never returned)
    verified = not st.get("failures") or st["attempt"] == 0 and not st["failures"]
    final_ok = not (st.get("forced") == "verification_failed")
    findings = st["findings"] if final_ok else []
    return {
        "run_id": ctx.run_id, "status": "completed", "complete": True, "route": st["route"], "route_reason": st["reason"],
        "category": bundle["category"]["category"], "claims_detected": [c["claim_text"] for c in bundle["claims"]],
        "findings": findings, "escalations": st["escalations"],
        "escalation_path": ("Hand off to a regulatory affairs professional with the evidence bundle and trace "
                            f"(GET /v1/runs/{ctx.run_id}/trace)." if st["route"] == "regulatory-review" else
                            "Revise the label and resubmit for re-check." if st["route"] == "revise-and-recheck" else
                            "A regulatory affairs professional still makes the print decision."),
        "summary": st["summary"], "summary_source": st["summary_source"],
        "verification": {"ok": final_ok, "attempts": st["attempt"] + 1, "repaired": final_ok and st["attempt"] > 0,
                         "failures": st["failures"] if not final_ok else []},
        "degraded": st.get("degraded"), "disclaimer": DISCLAIMER,
        "retrieval": {"mode": bundle["retrieval_mode"], "passages": len(bundle["passages"]), "unresolved": bundle["unresolved"],
                      "stop_reason": bundle.get("stop_reason")},
    }
