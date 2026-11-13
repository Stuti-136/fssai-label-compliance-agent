"""F3/F4: claim detection and extraction of claim conditions FROM RETRIEVED TEXT (nothing is hard-coded:
thresholds are parsed out of the retrieved clause so a wrong or missing passage cannot produce a verdict)."""
from __future__ import annotations
import re
from dataclasses import dataclass

NUM = r"(\d+(?:\.\d+)?)"
CLAIMS = [
    dict(key="source_of_protein", phrase="source of protein", pats=[r"\b(good |excellent )?source of protein\b", r"\bprotein source\b"],
         type="nutrient", nutrient="protein_g", kind="min_nrv", schedule="ACR-2018:Schedule I/Protein"),
    dict(key="high_protein", phrase="high protein", pats=[r"\bhigh[- ]protein\b", r"\brich in protein\b"],
         type="nutrient", nutrient="protein_g", kind="min_nrv", schedule="ACR-2018:Schedule I/Protein"),
    dict(key="source_of_fibre", phrase="source of dietary fibre", pats=[r"\b(good )?source of (dietary )?fi(b|be)re\b"],
         type="nutrient", nutrient="dietary_fibre_g", kind="min_abs", schedule="ACR-2018:Schedule I/Fibre"),
    dict(key="high_fibre", phrase="high dietary fibre", pats=[r"\bhigh[- ](dietary )?fi(b|be)re\b", r"\brich in fi(b|be)re\b"],
         type="nutrient", nutrient="dietary_fibre_g", kind="min_abs", schedule="ACR-2018:Schedule I/Fibre"),
    dict(key="low_fat", phrase="low fat", pats=[r"\blow[- ]fat\b"], type="nutrient", nutrient="total_fat_g",
         kind="max_abs", schedule="ACR-2018:Schedule I/Fat"),
    dict(key="fat_free", phrase="fat free", pats=[r"\bfat[- ]free\b", r"\b0% fat\b"], type="nutrient",
         nutrient="total_fat_g", kind="max_abs", schedule="ACR-2018:Schedule I/Fat"),
    dict(key="low_sugar", phrase="low sugar", pats=[r"\blow[- ]sugars?\b"], type="nutrient", nutrient="total_sugars_g",
         kind="max_abs", schedule="ACR-2018:Schedule I/Sugars"),
    dict(key="sugar_free", phrase="sugar free", pats=[r"\bsugar[- ]free\b"], type="nutrient",
         nutrient="total_sugars_g", kind="max_abs", schedule="ACR-2018:Schedule I/Sugars"),
    dict(key="no_added_sugar", phrase="no added sugar", pats=[r"\bno added sugars?\b", r"\bwithout added sugars?\b"],
         type="nutrient", nutrient="added_sugars_g", kind="max_abs", schedule="ACR-2018:Schedule I/Sugars"),
    dict(key="low_sodium", phrase="low sodium", pats=[r"\blow[- ](sodium|salt)\b"], type="nutrient",
         nutrient="sodium_mg", kind="max_abs", schedule="ACR-2018:Schedule I/Sodium"),
    dict(key="health_claim", phrase="health claim", pats=[r"\bboosts? immunity\b", r"\bimmunity\b", r"\bheart[- ]healthy\b",
         r"\bhelps? (lower|reduce|control|manage)\b", r"\bprevents?\b", r"\bcures?\b", r"\bdiabetic[- ]friendly\b",
         r"\bsupports? (heart|digestion|immunity)\b"], type="health", support="ACR-2018:Reg 7"),
    dict(key="descriptor_claim", phrase="descriptor", pats=[r"\b100% natural\b", r"\bnatural\b", r"\bpure\b", r"\bfresh\b"],
        type="descriptor", support="ACR-2018:Reg 9",
schedule="ACR-2018:Schedule V"),
]
UNIT = {"g": 1.0, "mg": 0.001}


def detect_claims(texts: list[str]) -> list[dict]:
    found, seen = [], set()
    for t in texts:
        for c in CLAIMS:
            if c["key"] in seen:
                continue
            for p in c["pats"]:
                m = re.search(p, t, re.I)
                if m:
                    seen.add(c["key"])
                    found.append({**{k: v for k, v in c.items() if k != "pats"}, "claim_text": m.group(0), "source_text": t})
                    break
    # 'high protein' subsumes a co-detected 'source of protein' pattern only if both literally present: keep both.
    return found


@dataclass
class Condition:
    kind: str
    solid: float | None
    liquid: float | None
    unit: str            # '% NRV' | 'g' | 'mg'
    chunk_id: str
    clause_id: str
    quote: str


def _lines(text: str):
    return [l.strip() for l in re.split(r"\n", text) if l.strip()]


def extract_conditions(passages: list[dict], claim: dict) -> list[Condition]:
    out = []
    ph = claim["phrase"].lower()
    for p in passages:
        for line in _lines(p["text"]):
            if not line.lower().startswith(ph):
                continue
            if claim["kind"] == "min_nrv":
                s = re.search(NUM + r"\s*%\s*of\s*(?:the\s*)?NRV\s*per\s*100\s*g", line, re.I)
                l = re.search(NUM + r"\s*%\s*of\s*(?:the\s*)?NRV\s*per\s*100\s*ml", line, re.I)
                if s:
                    out.append(Condition("min_nrv", float(s.group(1)), float(l.group(1)) if l else None, "% NRV",
                                         p["chunk_id"], p["clause_id"], line))
            else:
                word = r"at least" if claim["kind"] == "min_abs" else r"not more than"
                vals = {"g": None, "ml": None}
                unit = "g"
                for m in re.finditer(word + r"\s+" + NUM + r"\s*(mg|g)\s*(?:of\s+[a-z ]+?\s+)?per\s*100\s*(g|ml)", line, re.I):
                    unit = m.group(2).lower()
                    vals[m.group(3).lower()] = float(m.group(1))
                if vals["g"] is not None:
                    out.append(Condition(claim["kind"], vals["g"], vals["ml"], unit, p["chunk_id"], p["clause_id"], line))
    return out


def extract_nrv(passages: list[dict], nutrient: str) -> tuple[float, dict, str] | None:
    label = {"protein_g": "protein"}.get(nutrient)
    if not label:
        return None
    for p in passages:
        for line in _lines(p["text"]):
            m = re.match(label + r"\s*[:\-]\s*" + NUM + r"\s*g\b", line, re.I)
            if m:
                return float(m.group(1)), p, line
    return None


def fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def evaluate_claim(claim: dict, req: dict, conds: list[Condition], nrv) -> dict:
    """Pure function: (claim, request, parsed conditions, NRV) -> status/detail/computed. No retrieval, no LLM."""
    nut = (req.get("nutrition") or {}).get(claim["nutrient"])
    liquid = req["physical_state"] == "liquid"
    basis = "per 100 ml" if liquid else "per 100 g"
    vals = {(c.solid, c.liquid, c.unit) for c in conds}
    if len(vals) > 1:
        return {"status": "needs_human", "detail": "Retrieved provisions give different conditions for this claim "
                "(possible conflict between regulations or amendments); a human must resolve which applies.",
                "computed": {"conflict": sorted(map(str, vals))}}
    c = conds[0]
    limit = c.liquid if liquid else c.solid
    if limit is None:
        return {"status": "needs_human", "detail": f"The retrieved condition has no value for {'liquid' if liquid else 'solid'} foods.",
                "computed": {}}
    if nut is None:
        return {"status": "unmet", "detail": f"The claim '{claim['claim_text']}' needs the nutrient to be declared, but "
                f"{claim['nutrient']} is not declared in the nutrition panel.", "computed": {"declared": None}}
    if c.kind == "min_nrv":
        if not nrv:
            return {"status": "needs_human", "detail": "NRV reference value was not retrieved.", "computed": {}}
        nrv_g = nrv[0]
        thr = round(limit / 100 * nrv_g, 4)
        ok = nut + 1e-9 >= thr
        d = (f"Declared {claim['nutrient'].split('_')[0]} is {fmt(nut)} g {basis}. The condition requires at least {fmt(limit)}% of "
             f"the NRV ({fmt(nrv_g)} g), i.e. at least {fmt(thr)} g {basis}. The claim is "
             f"{'supported' if ok else 'NOT supported'} by the declared value.")
        return {"status": "met" if ok else "unmet", "detail": d,
                "computed": {"declared": nut, "threshold": thr, "pct_nrv": limit, "nrv_g": nrv_g, "basis": basis}}
    scale = UNIT[c.unit] / UNIT[{"sodium_mg": "mg"}.get(claim["nutrient"], "g")]
    thr = limit * scale  # express threshold in the unit of the declared field
    ok = nut + 1e-9 >= thr if c.kind == "min_abs" else nut <= thr + 1e-9
    word = "at least" if c.kind == "min_abs" else "not more than"
    unit = "mg" if claim["nutrient"] == "sodium_mg" else "g"
    d = (f"Declared value is {fmt(nut)} {unit} {basis}. The condition requires {word} {fmt(limit)} {c.unit} {basis}. "
         f"The claim is {'supported' if ok else 'NOT supported'} by the declared value.")
    return {"status": "met" if ok else "unmet", "detail": d,
            "computed": {"declared": nut, "limit": limit, "comparator": word, "basis": basis}}
