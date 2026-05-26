from agents.analyzer import build_deterministic_analysis
from agents.critic import build_structured_feedback


def test_degraded_collection_can_continue_with_traceable_status():
    state = {
        "task_context": {"competitors": ["Alpha"]},
        "raw_materials": [
            {
                "id": "src_degraded",
                "competitor": "Alpha",
                "quote_text": "",
                "validation_status": "degraded",
                "access_status": "blocked",
            }
        ],
    }

    analysis = build_deterministic_analysis(state)
    feedback = build_structured_feedback(analysis)

    assert analysis["comparison"][0]["status"] == "degraded"
    assert feedback[0]["suggested_action"] == "manual_review"
