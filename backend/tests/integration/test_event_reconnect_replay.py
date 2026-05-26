import json

from services.events import format_sse


def test_persisted_event_frame_carries_sequence_for_reconnect_replay():
    frame = format_sse("progress_update", {"sequence": 12, "progress": 60, "stage": "COLLECTING"})
    lines = frame.strip().splitlines()

    assert lines[0] == "event: progress_update"
    payload = json.loads(lines[1].removeprefix("data: "))
    assert payload["sequence"] == 12
    assert payload["stage"] == "COLLECTING"
