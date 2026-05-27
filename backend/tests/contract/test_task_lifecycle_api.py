import pytest
from pydantic import ValidationError

from schemas import TaskCreateRequest


def test_task_create_request_normalizes_competitors():
    req = TaskCreateRequest(domain=" AI ", competitors=["GPT-4o", "gpt-4o", "Claude"], execution_mode="step_by_step")
    assert req.domain == "AI"
    assert req.competitors == ["GPT-4o", "Claude"]


def test_task_create_request_allows_agent_discovered_competitors():
    req = TaskCreateRequest(domain="AI", competitors=[])
    assert req.competitors == []

    single_hint = TaskCreateRequest(domain="AI", competitors=["OnlyOne"])
    assert single_hint.competitors == ["OnlyOne"]


def test_task_create_request_rejects_empty_domain():
    with pytest.raises(ValidationError):
        TaskCreateRequest(domain=" ", competitors=["A", "B"])
