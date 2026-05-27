from agents.critic import build_structured_feedback


def test_critic_suggests_schema_extension_from_repeated_unmapped_evidence():
    feedback = build_structured_feedback(
        {
            "comparison": [
                {"competitor": "AlphaAI", "status": "accepted"},
                {"competitor": "BetaAI", "status": "accepted"},
            ],
            "unmapped_evidence": [
                {
                    "field_name": "Open Source License",
                    "dimension_group": "Function Tree",
                    "competitor": "AlphaAI",
                    "evidence_ref": "src_alpha",
                    "quote_text": "AlphaAI publishes an open source license.",
                    "confidence": 0.91,
                },
                {
                    "field_name": "Open Source License",
                    "dimension_group": "Function Tree",
                    "competitor": "BetaAI",
                    "evidence_ref": "src_beta",
                    "quote_text": "BetaAI documents Apache 2.0 support.",
                    "confidence": 0.87,
                },
            ],
        }
    )

    extensions = [item for item in feedback if item.get("code") == "suggested_schema_extension"]

    assert extensions == [
        {
            "level": "L2",
            "target_type": "dynamic_schema",
            "target_id": "Function Tree.Open Source License",
            "module_id": "schema_extension",
            "severity": "info",
            "code": "suggested_schema_extension",
            "message": "Consider adding Open Source License to Function Tree based on evidence from 2 competitors.",
            "suggested_action": "extend_schema",
            "retry_count": 0,
            "dimension_group": "Function Tree",
            "new_field": "Open Source License",
            "evidence": [
                "AlphaAI publishes an open source license.",
                "BetaAI documents Apache 2.0 support.",
            ],
            "evidence_refs": ["src_alpha", "src_beta"],
            "affected_competitors": ["AlphaAI", "BetaAI"],
            "confidence": 0.89,
        }
    ]
