import pytest

from agents.analyzer import build_deterministic_analysis
from agents.critic import build_structured_feedback
from agents.orchestrator import build_schema_from_context, ensure_schema_metadata


def test_schema_edit_can_feed_collection_analysis_and_quality_flow():
    schema = ensure_schema_metadata(
        build_schema_from_context(
            {
                "domain": "AI assistants",
                "competitors": ["Alpha", "Beta"],
                "predefined_schema": [{"name": "Latency", "type": "number", "source": "official", "origin": "user"}],
            }
        )
    )

    assert "Core Profile" in schema
    assert any(field["origin"] == "user" for field in schema["Core Profile"])

    state = {
        "task_context": {"competitors": ["Alpha", "Beta"]},
        "raw_materials": [
            {"id": "src_1", "competitor": "Alpha", "quote_text": "Alpha pricing and features", "validation_status": "accepted"},
            {"id": "src_2", "competitor": "Beta", "quote_text": "Beta pricing and features", "validation_status": "accepted"},
        ],
    }
    analysis = build_deterministic_analysis(state)
    feedback = build_structured_feedback(analysis)

    assert {item["competitor"] for item in analysis["comparison"]} == {"Alpha", "Beta"}
    assert analysis["report"]["source_appendix"]
    assert feedback == []


def test_quality_feedback_flags_degraded_sources():
    analysis = {
        "comparison": [
            {"competitor": "Alpha", "status": "accepted", "evidence_refs": ["src_1"]},
            {"competitor": "Beta", "status": "degraded", "evidence_refs": ["src_2"]},
        ]
    }

    feedback = build_structured_feedback(analysis)

    assert feedback[0]["code"] == "degraded_source"
    assert feedback[0]["suggested_action"] == "manual_review"
