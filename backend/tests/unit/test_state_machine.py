import pytest

from services.state_machine import TaskState, assert_transition, can_transition, retry_exhausted


def test_schema_review_can_resume_to_collecting():
    assert can_transition(TaskState.SCHEMA_REVIEW, TaskState.COLLECTING)


def test_completed_cannot_resume_to_collecting():
    assert not can_transition(TaskState.COMPLETED, TaskState.COLLECTING)
    with pytest.raises(ValueError):
        assert_transition(TaskState.COMPLETED, TaskState.COLLECTING)


def test_retry_exhaustion_boundary():
    assert not retry_exhausted(2, max_retries=3)
    assert retry_exhausted(3, max_retries=3)
