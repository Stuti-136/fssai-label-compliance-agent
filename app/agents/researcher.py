"""Agent 1 - RESEARCHER (LangGraph). Responsibility: gather evidence. Does NOT decide compliance.

Loop (bounded by steps / tool calls / wall clock):
  plan -> act(tool) -> reflect -> plan ...
 1. baseline: look up the clauses that ground each labelling requirement + one broad search
 2. reflect reads what came back for MODIFIER cues ('where a claim is made...', 'exempt', references to
    Schedules) and opens new goals from them  (section 5, step 2)
 3. claim goals use a query DERIVED from what was read (LLM, heuristic fallback)       (step 3)
 4. reflect verifies the passages actually contain the claim's condition; if not, retry
    with a different strategy: hybrid -> lexical/expanded -> clause prefix lookup        (steps 4, 5)
 5. goals that stay unresolved are handed on as gaps -> assessor escalates
"""
from __future__ import annotations
import re, logging
from typing import TypedDict, Any
from langgraph.graph import StateGraph, END
from .. import claims as C, category as CAT, guardrails, prompts, rules
from ..config import get_settings
from ..llm import LLMUnavailable, parse_json_loose
from .tools import ToolBox, Budget, BudgetExceeded

logger = logging.getLogger("researcher")
CUE_RE = re.compile(r"\b(claim|claims|unless|except|exempt\w*|subject to|notwithstanding|provided that|as specified in|in accordance with)\b", re.I)
MAX_ATTEMPTS = 3


class RState(TypedDict, total=False):
    request: dict
    category: dict
    claims: list
    evidence: dict
    goals: list
    current: Any
    cues: list
    flags: dict
    notes: list


def _sentences(t):
    return [s.strip() for s in re.split(r"(?<=[.;])\s+|\n", t) if s.strip()]


def _heuristic_query(claim, cue):
    return f"nutrition claim conditions {claim['claim_text']} {claim.get('nutrient', '').replace('_g', '').replace('_mg', '')} per 100 g NRV schedule"


def build_researcher(ctx):
    """ctx: object with .index .llm .rec .budget .redis .settings .request"""
    s = ctx.settings
    tb = ToolBox(ctx.index, ctx.request, ctx.rec, ctx.budget, ctx.redis)
    single = s.retrieval_mode == "single_pass"

    def goal(state, key, kind, **kw):
        if any(g["key"] == key for g in state["goals"]):
            return
        state["goals"].append({"key": key, "kind": kind, "status": "pending", "attempts": 0, **kw})

    def derive_query(state, claim, cue):
        fallback = _heuristic_query(claim, cue)
        try:
            ctx.budget.check()
            ctx.budget.tick()
            system, user, v = prompts.render("derive_query", claim=guardrails.wrap_untrusted(claim["claim_text"]),
                                             cue=guardrails.wrap_untrusted(cue or "none"))
            with ctx.rec.step("llm", "derive_query", {"claim": claim["key"]}) as st:
                res = ctx.llm.chat(system, user, "derive_query", max_tokens=80)
                d = parse_json_loose(res.text) or {}
                q = guardrails.sanitize_for_prompt(str(d.get("query", "")), 200)
                ok = bool(q) and any(w in q.lower() for w in claim["claim_text"].lower().split()[:2])
                st.set(prompt_tokens=res.prompt_tokens, completion_tokens=res.completion_tokens, cost_usd=res.cost_usd,
                       retries=res.retries, accepted=ok, query=q if ok else fallback)
            return q if ok else fallback
        except (LLMUnavailable, BudgetExceeded) as e:
            if isinstance(e, LLMUnavailable) and ctx.llm.enabled:
                state["flags"]["degraded"] = "llm_unavailable"
            return fallback

    def init(state):
        req = state["request"]
        with ctx.rec.step("tool", "get_request_field", {"path": "front_of_pack_text"}) as st:
            ctx.budget.tick(tool=True)
            texts = req.get("front_of_pack_text", []) + [req["product_name"]]
            st.set(n_texts=len(texts))
        cat = CAT.classify(req)
        cl = C.detect_claims(texts)
        ctx.rec.event("decision", "classify_and_detect", category=cat, claims=[c["key"] for c in cl])
        state.update(category=cat, claims=cl, evidence={}, goals=[], cues=[], notes=[],
                     flags={"stop_reason": None, "claims_planned": False, "degraded": None})
        if not cat["in_corpus"]:
            state["flags"]["stop_reason"] = "category_outside_corpus" if not cat["conflict"] else "category_conflict"
            return state
        goal(state, "baseline_lookup", "baseline_lookup", refs=rules.baseline_refs(req, cl))
        goal(state, "baseline_search", "baseline_search",
             query=f"labelling requirements pre-packaged {cat['category'].replace('_', ' ')} {req['product_name']}")
        return state

    def plan(state):
        if state["flags"]["stop_reason"]:
            return {"current": None}
        try:
            ctx.budget.check()
        except BudgetExceeded as e:
            state["flags"]["stop_reason"] = str(e)
            return {"current": None}
        pend = [g for g in state["goals"] if g["status"] == "pending"]
        if not pend:
            return {"current": None}
        g = pend[0]
        k, a = g["kind"], g["attempts"]
        if k == "baseline_lookup":
            act = ("lookup_clause", {"refs": g["refs"]})
        elif k == "baseline_search":
            act = ("search_corpus", {"query": g["query"], "mode": "semantic" if single else "hybrid", "k": 6})
        elif k == "claim_condition":
            cl = next(c for c in state["claims"] if c["key"] == g["claim_key"])
            if a == 0:
                act = ("search_corpus", {"query": g["query"], "mode": "hybrid", "doc_id": "ACR-2018", "k": 4})
            elif a == 1:  # different strategy: lexical on the claim wording, whole corpus
                act = ("search_corpus", {"query": f"{cl['phrase']} {cl['claim_text']} conditions", "mode": "lexical", "k": 4})
            else:         # different strategy: exact clause by id
                act = ("lookup_clause", {"refs": [cl.get("schedule") or cl.get("support")]})
        elif k == "nrv":
            act = ("lookup_clause", {"refs": ["ACR-2018:Schedule I/NRV"]}) if a == 0 else \
                  ("search_corpus", {"query": "nutrient reference values NRV protein", "mode": "lexical", "doc_id": "ACR-2018", "k": 3})
        elif k == "ref":
            act = ("lookup_clause", {"refs": [g["ref"]]})
        else:  # exemption
            act = ("search_corpus", {"query": g["query"], "mode": "hybrid", "doc_id": "LDR-2020", "k": 3})
        return {"current": {"goal": g, "tool": act[0], "args": act[1]}}

    def act(state):
        cur = state["current"]
        try:
            res = getattr(tb, cur["tool"])(**cur["args"])
        except BudgetExceeded as e:
            state["flags"]["stop_reason"] = str(e)
            cur["new"], cur["res"] = [], {}
            return {"current": cur}
        new = []
        for p in res.get("passages", []):
            if p["chunk_id"] not in state["evidence"]:
                state["evidence"][p["chunk_id"]] = p
                new.append(p)
        cur["new"], cur["res"] = new, res
        return {"current": cur}

    def plan_claims(state):
        state["flags"]["claims_planned"] = True
        cue = (state["cues"] or [None])[0]
        for cl in state["claims"]:
            if cl["type"] == "nutrient":
                goal(state, f"claim:{cl['key']}", "claim_condition", claim_key=cl["key"], query=derive_query(state, cl, cue))
            else:
                goal(state, f"claim:{cl['key']}", "claim_condition", claim_key=cl["key"],
                     query=f"advertising claims {cl['type']} claims conditions approval substantiation")

    def reflect(state):
        cur = state["current"]
        if not cur or not cur.get("res"):
            return {"current": None}
        g, new, allp = cur["goal"], cur["new"], list(state["evidence"].values())
        k, ok = g["kind"], True
        if k == "claim_condition":
            cl = next(c for c in state["claims"] if c["key"] == g["claim_key"])
            if cl["type"] == "nutrient":
                conds = C.extract_conditions(allp, cl)
                ok = bool(conds)
                if ok and cl["kind"] == "min_nrv":
                    goal(state, "nrv", "nrv", nutrient=cl["nutrient"])
            else:
                ok = any(p["clause_id"] == cl["support"] for p in allp)
            ctx.rec.event("verify_evidence", f"claim:{cl['key']}", supported=ok, attempt=g["attempts"] + 1,
                          strategy=cur["tool"] + ":" + str(cur["args"].get("mode", "")))
        elif k == "nrv":
            ok = C.extract_nrv(allp, g["nutrient"]) is not None
            ctx.rec.event("verify_evidence", "nrv", supported=ok, attempt=g["attempts"] + 1)
        elif k == "baseline_lookup":
            if cur["res"].get("missing"):
                state["notes"].append("missing clauses: " + ", ".join(cur["res"]["missing"]))
        # --- modifier discovery in newly read passages (agentic mode only)
        if not single:
            for p in new:
                for sent in _sentences(p["text"]):
                    if CUE_RE.search(sent) and sent not in state["cues"]:
                        state["cues"].append(sent)
                        if re.search(r"exempt|reduced form|omitted", sent, re.I):
                            goal(state, "exemption", "exemption", query="exemption small package surface area declarations omitted")
            if new:
                refs = tb.extract_cross_references(new)["refs"] if _has_budget(ctx) else []
                for ref in refs[:3]:
                    goal(state, f"ref:{ref}", "ref", ref=ref)
        if ok:
            g["status"] = "done"
        else:
            g["attempts"] += 1
            if g["attempts"] >= MAX_ATTEMPTS:
                g["status"] = "failed"
        pending_base = [x for x in state["goals"] if x["kind"].startswith("baseline") and x["status"] == "pending"]
        if not single and not pending_base and not state["flags"]["claims_planned"] and state["claims"]:
            plan_claims(state)
        return {"current": None}

    def finish(state):
        return state

    g = StateGraph(RState)
    for name, fn in [("init", init), ("plan", plan), ("act", act), ("reflect", reflect), ("finish", finish)]:
        g.add_node(name, fn)
    g.set_entry_point("init")
    g.add_edge("init", "plan")
    g.add_conditional_edges("plan", lambda s: "act" if s.get("current") else "finish", {"act": "act", "finish": "finish"})
    g.add_edge("act", "reflect")
    g.add_edge("reflect", "plan")
    g.add_edge("finish", END)
    return g.compile()


def _has_budget(ctx):
    try:
        ctx.budget.check()
        return True
    except BudgetExceeded:
        return False


def run_research(ctx) -> dict:
    """Runs the researcher graph and returns the EvidenceBundle handed to the assessor."""
    graph = build_researcher(ctx)
    st = graph.invoke({"request": ctx.request}, config={"recursion_limit": 6 * ctx.settings.run_max_steps + 20})
    unresolved = [{"key": g["key"], "kind": g["kind"], "attempts": g["attempts"]} for g in st["goals"] if g["status"] != "done"]
    return {"run_id": ctx.run_id, "category": st["category"], "claims": st["claims"], "passages": st["evidence"],
            "unresolved": unresolved, "cues": st["cues"], "notes": st.get("notes", []),
            "stop_reason": st["flags"]["stop_reason"], "degraded": st["flags"]["degraded"],
            "retrieval_mode": ctx.settings.retrieval_mode, "stats": ctx.rec.stats()}
