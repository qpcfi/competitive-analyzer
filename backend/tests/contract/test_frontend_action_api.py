import main


def route_methods(path: str) -> set[str]:
    methods = set()
    for route in main.app.routes:
        if getattr(route, "path", None) == path:
            methods.update(route.methods or [])
    return methods


def test_frontend_action_routes_are_registered():
    expected = {
        "/api/v1/tasks": "GET",
        "/api/v1/tasks/{task_id}/snapshots": "GET",
        "/api/v1/tasks/{task_id}/restore_snapshot": "POST",
        "/api/v1/tasks/{task_id}/schema/advice": "GET",
        "/api/v1/tasks/{task_id}/feedback": "POST",
        "/api/v1/tasks/{task_id}/notes": "POST",
        "/api/v1/tasks/{task_id}/report": "GET",
        "/api/v1/tasks/{task_id}/export": "GET",
        "/api/v1/tasks/{task_id}/share": "POST",
        "/api/v1/tasks/{task_id}/verify_links": "POST",
        "/api/v1/tasks/{task_id}/events": "GET",
    }

    for path, method in expected.items():
        assert method in route_methods(path), path


def test_schema_and_source_event_payload_stats_are_contract_shaped():
    schema = {"Core": [{"origin": "user"}, {"origin": "agent"}]}
    materials = [
        {"validation_status": "accepted", "access_status": "accessible"},
        {"validation_status": "degraded", "access_status": "blocked"},
    ]

    assert main.count_schema_stats(schema) == {"total_fields": 2, "user_defined": 1, "agent_supplement": 1}
    assert main.source_stats(materials) == {"accepted": 1, "degraded": 1, "failed": 0, "blocked": 1}
