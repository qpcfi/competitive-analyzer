from agents.analyzer.node import build_deterministic_analysis


def test_analyzer_matrix_uses_schema_dimensions_and_collected_competitors():
    state = {
        "task_context": {"competitors": ["Alpha"]},
        "dynamic_schema": {
            "Core": [
                {"id": "Core.Pricing", "name": "Pricing"},
                {"id": "Core.SLA", "name": "SLA"},
            ]
        },
        "raw_materials": [
            {
                "id": "src_alpha_pricing",
                "competitor": "Alpha",
                "schema_field_id": "Core.Pricing",
                "schema_field_name": "Pricing",
                "quote_text": "Alpha pricing starts at a public monthly plan.",
                "validation_status": "accepted",
            },
            {
                "id": "src_beta_sla",
                "competitor": "Beta",
                "schema_field_id": "Core.SLA",
                "schema_field_name": "SLA",
                "quote_text": "Beta publishes enterprise SLA details.",
                "validation_status": "accepted",
            },
        ],
    }

    analysis = build_deterministic_analysis(state)

    assert analysis["discovered_competitors"] == ["Alpha", "Beta"]
    assert analysis["schema_dimensions"] == [
        {
            "id": "Core.Pricing",
            "name": "Pricing",
            "group": "Core",
            "axis": "Core",
            "description": "Pricing",
            "source": "",
            "skill_category": "",
        },
        {
            "id": "Core.SLA",
            "name": "SLA",
            "group": "Core",
            "axis": "Core",
            "description": "SLA",
            "source": "",
            "skill_category": "",
        },
    ]
    assert [row["dimension_id"] for row in analysis["comparison_rows"]] == ["Core.Pricing", "Core.SLA"]
    pricing_row = analysis["comparison_rows"][0]
    assert pricing_row["values"]["Alpha"]["value"] == "Alpha pricing starts at a public monthly plan."
    assert pricing_row["values"]["Alpha"]["evidence_refs"] == ["src_alpha_pricing"]
    assert pricing_row["values"]["Beta"]["status"] == "degraded"
    assert pricing_row["values"]["Beta"]["value"] == "信息缺失"


def test_public_web_analysis_is_not_marked_as_survey_source():
    state = {
        "task_context": {"competitors": ["Alpha"]},
        "dynamic_schema": {"Core": [{"id": "Core.Pricing", "name": "Pricing"}]},
        "raw_materials": [
            {
                "id": "src_alpha_pricing",
                "competitor": "Alpha",
                "schema_field_id": "Core.Pricing",
                "quote_text": "Alpha publishes public pricing.",
                "source_type": "web_page",
                "validation_status": "accepted",
            }
        ],
    }

    analysis = build_deterministic_analysis(state)
    cell = analysis["comparison_rows"][0]["values"]["Alpha"]

    assert cell["source_type"] == "web_page"
    assert cell["survey_sources"] == []
