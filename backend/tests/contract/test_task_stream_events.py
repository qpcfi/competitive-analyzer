from services.events import format_sse


def test_format_sse_uses_named_event_and_json_payload():
    frame = format_sse("schema_ready", {"sequence": 2, "dynamic_schema": {"basic": []}})
    assert frame.startswith("event: schema_ready\n")
    assert '"sequence": 2' in frame
    assert frame.endswith("\n\n")
