import main
from schemas import PartialRerunRequest


def route_methods(path: str) -> set[str]:
    methods = set()
    for route in main.app.routes:
        if getattr(route, "path", None) == path:
            methods.update(route.methods or [])
    return methods


def test_recovery_and_rerun_routes_are_registered():
    assert "POST" in route_methods("/api/v1/tasks/{task_id}/force_next")
    assert "POST" in route_methods("/api/v1/tasks/{task_id}/partial_rerun")
    assert "POST" in route_methods("/api/v1/tasks/{task_id}/pause")


def test_partial_rerun_payload_contract_defaults():
    req = PartialRerunRequest(
        scope={"type": "cell", "module_id": "comparison", "dimension_id": "pricing", "competitor": "竞品A"},
        instruction="重新分析该竞品在价格维度的表现",
    )

    assert req.scope == {"type": "cell", "module_id": "comparison", "dimension_id": "pricing", "competitor": "竞品A"}
    assert req.instruction == "重新分析该竞品在价格维度的表现"


def test_partial_rerun_backwards_compat():
    """Old target_module/new_instruction fields should still be accepted."""
    req = PartialRerunRequest(target_module="swot.threats", new_instruction="focus on pricing")

    assert req.target_module == "swot.threats"
    assert req.new_instruction == "focus on pricing"
    # New fields default
    assert req.scope == {}
    assert req.instruction == ""
