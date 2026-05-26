from pydantic import ValidationError

import main
from schemas import InterventionRequest, SourceMaterialCreateRequest, TrustUpdateRequest


def route_methods(path: str) -> set[str]:
    methods = set()
    for route in main.app.routes:
        if getattr(route, "path", None) == path:
            methods.update(route.methods or [])
    return methods


def test_source_intervention_routes_are_registered():
    expected = {
        "/api/v1/tasks/{task_id}/source-materials": {"GET", "POST"},
        "/api/v1/tasks/{task_id}/source-materials/{source_id}": {"GET"},
        "/api/v1/tasks/{task_id}/source-materials/{source_id}/refetch": {"POST"},
        "/api/v1/tasks/{task_id}/source-materials/{source_id}/trust": {"POST"},
        "/api/v1/tasks/{task_id}/interventions": {"POST"},
    }

    for path, methods in expected.items():
        assert methods.issubset(route_methods(path)), path


def test_source_and_intervention_payload_contracts():
    source = SourceMaterialCreateRequest(source_url="https://example.com/report", competitor="Alpha")
    trust = TrustUpdateRequest(trust_status="untrusted", reason="User review")
    intervention = InterventionRequest(remove_source_ids=["src_1"], restore_noise_ids=["src_2"], add_urls=["https://example.com"])

    assert source.source_url == "https://example.com/report"
    assert trust.trust_status == "untrusted"
    assert intervention.add_urls == ["https://example.com"]


def test_trust_payload_rejects_unknown_status():
    try:
        TrustUpdateRequest(trust_status="unknown")
    except ValidationError:
        return
    raise AssertionError("unknown trust status must be rejected")
