from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_results_page_renders_citation_source_version_clause_and_quote():
    result = {
        "route": "revise-and-recheck",
        "findings": [
            {
                "id": "CLAIM:source_of_protein",
                "title": "Source of Protein",
                "status": "unmet",
                "detail": "The declared value does not meet the retrieved condition.",
                "clause_ref": "ACR-2018:Schedule I/Protein",
                "citations": [
                    {
                        "doc_id": "ACR-2018",
                        "clause_id": "ACR-2018:Schedule I/Protein",
                        "chunk_id": "protein-chunk",
                        "quote": "Source of protein: at least 10% of RDA per 100 g.",
                    }
                ],
            }
        ],
        "versions": {
            "corpus": {
                "ACR-2018": "Compendium (04.10.2022)",
            }
        },
        "disclaimer": "Human review required.",
    }

    app = AppTest.from_file(str(ROOT / "streamlit_app.py"))
    app.session_state["navigation"] = "Results"
    app.session_state["last_result"] = result
    app.run()

    assert not app.exception
    rendered_markdown = "\n".join(element.value for element in app.markdown)
    rendered_quotes = [element.value for element in app.code]

    assert "**Source:** `ACR-2018`" in rendered_markdown
    assert "Compendium (04.10.2022)" in rendered_markdown
    assert "**Clause:** `ACR-2018:Schedule I/Protein`" in rendered_markdown
    assert "Source of protein: at least 10% of RDA per 100 g." in rendered_quotes


def test_results_page_handles_missing_or_unexpected_citation_metadata():
    result = {
        "route": "regulatory-review",
        "findings": [
            {
                "id": "R01_name",
                "title": "Product name",
                "status": "needs_human",
                "citations": [
                    {
                        "doc_id": "LDR-2020",
                        "clause_id": None,
                        "chunk_id": None,
                        "quote": None,
                    },
                    "unexpected citation shape",
                ],
            }
        ],
        "versions": None,
    }

    app = AppTest.from_file(str(ROOT / "streamlit_app.py"))
    app.session_state["navigation"] = "Results"
    app.session_state["last_result"] = result
    app.run()

    assert not app.exception
    rendered_markdown = "\n".join(element.value for element in app.markdown)
    assert "**Source:** `LDR-2020`" in rendered_markdown
    assert "version unavailable" in rendered_markdown
    assert "**Clause:** `not supplied`" in rendered_markdown
    assert [element.value for element in app.code] == []


def test_home_shows_expanded_category_options_and_coverage_notice():
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"))
    app.session_state["navigation"] = "Home"
    app.run()

    assert not app.exception
    category_box = next(
        element for element in app.selectbox if element.label == "Food category"
    )
    assert {
        "Biscuits and Bakery",
        "Beverages and Juices",
        "Dairy Products (including milk products)",
        "Snacks and Savoury Products",
        "Confectionery and Chocolates",
        "Cereals and Breakfast Products",
        "Instant and Ready-to-Eat Foods",
        "Spices and Seasonings",
        "Sauces, Dips and Condiments",
        "Edible Oils and Fats",
        "Pulses and Packaged Grains",
        "Nutritional and Health Foods",
        "Other packaged food",
    } <= set(category_box.options)
    assert any("does not prove regulatory coverage" in item.value for item in app.caption)


def test_other_category_shows_custom_category_input():
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"))
    app.session_state["navigation"] = "New assessment"
    app.session_state["form_declared_category"] = "other"
    app.run()

    assert not app.exception
    assert any(
        item.label == "Describe the food category *"
        for item in app.text_input
    )


def test_results_keep_human_review_distinct_from_passed_checks():
    result = {
        "route": "regulatory-review",
        "category": "dairy_products",
        "category_details": {"display_category": "Dairy Products (including milk products)"},
        "findings": [
            {"id": "category-review", "title": "Category coverage", "status": "needs_human", "detail": "No category-specific assessment was made.", "citations": []},
            {"id": "general-check", "title": "General check", "status": "met", "detail": "Evidence available.", "citations": []},
        ],
        "escalations": [{"trigger": "category_outside_corpus", "detail": "Category workflow is not configured."}],
    }
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"))
    app.session_state["navigation"] = "Results"
    app.session_state["last_result"] = result
    app.run()

    assert not app.exception
    rendered = "\n".join(item.value for item in app.markdown)
    captions = "\n".join(item.value for item in app.caption)
    assert "Dairy Products (including milk products)" in captions
    assert any("Human review required" in item.value for item in app.warning)
    assert any(item.label.startswith("HUMAN REVIEW") for item in app.expander)
    assert any(item.label.startswith("PASSED CHECK") for item in app.expander)
