from __future__ import annotations

import os
from typing import Any

import streamlit as st

from app.category import CATEGORY_LABELS
from app.frontend_client import BackendError, assess_label, get_readiness, get_trace
from app.samples import make

st.set_page_config(
    page_title="FSSAI Food Label Compliance Checker",
    page_icon="F",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --forest: #174b39;
        --forest-dark: #10382b;
        --green-soft: #eaf3ed;
        --ink: #1d2b25;
        --muted: #64736b;
        --line: #e2e9e4;
        --canvas: #f7f9f7;
        --amber: #8a5a08;
        --amber-soft: #fff5df;
        --red: #9c2f2f;
        --red-soft: #fff0ef;
    }
    .stApp { background: var(--canvas); color: var(--ink); }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stSidebar"] { background: #fff; border-right: 1px solid var(--line); }
    [data-testid="stSidebar"] h1 { color: var(--forest); font-size: 1.15rem; }
    .block-container { max-width: 1220px; padding-top: 1.2rem; padding-bottom: 3rem; }
    h1, h2, h3 { color: var(--ink); letter-spacing: -0.025em; }
    h1 { font-size: clamp(1.7rem, 3vw, 2.25rem); }
    h2 { font-size: 1.35rem; }
    .app-header {
        display: flex; justify-content: space-between; align-items: center;
        padding: .3rem 0 1rem; border-bottom: 1px solid var(--line); margin-bottom: 1.5rem;
    }
    .app-brand { color: var(--forest); font-size: 1.05rem; font-weight: 700; }
    .app-subtitle { color: var(--muted); font-size: .88rem; margin-top: .15rem; }
    .status-pill {
        display: inline-flex; align-items: center; gap: .45rem;
        padding: .42rem .7rem; border-radius: 999px;
        background: var(--green-soft); color: var(--forest); font-size: .8rem; font-weight: 600;
    }
    .status-dot { height: .48rem; width: .48rem; border-radius: 50%; background: #4a896a; }
    .hero {
        padding: clamp(1.35rem, 4vw, 2.4rem); border: 1px solid var(--line);
        border-radius: 1.1rem; background: linear-gradient(120deg, #fff, #f0f6f1);
    }
    .hero p { color: var(--muted); max-width: 730px; font-size: 1rem; line-height: 1.65; }
    .section-note { color: var(--muted); font-size: .9rem; }
    div.stButton > button[kind="primary"], div.stFormSubmitButton > button[kind="primary"] {
        background: var(--forest); border-color: var(--forest); color: #fff; border-radius: .65rem;
        min-height: 2.8rem; font-weight: 650;
    }
    div.stButton > button[kind="primary"]:hover, div.stFormSubmitButton > button[kind="primary"]:hover {
        background: var(--forest-dark); border-color: var(--forest-dark);
    }
    div[data-testid="stExpander"] {
        border: 1px solid var(--line); border-radius: .8rem; background: #fff;
    }
    div[data-testid="stForm"] {
        border: 1px solid var(--line); border-radius: 1rem; background: #fff; padding: 1rem 1.2rem;
    }
    [data-testid="stMetric"] {
        background: #fff; border: 1px solid var(--line); border-radius: .8rem; padding: .8rem 1rem;
    }
    @media (max-width: 720px) {
        .block-container { padding: .8rem 1rem 2rem; }
        .app-header { align-items: flex-start; gap: .6rem; flex-direction: column; }
        [data-testid="stMetric"] { padding: .65rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="app-header">
      <div>
        <div class="app-brand">FSSAI | Food Label Review</div>
        <div class="app-subtitle">Evidence-led decision support for packaged food labels</div>
      </div>
      <div class="status-pill"><span class="status-dot"></span>Evidence coverage varies by category</div>
    </div>
    """,
    unsafe_allow_html=True,
)

SAMPLES = {
    "Structured label example": make(),
    "Protein-claim example": make(
        front_of_pack_text=["Source of Protein"],
        nutrition={"protein_g": 4.0},
    ),
    "Human-review example": make(
        front_of_pack_text=["Boosts Immunity"],
    ),
}
NUTRIENTS = (
    ("energy_kcal", "Energy (kcal)", 900.0),
    ("protein_g", "Protein (g)", 100.0),
    ("carbohydrate_g", "Carbohydrate (g)", 100.0),
    ("total_sugars_g", "Total sugars (g)", 100.0),
    ("added_sugars_g", "Added sugars (g)", 100.0),
    ("dietary_fibre_g", "Dietary fibre (g)", 100.0),
    ("total_fat_g", "Total fat (g)", 100.0),
    ("saturated_fat_g", "Saturated fat (g)", 100.0),
    ("trans_fat_g", "Trans fat (g)", 100.0),
    ("sodium_mg", "Sodium (mg)", 40000.0),
)
CATEGORIES = [
    ("biscuits_bakery", CATEGORY_LABELS["biscuits_bakery"]),
    ("beverages_juices", CATEGORY_LABELS["beverages_juices"]),
    ("dairy_products", CATEGORY_LABELS["dairy_products"]),
    ("snacks_savoury", CATEGORY_LABELS["snacks_savoury"]),
    ("confectionery_chocolates", CATEGORY_LABELS["confectionery_chocolates"]),
    ("cereals_breakfast", CATEGORY_LABELS["cereals_breakfast"]),
    ("instant_ready_to_eat", CATEGORY_LABELS["instant_ready_to_eat"]),
    ("spices_seasonings", CATEGORY_LABELS["spices_seasonings"]),
    ("sauces_dips_condiments", CATEGORY_LABELS["sauces_dips_condiments"]),
    ("edible_oils_fats", CATEGORY_LABELS["edible_oils_fats"]),
    ("pulses_packaged_grains", CATEGORY_LABELS["pulses_packaged_grains"]),
    ("nutritional_health_foods", CATEGORY_LABELS["nutritional_health_foods"]),
    ("other", "Other packaged food"),
]
CATEGORY_VALUES = [item[0] for item in CATEGORIES]
CATEGORY_LABEL_BY_VALUE = dict(CATEGORIES)
FORM_KEYS = {
    "product_name": "form_product_name",
    "brand_name": "form_brand_name",
    "declared_category": "form_declared_category",
    "custom_category": "form_custom_category",
    "physical_state": "form_physical_state",
    "net_quantity_value": "form_net_quantity_value",
    "net_quantity_unit": "form_net_quantity_unit",
    "package_type": "form_package_type",
    "package_surface_area_cm2": "form_surface_area",
    "ingredients_text": "form_ingredients",
    "front_of_pack_text": "form_claims",
    "diet_mark": "form_diet_mark",
    "allergen_statement": "form_allergens",
    "fssai_license_no": "form_license",
    "fssai_logo_present": "form_logo",
    "manufacturer_name": "form_manufacturer_name",
    "manufacturer_address": "form_manufacturer_address",
    "batch_marking_present": "form_batch",
    "date_marking": "form_date_marking",
    "is_imported": "form_imported",
    "country_of_origin": "form_country_of_origin",
    "include_nutrition": "form_include_nutrition",
}


def _load_sample(payload: dict[str, Any]) -> None:
    nutrition = payload.get("nutrition") or {}
    values = {
        "product_name": payload["product_name"],
        "brand_name": payload.get("brand_name") or "",
        "declared_category": payload.get("declared_category", "biscuits_bakery"),
        "custom_category": payload.get("custom_category") or "",
        "physical_state": payload["physical_state"],
        "net_quantity_value": float(payload["net_quantity_value"]),
        "net_quantity_unit": payload["net_quantity_unit"],
        "package_type": payload["package_type"],
        "package_surface_area_cm2": float(payload["package_surface_area_cm2"]),
        "ingredients_text": payload["ingredients_text"],
        "front_of_pack_text": "\n".join(payload.get("front_of_pack_text", [])),
        "diet_mark": payload["diet_mark"],
        "allergen_statement": payload.get("allergen_statement") or "",
        "fssai_license_no": payload.get("fssai_license_no") or "",
        "fssai_logo_present": payload["fssai_logo_present"],
        "manufacturer_name": payload.get("manufacturer_name") or "",
        "manufacturer_address": payload.get("manufacturer_address") or "",
        "batch_marking_present": payload["batch_marking_present"],
        "date_marking": payload["date_marking"],
        "is_imported": payload["is_imported"],
        "country_of_origin": payload.get("country_of_origin") or "",
        "include_nutrition": payload.get("nutrition") is not None,
    }
    for field, key in FORM_KEYS.items():
        st.session_state[key] = values[field]
    for name, _, _ in NUTRIENTS:
        st.session_state[f"nutrition_{name}"] = float(nutrition.get(name) or 0)


def _build_payload(values: dict[str, Any]) -> dict[str, Any]:
    nutrition = None
    if values["include_nutrition"]:
        nutrition = {name: float(values[name]) for name, _, _ in NUTRIENTS}
    country = str(values["country_of_origin"]).strip() or None
    category = values["declared_category"]
    payload = {
        "schema_version": "1.0",
        "product_name": str(values["product_name"]).strip(),
        "brand_name": str(values["brand_name"]).strip() or None,
        "declared_category": category,
        "physical_state": values["physical_state"],
        "net_quantity_value": float(values["net_quantity_value"]),
        "net_quantity_unit": values["net_quantity_unit"],
        "package_type": values["package_type"],
        "package_surface_area_cm2": float(values["package_surface_area_cm2"]),
        "ingredients_text": str(values["ingredients_text"]).strip(),
        "front_of_pack_text": [
            line.strip()
            for line in str(values["front_of_pack_text"]).splitlines()
            if line.strip()
        ],
        "diet_mark": values["diet_mark"],
        "allergen_statement": str(values["allergen_statement"]).strip() or None,
        "fssai_license_no": str(values["fssai_license_no"]).strip() or None,
        "fssai_logo_present": bool(values["fssai_logo_present"]),
        "manufacturer_name": str(values["manufacturer_name"]).strip() or None,
        "manufacturer_address": str(values["manufacturer_address"]).strip() or None,
        "batch_marking_present": bool(values["batch_marking_present"]),
        "date_marking": values["date_marking"],
        "is_imported": bool(values["is_imported"]),
        "country_of_origin": country,
        "nutrition": nutrition,
    }
    if category == "other":
        payload["custom_category"] = str(values.get("custom_category", "")).strip()
    return payload


def _source_versions(result: dict[str, Any]) -> dict[str, Any]:
    versions = result.get("versions")
    if not isinstance(versions, dict):
        return {}
    corpus = versions.get("corpus")
    if not isinstance(corpus, dict):
        return {}
    return {doc_id: metadata for doc_id, metadata in corpus.items() if isinstance(doc_id, str)}


def _status_label(status: str) -> str:
    return {
        "met": "PASSED CHECK",
        "unmet": "NEEDS ATTENTION",
        "needs_human": "HUMAN REVIEW",
        "not_applicable": "NOT APPLICABLE",
    }.get(status, status.replace("_", " ").upper())


def _start_assessment() -> None:
    selected = st.session_state.get("landing_category", "biscuits_bakery")
    st.session_state[FORM_KEYS["declared_category"]] = selected
    st.session_state["navigation"] = "New assessment"


def _render_citations(finding: dict[str, Any], versions: dict[str, Any]) -> None:
    citations = finding.get("citations")
    if not isinstance(citations, list) or not citations:
        st.caption("No supporting quotation was attached to this finding.")
        return
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        source_id = citation.get("doc_id")
        source_id = source_id if isinstance(source_id, str) and source_id else "Unknown document"
        metadata = versions.get(source_id)
        if isinstance(metadata, str):
            source_title, source_version = source_id, metadata
        elif isinstance(metadata, dict):
            title, version = metadata.get("title"), metadata.get("version")
            source_title = title if isinstance(title, str) and title else source_id
            source_version = version if isinstance(version, str) and version else "version unavailable"
        else:
            source_title, source_version = source_id, "version unavailable"
        clause_id = citation.get("clause_id")
        chunk_id = citation.get("chunk_id")
        quote = citation.get("quote")
        st.markdown(
            f"**Source:** `{source_id}` ({source_title}) · {source_version}  \n"
            f"**Clause:** `{clause_id if isinstance(clause_id, str) and clause_id else 'not supplied'}`  \n"
            f"**Evidence ID:** `{chunk_id if isinstance(chunk_id, str) and chunk_id else 'not supplied'}`"
        )
        if isinstance(quote, str) and quote.strip():
            st.code(quote, language=None)


def _render_finding_group(
    heading: str,
    items: list[dict[str, Any]],
    versions: dict[str, Any],
    *,
    expanded: bool = False,
) -> None:
    st.subheader(heading)
    if not items:
        st.caption("No findings in this group.")
        return
    for finding in items:
        status = finding.get("status", "needs_human")
        title = finding.get("title") or finding.get("id") or "Assessment item"
        with st.expander(f"{_status_label(status)} · {title}", expanded=expanded):
            st.write(finding.get("detail") or "No explanation was provided.")
            refs = finding.get("clause_refs") or [finding.get("clause_ref")]
            refs = [ref for ref in refs if isinstance(ref, str) and ref]
            if refs:
                st.markdown("**Clause reference(s):** " + ", ".join(f"`{ref}`" for ref in refs))
            _render_citations(finding, versions)


def _render_results(result: dict[str, Any]) -> None:
    route = result.get("route", "regulatory-review")
    category = result.get("category_details")
    category_name = (
        category.get("display_category")
        if isinstance(category, dict)
        else result.get("category", "not supplied")
    )
    st.caption(f"Selected category: {category_name}")
    st.caption("Decision support only. This result is not certification or approval to print.")
    if not result.get("complete", True) or route == "regulatory-review":
        st.warning(
            "Human review required. The available category workflow or evidence was insufficient "
            "for a supported determination."
        )
    elif route == "revise-and-recheck":
        st.warning("One or more supplied label details need attention before reassessment.")
    else:
        st.info("No open items were identified in the checks performed. This is not an approval to print.")
    if result.get("route_reason"):
        st.write(result["route_reason"])

    findings = result.get("findings")
    findings = [item for item in findings if isinstance(item, dict)] if isinstance(findings, list) else []
    counts = [
        ("Needs attention", sum(item.get("status") == "unmet" for item in findings)),
        ("Human review", sum(item.get("status") == "needs_human" for item in findings)),
        ("Passed checks", sum(item.get("status") == "met" for item in findings)),
    ]
    columns = st.columns(3)
    for column, (label, count) in zip(columns, counts):
        column.metric(label, count)

    versions = _source_versions(result)
    _render_finding_group("Items requiring human review", [f for f in findings if f.get("status") == "needs_human"], versions, expanded=True)
    _render_finding_group("Items needing attention", [f for f in findings if f.get("status") == "unmet"], versions, expanded=True)
    _render_finding_group("Passed checks", [f for f in findings if f.get("status") == "met"], versions)
    _render_finding_group("Not applicable", [f for f in findings if f.get("status") == "not_applicable"], versions)

    escalations = result.get("escalations")
    if isinstance(escalations, list) and escalations:
        with st.expander("Why human review was requested"):
            for item in escalations:
                if isinstance(item, dict):
                    st.markdown(f"- **{item.get('trigger', 'Review')}:** {item.get('detail', '')}")
    st.caption(result.get("disclaimer", "A qualified professional makes the final regulatory decision."))


st.sidebar.title("FSSAI | Label Review")
api_base = st.sidebar.text_input(
    "FastAPI address",
    value=os.getenv("FSSAI_API_BASE_URL", "http://127.0.0.1:8000"),
    help="Address reachable from this Streamlit process.",
)
page = st.sidebar.radio(
    "Workspace",
    ["Home", "New assessment", "Results", "Evidence & sources", "About"],
    key="navigation",
)
with st.sidebar.expander("Important limitation"):
    st.caption(
        "Category selection does not prove regulatory coverage. Checks depend on verified "
        "documents in the active corpus; unsupported categories are escalated."
    )

if page == "Home":
    st.markdown(
        """
        <div class="hero">
          <h1>Review a food label with traceable evidence</h1>
          <p>Enter structured product and package details. The checker validates the submission,
          retrieves available regulatory passages, and flags gaps that need a qualified reviewer.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    left, right = st.columns([1.35, 1], gap="large")
    with left:
        st.subheader("Start with a product category")
        st.selectbox(
            "Food category",
            CATEGORY_VALUES,
            format_func=lambda value: CATEGORY_LABEL_BY_VALUE[value],
            key="landing_category",
        )
        st.caption(
            "The category list is for describing your product, not a promise of coverage. "
            "Automated category-specific handling is currently configured only for the existing "
            "biscuits and bakery workflow; other selections are routed for human review."
        )
        st.button("Check a food label", type="primary", on_click=_start_assessment, use_container_width=True)
    with right:
        try:
            readiness = get_readiness(api_base)
            if readiness.get("ready"):
                st.success("Evidence service is online")
                st.caption(readiness.get("checks", {}).get("index", "Index status unavailable"))
            else:
                st.warning("Evidence service is not ready")
                st.caption(str(readiness.get("checks", {})))
        except BackendError as exc:
            st.warning("Evidence service is currently unreachable")
            st.caption(str(exc))
        with st.container(border=True):
            st.markdown("**How it works**")
            st.markdown(
                "1. Validate label fields.\n"
                "2. Retrieve passages from the active corpus.\n"
                "3. Present cited findings or request human review."
            )
    st.info("A result is decision support only. Confirm applicable requirements with a qualified regulatory professional.")

elif page == "New assessment":
    st.title("Food label details")
    st.caption("Required fields are marked *. Optional fields may be left blank. This form does not read package images or artwork.")
    with st.expander("Load a demonstration example", expanded=False):
        sample_name = st.selectbox("Example", list(SAMPLES), key="selected_sample")
        if st.button("Load example", key="load_sample"):
            _load_sample(SAMPLES[sample_name])
            st.rerun()

    default_sample = SAMPLES["Structured label example"]
    nutrition_default = default_sample.get("nutrition") or {}
    with st.form("label_assessment"):
        with st.expander("1 · Product information", expanded=True):
            product_name = st.text_input("Product name *", value=default_sample["product_name"], key=FORM_KEYS["product_name"], placeholder="Name as shown on the package")
            brand_name = st.text_input("Brand name (optional)", value=default_sample.get("brand_name") or "", key=FORM_KEYS["brand_name"])
            category = st.selectbox(
                "Food category *",
                CATEGORY_VALUES,
                format_func=lambda value: CATEGORY_LABEL_BY_VALUE[value],
                key=FORM_KEYS["declared_category"],
            )
            custom_category = ""
            if category == "other":
                custom_category = st.text_input(
                    "Describe the food category *",
                    key=FORM_KEYS["custom_category"],
                    placeholder="For example, a short product category description",
                    help="This description is recorded for the reviewer; it does not add regulatory coverage.",
                )
            st.info(
                "Coverage depends on verified documents in the active corpus. Only the existing "
                "biscuits and bakery workflow is configured for automated category handling; "
                "other categories are submitted but escalated for human review."
            )
            physical_state = st.selectbox("Physical state *", ["solid", "liquid"], key=FORM_KEYS["physical_state"])

        with st.expander("2 · Ingredients and composition", expanded=True):
            ingredients = st.text_area("Ingredients list *", key=FORM_KEYS["ingredients_text"], placeholder="Enter the ingredients in the order shown on the label")
            allergens = st.text_input("Allergen statement (optional)", key=FORM_KEYS["allergen_statement"])
            include_nutrition = st.checkbox("Nutrition panel is available", key=FORM_KEYS["include_nutrition"], value=True)
            nutrient_values: dict[str, float] = {}
            if include_nutrition:
                st.caption("Enter values per 100 g for solids or per 100 ml for liquids.")
                columns = st.columns(2)
                for i, (name, label, maximum) in enumerate(NUTRIENTS):
                    with columns[i % 2]:
                        nutrient_values[name] = st.number_input(
                            label,
                            min_value=0.0,
                            max_value=maximum,
                            value=float(nutrition_default.get(name) or 0),
                            key=f"nutrition_{name}",
                        )

        with st.expander("3 · Packaging and label declarations", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                quantity = st.number_input("Net quantity *", min_value=0.01, value=float(default_sample["net_quantity_value"]), key=FORM_KEYS["net_quantity_value"])
                unit = st.selectbox("Net quantity unit *", ["g", "kg", "ml", "l"], key=FORM_KEYS["net_quantity_unit"])
                package_type = st.selectbox("Package type *", ["pouch", "box", "wrapper", "bottle", "jar", "can", "other"], key=FORM_KEYS["package_type"])
                surface = st.number_input("Package surface area (cm²) *", min_value=0.01, max_value=10000.0, value=float(default_sample["package_surface_area_cm2"]), key=FORM_KEYS["package_surface_area_cm2"])
                date_marking = st.selectbox("Date marking type *", ["best_before", "use_by", "expiry", "none"], key=FORM_KEYS["date_marking"])
            with c2:
                diet_mark = st.selectbox("Vegetarian / non-vegetarian mark *", ["veg", "non_veg", "none"], key=FORM_KEYS["diet_mark"])
                claims = st.text_area("Claims and front-of-pack text (optional; one per line)", key=FORM_KEYS["front_of_pack_text"], placeholder="Enter claims and declarations as printed")
                license_no = st.text_input("FSSAI licence number (optional; 14 digits)", key=FORM_KEYS["fssai_license_no"])
                logo = st.checkbox("FSSAI logo present", key=FORM_KEYS["fssai_logo_present"], value=True)
            manufacturer = st.text_input("Manufacturer name (optional)", key=FORM_KEYS["manufacturer_name"])
            address = st.text_input("Manufacturer address (optional)", key=FORM_KEYS["manufacturer_address"])
            c1, c2 = st.columns(2)
            with c1:
                batch = st.checkbox("Batch marking present", key=FORM_KEYS["batch_marking_present"], value=True)
            with c2:
                imported = st.checkbox("Imported product", key=FORM_KEYS["is_imported"])
                country = st.text_input("Country of origin (required if imported)", key=FORM_KEYS["country_of_origin"])

        submitted = st.form_submit_button(
            "Submit for evidence review",
            type="primary",
            disabled=bool(st.session_state.get("assessment_in_progress")),
            use_container_width=True,
        )

    if submitted:
        if category == "other" and not custom_category.strip():
            st.error("Enter a custom category when selecting Other packaged food.")
        elif not product_name.strip() or not ingredients.strip():
            st.error("Product name and ingredients list are required.")
        else:
            values = {
                "product_name": product_name,
                "brand_name": brand_name,
                "declared_category": category,
                "custom_category": custom_category,
                "physical_state": physical_state,
                "net_quantity_value": quantity,
                "net_quantity_unit": unit,
                "package_type": package_type,
                "package_surface_area_cm2": surface,
                "ingredients_text": ingredients,
                "front_of_pack_text": claims,
                "diet_mark": diet_mark,
                "allergen_statement": allergens,
                "fssai_license_no": license_no,
                "fssai_logo_present": logo,
                "manufacturer_name": manufacturer,
                "manufacturer_address": address,
                "batch_marking_present": batch,
                "date_marking": date_marking,
                "is_imported": imported,
                "country_of_origin": country,
                "include_nutrition": include_nutrition,
                **nutrient_values,
            }
            payload = _build_payload(values)
            st.session_state["assessment_in_progress"] = True
            status_panel = st.status("Submitting label for review…", expanded=True)
            progress = st.progress(0, text="Waiting for the review queue")
            progress_by_status = {"queued": 20, "researching": 50, "assessing": 80, "completed": 100, "failed": 100}

            def update_status(state: str) -> None:
                progress.progress(progress_by_status.get(state, 15), text=f"Assessment status: {state}")
                status_panel.update(label=f"Assessment status: {state}")

            try:
                result, run_id = assess_label(api_base, payload, on_status=update_status)
                st.session_state["last_result"] = result
                st.session_state["last_run_id"] = run_id
                st.session_state["last_api_base"] = api_base
                status_panel.update(label="Assessment finished.", state="complete")
                progress.progress(100, text="Review complete")
                st.success("Assessment complete. Open Results to review findings and citations.")
            except BackendError as exc:
                status_panel.update(label="Assessment could not be completed.", state="error")
                st.error(str(exc))
            finally:
                st.session_state["assessment_in_progress"] = False

elif page == "Results":
    st.title("Assessment results")
    result = st.session_state.get("last_result")
    if not isinstance(result, dict):
        st.info("No assessment is available in this session. Start a label review to see cited findings.")
        st.button("Start a label review", type="primary", on_click=_start_assessment)
    else:
        _render_results(result)
        with st.expander("Technical run details"):
            st.caption(f"Run ID: {st.session_state.get('last_run_id', result.get('run_id', 'not supplied'))}")
            if result.get("versions"):
                st.json(result["versions"])
        st.button("Start another assessment", type="primary", on_click=_start_assessment)

elif page == "Evidence & sources":
    st.title("Evidence and source trace")
    run_id = st.session_state.get("last_run_id")
    if not run_id:
        st.info("Submit an assessment to inspect retrieved passages and the research trace.")
    else:
        try:
            trace = get_trace(st.session_state.get("last_api_base", api_base), run_id)
            st.caption(f"Run ID: {run_id} · status: {trace.get('status', 'unknown')}")
            passages = trace.get("passages_retrieved")
            passages = passages if isinstance(passages, list) else []
            if not passages:
                st.warning("No retrieved passages were returned. This can occur when the category is outside the configured workflow.")
            for passage in passages:
                if not isinstance(passage, dict):
                    continue
                heading = (
                    f"{passage.get('doc_title') or passage.get('doc_id') or 'Source'} · "
                    f"{passage.get('doc_version') or 'version unavailable'} · "
                    f"{passage.get('clause_id') or 'clause unavailable'}"
                )
                with st.expander(heading):
                    st.caption(f"Source ID: {passage.get('doc_id', 'not supplied')} · Chunk: {passage.get('chunk_id', 'not supplied')}")
                    if passage.get("title"):
                        st.markdown(f"**Passage heading:** {passage['title']}")
                    st.code(passage.get("text", ""), language=None)
            with st.expander("Research and verification trace"):
                st.json(trace.get("events", []))
        except BackendError as exc:
            st.error(str(exc))

else:
    st.title("About this checker")
    st.markdown(
        """
        This project validates structured label data, retrieves passages from the active corpus,
        and presents findings for review. The category selector accepts common packaged-food
        descriptions, but selection alone does not establish regulatory coverage.

        **Coverage:** The existing automated category workflow is configured for biscuits and
        bakery snacks. Other categories are accepted as input but escalated for human review.
        General labelling provisions and category-specific requirements are distinct; category-
        specific requirements are not inferred from product names or applied without verified
        supporting sources in the active corpus.

        **Limitations:** The application does not inspect artwork, perform OCR, or accept uploaded
        label PDFs. It does not record actual date values or verify every exemption. Source edition,
        amendment status, and extraction quality must be checked by a qualified professional.

        This tool is not legal advice, FSSAI certification, or approval to print.
        """
    )
