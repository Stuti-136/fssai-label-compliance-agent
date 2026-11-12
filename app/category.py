"""F3: product category classification. Corpus covers one category; everything else escalates (F7)."""
from __future__ import annotations
import re

IN_CORPUS = {"biscuits_bakery"}
KW = {
    "biscuits_bakery": ["biscuit", "cookie", "cracker", "rusk", "wafer", "digestive", "marie", "bakery", "cream biscuit", "cereal bar", "oat bar", "granola bar"],
    "dairy": ["milk", "paneer", "cheese", "yogurt", "yoghurt", "curd", "dahi", "butter", "ghee", "lassi", "ice cream", "khoa"],
    "beverages": ["juice", "soda", "drink", "beverage", "tea", "coffee", "squash", "cola", "energy drink"],
    "meat_fish": ["chicken", "mutton", "fish", "prawn", "sausage", "meat", "egg roll", "salami"],
    "infant_nutrition": ["infant", "baby food", "toddler", "follow-up formula", "weaning"],
    "supplements": ["protein powder", "supplement", "capsule", "nutraceutical", "whey", "multivitamin", "gummies"],
    "confectionery": ["candy", "chocolate", "toffee", "lollipop", "chewing gum", "jelly"],
}


def classify(req: dict) -> dict:
    name = (req["product_name"] + " " + (req.get("brand_name") or "")).lower()
    ing = req["ingredients_text"].lower()
    scores = {}
    for cat, kws in KW.items():
        s = sum(3 for k in kws if re.search(r"\b" + re.escape(k), name)) + sum(1 for k in kws if re.search(r"\b" + re.escape(k), ing))
        if s:
            scores[cat] = s
    decl = req.get("declared_category", "unspecified")
    if decl not in ("unspecified",):
        scores[decl] = scores.get(decl, 0) + 4
    if not scores:
        return {"category": "unknown", "in_corpus": False, "conflict": False, "scores": {}}
    top = max(scores, key=scores.get)
    conflict = decl not in ("unspecified", "other") and top != decl
    # a declared in-corpus category contradicted by name evidence for another category is a conflict
    if decl in IN_CORPUS and top != decl:
        conflict = True
    return {"category": top, "in_corpus": top in IN_CORPUS and not conflict, "conflict": conflict, "scores": scores}
