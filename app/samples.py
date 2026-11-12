"""Reference request used by tests, the evaluation set builder and demo samples."""
import copy

BASE = {
    "schema_version": "1.0", "product_name": "Crunchy Oat Digestive Biscuits", "brand_name": "Wholesome Bakes",
    "declared_category": "biscuits_bakery", "physical_state": "solid", "net_quantity_value": 200, "net_quantity_unit": "g",
    "package_type": "wrapper", "package_surface_area_cm2": 420,
    "ingredients_text": "Refined wheat flour (maida), whole wheat flour, rolled oats, sugar, edible vegetable oil (palm), invert syrup, raising agents (INS 500(ii), INS 503(ii)), iodised salt, emulsifier (INS 322), milk solids.",
    "front_of_pack_text": ["Crunchy Oat Digestive Biscuits", "Baked, not fried"], "diet_mark": "veg",
    "allergen_statement": "Contains wheat (gluten), oats and milk.", "fssai_license_no": "10020021001234", "fssai_logo_present": True,
    "manufacturer_name": "Wholesome Bakes Pvt Ltd", "manufacturer_address": "Plot 12, Industrial Area, Bengaluru, Karnataka 560058",
    "batch_marking_present": True, "date_marking": "best_before", "is_imported": False,
    "nutrition": {"energy_kcal": 470, "protein_g": 7.0, "carbohydrate_g": 66, "total_sugars_g": 18, "added_sugars_g": 16,
                  "dietary_fibre_g": 4, "total_fat_g": 19, "saturated_fat_g": 9, "trans_fat_g": 0.1, "sodium_mg": 380},
}


def make(**over):
    d = copy.deepcopy(BASE)
    nut = over.pop("nutrition", None)
    for k, v in over.items():
        d[k] = v
    if nut is not None:
        d["nutrition"] = {**d["nutrition"], **nut} if isinstance(nut, dict) else nut
    return d
