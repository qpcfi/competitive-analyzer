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
    req = PartialRerunRequest(target_module="swot.threats", new_instruction="focus on pricing")

    assert req.target_module == "swot.threats"
    assert req.rerun_scope == "current_only"
