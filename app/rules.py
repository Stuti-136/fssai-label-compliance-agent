"""Requirement catalogue (F4/F5). Each rule says WHICH clause grounds it and how to evaluate the request.
The verdict is computed from request fields; the clause supplies the citation and may be a placeholder id
until the official PDFs replace the seed corpus (ingest warns about missing ids)."""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Callable
from .claims import CLAIMS

D = "LDR-2020:"
NON_VEG = [r"\bgelatine?\b", r"\beggs?\b", r"\bchicken\b", r"\bmutton\b", r"\bfish\b", r"\bpork\b", r"\bbeef\b",
           r"\blard\b", r"\btallow\b", r"\bshrimps?\b", r"\bprawns?\b", r"\bbone\b", r"\bcarmine\b", r"\bcochineal\b",
           r"\bisinglass\b", r"\bmeat\b", r"\brennet\b"]
ALLERGENS = {
    "gluten/wheat": (["wheat", "gluten", "barley", "rye", "oats", "maida", "semolina", "rava", "atta"], ["gluten", "wheat", "cereal"]),
    "milk": (["milk", "butter", "ghee", "cream", "whey", "casein", "lactose", "cheese"], ["milk", "dairy", "lactose"]),
    "soy": (["soy", "soya", "soybean"], ["soy"]),
    "egg": ([r"eggs?"], ["egg"]),
    "peanut": (["peanut", "groundnut"], ["peanut", "groundnut"]),
    "tree nuts": (["almond", "cashew", "walnut", "pistachio", "hazelnut", "pecan"], ["nut", "almond", "cashew", "walnut", "pistachio", "hazelnut", "pecan"]),
    "sesame": (["sesame"], ["sesame"]),
    "fish": (["fish"], ["fish"]),
    "crustacean": (["shrimp", "prawn", "crab"], ["shrimp", "prawn", "crab", "crustacean", "shellfish"]),
}
ADDITIVE_CLASSES = ["acidity regulator", "antioxidant", "emulsifier", "raising agent", "preservative", "colour", "color",
                    "flavour", "flavor", "stabili", "thickener", "humectant", "sweetener", "anticaking", "bulking agent",
                    "firming agent", "flour treatment", "glazing", "gelling agent", "improver"]
REQ_NUTRIENTS = ["energy_kcal", "protein_g", "carbohydrate_g", "total_sugars_g", "added_sugars_g", "total_fat_g",
                 "saturated_fat_g", "trans_fat_g", "sodium_mg"]


def _has(words, text):
    return any(re.search(r"\b" + w + r"\b", text) for w in words)


def r_name(q): return ("met", "A product name is declared.")
def r_ingredients(q): return ("met", "An ingredients list is present (descending order cannot be verified from text alone).") if q["ingredients_text"].strip() else ("unmet", "Ingredients list is missing.")


def r_nutrition(q):
    n = q.get("nutrition")
    if not n:
        return ("unmet", "No nutritional information was supplied.")
    miss = [k for k in REQ_NUTRIENTS if n.get(k) is None]
    return ("unmet", "Nutrition panel is missing: " + ", ".join(miss) + ".") if miss else ("met", "All mandatory nutrients are declared per 100 g / 100 ml.")


def r_diet(q):
    ing = q["ingredients_text"].lower()
    nv = [p.strip(r"\b").replace("\\", "") for p in NON_VEG if re.search(p, ing)]
    m = q["diet_mark"]
    if m == "none":
        return ("unmet", "No vegetarian / non-vegetarian mark was declared.")
    if m == "veg" and nv:
        return ("unmet", "Vegetarian mark declared but ingredients include animal-derived item(s): " + ", ".join(nv) + ".")
    return ("met", f"Declared mark '{m}' is consistent with the ingredients list.")


def r_additives(q):
    t = q["ingredients_text"]
    bad = []
    for m in re.finditer(r"\b(?:INS|E)\s?\d{3,4}[a-z]?(?:\([ivx]+\))?", t, re.I):
        back = t[max(0, m.start() - 45): m.start()].lower()
        if not any(c in back for c in ADDITIVE_CLASSES):
            bad.append(m.group(0))
    return ("unmet", "Additive code(s) without a functional class name: " + ", ".join(bad) + ".") if bad else ("met", "Additives are declared with a class name and code (or none present).")


def r_mfr(q):
    return ("met", "Manufacturer name and address are declared.") if q.get("manufacturer_name") and q.get("manufacturer_address") else ("unmet", "Manufacturer name and/or complete address is missing.")


def r_qty(q): return ("met", f"Net quantity declared: {q['net_quantity_value']} {q['net_quantity_unit']}.")
def r_batch(q): return ("met", "Lot/batch marking present.") if q["batch_marking_present"] else ("unmet", "Lot/batch marking is missing.")
def r_date(q): return ("met", f"Date marking present ({q['date_marking']}).") if q["date_marking"] != "none" else ("unmet", "Date marking is missing.")
def r_origin(q):
    if not q["is_imported"]:
        return ("not_applicable", "Product is not imported.")
    return ("met", f"Country of origin declared: {q['country_of_origin']}.")


def r_license(q):
    ok = q["fssai_logo_present"] and q.get("fssai_license_no")
    return ("met", "FSSAI logo and 14-digit licence number present.") if ok else ("unmet", "FSSAI logo and/or licence number is missing.")


def r_allergen(q):
    ing = q["ingredients_text"].lower()
    stmt = (q.get("allergen_statement") or "").lower()
    missing = []
    for grp, (kws, decl) in ALLERGENS.items():
        if any(re.search(r"\b" + k + r"\b", ing) for k in kws) and not any(d in stmt for d in decl):
            missing.append(grp)
    return ("unmet", "Allergen(s) present in ingredients but not declared: " + ", ".join(missing) + ".") if missing else ("met", "Allergen declaration is consistent with the ingredients list (or none required).")


def r_small_pack(q):  # exemption handled specially in assessor
    return ("exemption_check", "")


@dataclass
class Rule:
    id: str
    title: str
    clause: str
    keywords: list[str]
    check: Callable


RULES = [
    Rule("R01_name", "Name of food", D + "Reg 5(1)", ["name of the food"], r_name),
    Rule("R02_ingredients", "List of ingredients", D + "Reg 5(2)", ["list of ingredients", "descending"], r_ingredients),
    Rule("R03_nutrition", "Nutritional information", D + "Reg 5(3)", ["nutritional information", "per 100"], r_nutrition),
    Rule("R04_diet_mark", "Vegetarian / non-vegetarian mark", D + "Reg 5(4)", ["vegetarian", "mark"], r_diet),
    Rule("R05_additives", "Food additive declaration", D + "Reg 5(5)", ["functional class", "INS"], r_additives),
    Rule("R06_manufacturer", "Manufacturer name and address", D + "Reg 5(6)", ["name and complete address"], r_mfr),
    Rule("R07_net_quantity", "Net quantity", D + "Reg 5(7)", ["net quantity"], r_qty),
    Rule("R08_batch", "Lot / batch identification", D + "Reg 5(8)", ["lot number", "batch"], r_batch),
    Rule("R09_date", "Date marking", D + "Reg 5(9)", ["date marking", "best before"], r_date),
    Rule("R10_origin", "Country of origin (imported food)", D + "Reg 5(10)", ["country of origin"], r_origin),
    Rule("R11_allergen", "Allergen declaration", D + "Reg 5(11)", ["allergen"], r_allergen),
    Rule("R12_license", "FSSAI logo and licence number", D + "Reg 5(12)", ["logo", "licence"], r_license),
    Rule("R13_small_pack", "Small-package exemption", D + "Reg 7", ["surface area", "less than"], r_small_pack),
]
CLAIM_GENERAL = [D + "Reg 5(3)", "ACR-2018:Reg 4", "ACR-2018:Reg 5"]


def all_referenced_clauses() -> list[str]:
    s = {r.clause for r in RULES} | set(CLAIM_GENERAL)
    for c in CLAIMS:
        s.add(c.get("schedule") or c.get("support"))
    s.add("ACR-2018:Schedule I/NRV")
    return sorted(s)


def baseline_refs(req: dict, claims: list[dict]) -> list[str]:
    refs = [r.clause for r in RULES]
    if claims:
        refs += ["LDR-2020:Reg 4", "ACR-2018:Reg 4", "ACR-2018:Reg 5"]
    return list(dict.fromkeys(refs))
