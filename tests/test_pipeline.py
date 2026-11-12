from app.samples import make
from app.pipeline import run_pipeline


def run(index, redis, req, **kw):
    return run_pipeline(req, redis, index, **kw)


def f(res, fid):
    return next(x for x in res["findings"] if x["id"] == fid)


def test_base_label_clear(index, redis):
    res, _ = run(index, redis, make())
    assert res["route"] == "clear-for-print", res["route_reason"]
    assert res["verification"]["ok"]


def test_section_4_1_unmet(index, redis):
    """'source of protein' with 4.0 g/100 g: needs >= 10% of NRV 60 g = 6 g -> unmet; cites BOTH regulations."""
    res, b = run(index, redis, make(front_of_pack_text=["Source of Protein"], nutrition={"protein_g": 4.0}))
    c = f(res, "CLAIM:source_of_protein")
    assert c["status"] == "unmet" and c["computed"]["threshold"] == 6.0
    docs = {x["doc_id"] for x in c["citations"]}
    assert docs == {"ACR-2018", "LDR-2020"}
    assert res["route"] == "revise-and-recheck"
    for x in c["citations"]:  # every citation resolves to retrieved text
        assert x["quote"].lower() in b["passages"][x["chunk_id"]]["text"].lower()


def test_section_4_1_met_and_boundary(index, redis):
    for g, st in [(7.5, "met"), (6.0, "met"), (5.9, "unmet")]:
        res, _ = run(index, redis, make(front_of_pack_text=["source of protein"], nutrition={"protein_g": g, "energy_kcal": 470}))
        assert f(res, "CLAIM:source_of_protein")["status"] == st, g


def test_single_pass_misses_claim_condition(index, redis, monkeypatch):
    """The deliberate change: one embedding search cannot find the claims regulation -> must NOT answer (escalates)."""
    from app.config import reset_settings
    monkeypatch.setenv("RETRIEVAL_MODE", "single_pass"); reset_settings()
    try:
        res, _ = run(index, redis, make(front_of_pack_text=["Source of Protein"], nutrition={"protein_g": 4.0}))
        assert f(res, "CLAIM:source_of_protein")["status"] == "needs_human"
        assert res["route"] == "regulatory-review"
    finally:
        monkeypatch.delenv("RETRIEVAL_MODE"); reset_settings()


def test_out_of_corpus_escalates(index, redis):
    res, _ = run(index, redis, make(product_name="Fresh Paneer Block", declared_category="dairy", ingredients_text="Pasteurised milk, citric acid"))
    assert res["route"] == "regulatory-review" and res["findings"] == []
    assert res["escalations"][0]["trigger"] == "category_outside_corpus"


def test_health_claim_and_exemption_escalate(index, redis):
    res, _ = run(index, redis, make(front_of_pack_text=["Boosts immunity"]))
    assert res["route"] == "regulatory-review"
    res, _ = run(index, redis, make(package_surface_area_cm2=60))
    assert f(res, "R13_small_pack")["status"] == "needs_human" and res["route"] == "regulatory-review"


def test_verification_catches_unsupported_then_repairs(index, redis):
    res, _ = run(index, redis, make(front_of_pack_text=["Source of Protein"], nutrition={"protein_g": 7.5}), fault="unsupported")
    assert res["verification"]["ok"] and res["verification"]["repaired"] and res["verification"]["attempts"] == 2
    assert res["route"] == "clear-for-print"


def test_persistent_unverified_escalates_without_findings(index, redis):
    res, _ = run(index, redis, make(), fault="persistent")
    assert res["route"] == "regulatory-review" and res["findings"] == [] and not res["verification"]["ok"]


def test_rule_failures(index, redis):
    res, _ = run(index, redis, make(diet_mark="none", allergen_statement=None, batch_marking_present=False))
    ids = {x["id"] for x in res["findings"] if x["status"] == "unmet"}
    assert {"R04_diet_mark", "R11_allergen", "R08_batch"} <= ids and res["route"] == "revise-and-recheck"


def test_trace_reconstructible(index, redis):
    res, _ = run(index, redis, make(front_of_pack_text=["Source of Protein"], nutrition={"protein_g": 4.0}))
    ev = [__import__("json").loads(x) for x in redis.lrange(f"trace:{res['run_id']}", 0, -1)]
    kinds = {(e["kind"], e["name"]) for e in ev}
    assert ("tool", "lookup_clause") in kinds and ("tool", "search_corpus") in kinds and ("verify", "verify_findings") in kinds
    assert all("prompt_version" in e for e in ev)


def test_budget_exhaustion_stops_and_escalates(index, redis, monkeypatch):
    from app.config import reset_settings
    monkeypatch.setenv("RUN_MAX_TOOL_CALLS", "2"); reset_settings()
    try:
        res, b = run(index, redis, make(front_of_pack_text=["Source of Protein"], nutrition={"protein_g": 7.5}))
        assert b["stop_reason"] and "budget" in b["stop_reason"]
        assert res["route"] == "regulatory-review"          # incomplete research never yields a confident answer
        assert any(e["trigger"] == "research_incomplete" for e in res["escalations"])
    finally:
        monkeypatch.delenv("RUN_MAX_TOOL_CALLS"); reset_settings()


def test_llm_called_once_per_claim(index, redis):
    class Fake:
        enabled = True
        n = 0
        def chat(self, system, user, step, max_tokens=0):
            from app.llm import LLMResult
            Fake.n += step == "derive_query"
            return LLMResult('{"query": "source of protein claim conditions schedule"}', 50, 10, 0.001, 0.0, 0)
    res, b = run(index, redis, make(front_of_pack_text=["Source of Protein"], nutrition={"protein_g": 7.5}), llm=Fake())
    assert Fake.n == 1 and res["stats"]["cost_usd"] > 0
