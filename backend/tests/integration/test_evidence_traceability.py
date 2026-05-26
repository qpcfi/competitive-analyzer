from agents.analyzer import build_deterministic_analysis


def test_every_comparison_claim_has_evidence_or_degraded_status():
    state = {
        "task_context": {"competitors": ["Alpha", "Beta"]},
        "raw_materials": [
            {"id": "src_1", "competitor": "Alpha", "quote_text": "Alpha feature evidence", "validation_status": "accepted"},
            {"id": "src_2", "competitor": "Beta", "quote_text": "", "validation_status": "degraded"},
        ],
    }

    analysis = build_deterministic_analysis(state)

    for claim in analysis["comparison"]:
        assert claim["evidence_refs"] or claim["status"] == "degraded"
