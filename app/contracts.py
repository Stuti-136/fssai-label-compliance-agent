"""Data contract for POST /v1/runs (D1, F2). Schema, type, range, category and cross-field validation.
Export JSON Schema:  python -m app.contracts"""
from __future__ import annotations
import json, sys
from typing import Literal, Optional
from pydantic import BaseModel, Field, ValidationError, model_validator
from . import guardrails

Category = Literal["unspecified", "biscuits_bakery", "dairy", "beverages", "meat_fish", "infant_nutrition",
                   "supplements", "confectionery", "other"]


class Nutrition(BaseModel):
    """Values per 100 g (solids) or per 100 ml (liquids)."""
    model_config = {"extra": "forbid"}
    energy_kcal: Optional[float] = Field(None, ge=0, le=900)
    protein_g: Optional[float] = Field(None, ge=0, le=100)
    carbohydrate_g: Optional[float] = Field(None, ge=0, le=100)
    total_sugars_g: Optional[float] = Field(None, ge=0, le=100)
    added_sugars_g: Optional[float] = Field(None, ge=0, le=100)
    dietary_fibre_g: Optional[float] = Field(None, ge=0, le=100)
    total_fat_g: Optional[float] = Field(None, ge=0, le=100)
    saturated_fat_g: Optional[float] = Field(None, ge=0, le=100)
    trans_fat_g: Optional[float] = Field(None, ge=0, le=100)
    sodium_mg: Optional[float] = Field(None, ge=0, le=40000)

    @model_validator(mode="after")
    def cross(self):
        def le(a, b, msg):
            if a is not None and b is not None and a > b + 1e-9:
                raise ValueError(msg)
        le(self.total_sugars_g, self.carbohydrate_g, "total_sugars_g cannot exceed carbohydrate_g")
        le(self.added_sugars_g, self.total_sugars_g, "added_sugars_g cannot exceed total_sugars_g")
        if self.saturated_fat_g is not None and self.total_fat_g is not None:
            le((self.saturated_fat_g or 0) + (self.trans_fat_g or 0), self.total_fat_g,
               "saturated_fat_g + trans_fat_g cannot exceed total_fat_g")
        if None not in (self.energy_kcal, self.protein_g, self.carbohydrate_g, self.total_fat_g) and self.energy_kcal > 20:
            est = 4 * (self.protein_g + self.carbohydrate_g) + 9 * self.total_fat_g
            if est > 0 and abs(self.energy_kcal - est) / est > 0.35:
                raise ValueError(f"energy_kcal ({self.energy_kcal}) inconsistent with macronutrients (~{est:.0f} kcal)")
        return self


class LabelRequest(BaseModel):
    model_config = {"extra": "forbid"}
    schema_version: Literal["1.0"] = "1.0"
    product_name: str = Field(..., min_length=2, max_length=120)
    brand_name: Optional[str] = Field(None, max_length=80)
    declared_category: Category = "unspecified"
    physical_state: Literal["solid", "liquid"]
    net_quantity_value: float = Field(..., gt=0, le=100000)
    net_quantity_unit: Literal["g", "kg", "ml", "l"]
    package_type: Literal["pouch", "box", "wrapper", "bottle", "jar", "can", "other"]
    package_surface_area_cm2: float = Field(..., gt=0, le=10000)
    ingredients_text: str = Field(..., min_length=3, max_length=2000)
    front_of_pack_text: list[str] = Field(default_factory=list, max_length=20)
    diet_mark: Literal["veg", "non_veg", "none"]
    allergen_statement: Optional[str] = Field(None, max_length=500)
    fssai_license_no: Optional[str] = Field(None, pattern=r"^\d{14}$")
    fssai_logo_present: bool
    manufacturer_name: Optional[str] = Field(None, max_length=120)
    manufacturer_address: Optional[str] = Field(None, max_length=300)
    batch_marking_present: bool
    date_marking: Literal["best_before", "use_by", "expiry", "none"]
    is_imported: bool = False
    country_of_origin: Optional[str] = Field(None, max_length=60)
    nutrition: Optional[Nutrition] = None

    @model_validator(mode="after")
    def cross(self):
        if self.physical_state == "solid" and self.net_quantity_unit not in ("g", "kg"):
            raise ValueError("solid products must use net_quantity_unit g or kg")
        if self.physical_state == "liquid" and self.net_quantity_unit not in ("ml", "l"):
            raise ValueError("liquid products must use net_quantity_unit ml or l")
        if self.is_imported and not self.country_of_origin:
            raise ValueError("country_of_origin is required when is_imported is true")
        for t in self.front_of_pack_text:
            if len(t) > 200:
                raise ValueError("each front_of_pack_text entry must be <= 200 characters")
        return self

    def free_text_fields(self) -> dict[str, str]:
        d = {"product_name": self.product_name, "brand_name": self.brand_name or "",
             "ingredients_text": self.ingredients_text, "allergen_statement": self.allergen_statement or "",
             "manufacturer_name": self.manufacturer_name or "", "manufacturer_address": self.manufacturer_address or "",
             "country_of_origin": self.country_of_origin or ""}
        for i, t in enumerate(self.front_of_pack_text):
            d[f"front_of_pack_text[{i}]"] = t
        return d


def validate_request(payload) -> tuple[Optional[LabelRequest], list[dict]]:
    """Returns (model, []) or (None, field-level errors). Guardrails run here, before any agent starts."""
    if not isinstance(payload, dict):
        return None, [{"field": "$", "code": "invalid_type", "message": "body must be a JSON object"}]
    try:
        req = LabelRequest.model_validate(payload)
    except ValidationError as e:
        errs = []
        for x in e.errors():
            loc = ".".join(str(p) for p in x["loc"]) or "$"
            errs.append({"field": loc, "code": x["type"], "message": x["msg"].replace("Value error, ", "")})
        return None, errs
    g = guardrails.check_free_text(req.free_text_fields())
    return (None, g) if g else (req, [])


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "contracts/label_request.v1.schema.json"
    json.dump(LabelRequest.model_json_schema(), open(out, "w"), indent=2)
    print("wrote", out)
