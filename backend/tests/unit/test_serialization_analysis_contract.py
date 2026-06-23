from types import SimpleNamespace

from services.serialization import serialize_task


def test_serialize_task_merges_critic_feedback_into_analysis_results_for_frontend():
    task = SimpleNamespace(
        id="task_123",
        task_name="Demo",
        domain="AI models",
        main_product=None,
        competitors=["Alpha"],
        execution_mode="auto",
        analysis_goal="",
        task_intent={},
        state="COMPLETED",
        progress=100,
        active_run_id=None,
        current_collection_run_id=None,
        current_material_ids=None,
        dynamic_schema={},
        raw_materials=[],
        analysis_results={"swot": {"strengths": [{"text": "Fast"}]}},
        critic_feedback=[
            {
                "level": "L2",
                "message": "Alpha needs stronger evidence.",
                "suggested_action": "retry_collection",
            }
        ],
        updated_at=None,
    )

    payload = serialize_task(task)

    assert payload["analysis_results"]["critic_feedback"] == task.critic_feedback
