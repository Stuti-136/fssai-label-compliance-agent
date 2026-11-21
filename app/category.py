"""Product category classification. Only the configured bakery workflow is automated."""
from __future__ import annotations
import re

IN_CORPUS = {"biscuits_bakery"}
KW = {
    "biscuits_bakery": ["biscuit", "cookie", "cracker", "rusk", "wafer", "digestive", "marie", "bakery", "cream biscuit", "cereal bar", "oat bar", "granola bar"],
    "dairy_products": ["milk", "paneer", "cheese", "yogurt", "yoghurt", "curd", "dahi", "butter", "ghee", "lassi", "ice cream", "khoa"],
    "dairy": ["milk", "paneer", "cheese", "yogurt", "yoghurt", "curd", "dahi", "butter", "ghee", "lassi", "ice cream", "khoa"],
    "beverages_juices": ["juice", "soda", "drink", "beverage", "tea", "coffee", "squash", "cola", "energy drink"],
    "beverages": ["juice", "soda", "drink", "beverage", "tea", "coffee", "squash", "cola", "energy drink"],
    "snacks_savoury": ["snack", "namkeen", "chips", "crisps", "savoury", "savory", "mixture"],
    "confectionery_chocolates": ["candy", "chocolate", "toffee", "lollipop", "chewing gum", "jelly"],
    "confectionery": ["candy", "chocolate", "toffee", "lollipop", "chewing gum", "jelly"],
    "cereals_breakfast": ["cereal", "breakfast", "cornflakes", "muesli", "oats", "porridge"],
    "instant_ready_to_eat": ["instant", "ready to eat", "ready-to-eat", "noodles", "soup mix"],
    "spices_seasonings": ["spice", "masala", "seasoning", "pepper", "turmeric", "chilli", "chili"],
    "sauces_dips_condiments": ["sauce", "dip", "ketchup", "chutney", "mayonnaise", "condiment"],
    "edible_oils_fats": ["edible oil", "cooking oil", "mustard oil", "sunflower oil", "ghee", "fat"],
    "pulses_packaged_grains": ["pulse", "lentil", "dal", "rice", "grain", "wheat", "chickpea"],
    "meat_fish": ["chicken", "mutton", "fish", "prawn", "sausage", "meat", "egg roll", "salami"],
    "infant_nutrition": ["infant", "baby food", "toddler", "follow-up formula", "weaning"],
    "supplements": ["protein powder", "supplement", "capsule", "nutraceutical", "whey", "multivitamin", "gummies"],
    "nutritional_health_foods": ["protein powder", "supplement", "capsule", "nutraceutical", "whey", "multivitamin", "gummies", "health food"],
}

CATEGORY_LABELS = {
    "biscuits_bakery": "Biscuits and Bakery",
    "beverages_juices": "Beverages and Juices",
    "dairy_products": "Dairy Products (including milk products)",
    "snacks_savoury": "Snacks and Savoury Products",
    "confectionery_chocolates": "Confectionery and Chocolates",
    "cereals_breakfast": "Cereals and Breakfast Products",
    "instant_ready_to_eat": "Instant and Ready-to-Eat Foods",
    "spices_seasonings": "Spices and Seasonings",
    "sauces_dips_condiments": "Sauces, Dips and Condiments",
    "edible_oils_fats": "Edible Oils and Fats",
    "pulses_packaged_grains": "Pulses and Packaged Grains",
    "nutritional_health_foods": "Nutritional and Health Foods",
    "other": "Other",
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
        return {
            "category": "unknown",
            "display_category": "Unspecified category",
            "declared_category": decl,
            "custom_category": req.get("custom_category"),
            "in_corpus": False,
            "conflict": False,
            "scores": {},
        }
    top = max(scores, key=scores.get)
    conflict = decl not in ("unspecified", "other") and top != decl
    # a declared in-corpus category contradicted by name evidence for another category is a conflict
    if decl in IN_CORPUS and top != decl:
        conflict = True
    custom = req.get("custom_category") if decl == "other" else None
    label = custom or CATEGORY_LABELS.get(top) or top.replace("_", " ").title()
    return {
        "category": top,
        "display_category": label,
        "declared_category": decl,
        "custom_category": custom,
        "in_corpus": top in IN_CORPUS and not conflict,
        "conflict": conflict,
        "scores": scores,
    }
