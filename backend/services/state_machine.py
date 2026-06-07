from enum import StrEnum


class TaskState(StrEnum):
    INITIALIZING = "INITIALIZING"
    SCHEMA_GENERATING = "SCHEMA_GENERATING"
    SCHEMA_REVIEW = "SCHEMA_REVIEW"
    COLLECTING = "COLLECTING"
    ANALYZING = "ANALYZING"
    QUALITY_REVIEW = "QUALITY_REVIEW"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
    PAUSED = "PAUSED"
    NEEDS_INTERVENTION = "NEEDS_INTERVENTION"
    CRITIQUING = "CRITIQUING"
    SCHEMA_CALIBRATING = "SCHEMA_CALIBRATING"


ALLOWED_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.INITIALIZING: {
        TaskState.SCHEMA_GENERATING, TaskState.SCHEMA_REVIEW, TaskState.ERROR,
    },
    TaskState.SCHEMA_GENERATING: {
        TaskState.SCHEMA_REVIEW, TaskState.ERROR,
    },
    TaskState.SCHEMA_REVIEW: {
        TaskState.SCHEMA_GENERATING, TaskState.COLLECTING, TaskState.PAUSED, TaskState.ERROR,
    },
    TaskState.COLLECTING: {
        TaskState.ANALYZING, TaskState.NEEDS_INTERVENTION, TaskState.PAUSED, TaskState.ERROR,
    },
    TaskState.ANALYZING: {
        TaskState.QUALITY_REVIEW, TaskState.NEEDS_INTERVENTION, TaskState.PAUSED, TaskState.ERROR,
        TaskState.CRITIQUING, TaskState.SCHEMA_CALIBRATING, TaskState.COMPLETED,
    },
    TaskState.QUALITY_REVIEW: {
        TaskState.ANALYZING, TaskState.COLLECTING, TaskState.NEEDS_INTERVENTION, TaskState.COMPLETED, TaskState.ERROR,
    },
    TaskState.CRITIQUING: {
        TaskState.COMPLETED, TaskState.NEEDS_INTERVENTION, TaskState.PAUSED, TaskState.ERROR,
        TaskState.ANALYZING, TaskState.COLLECTING,
    },
    TaskState.SCHEMA_CALIBRATING: {
        TaskState.ANALYZING, TaskState.NEEDS_INTERVENTION, TaskState.ERROR,
    },
    TaskState.PAUSED: {
        TaskState.SCHEMA_REVIEW, TaskState.COLLECTING, TaskState.ANALYZING, TaskState.QUALITY_REVIEW, TaskState.ERROR,
    },
    TaskState.NEEDS_INTERVENTION: {
        TaskState.COLLECTING, TaskState.ANALYZING, TaskState.PAUSED, TaskState.ERROR,
    },
    TaskState.COMPLETED: {
        TaskState.ANALYZING,
    },
    TaskState.ERROR: {
        TaskState.SCHEMA_REVIEW, TaskState.COLLECTING, TaskState.ANALYZING,
    },
}


def can_transition(current: str | TaskState, target: str | TaskState) -> bool:
    current_state = TaskState(current)
    target_state = TaskState(target)
    return target_state in ALLOWED_TRANSITIONS[current_state]


def assert_transition(current: str | TaskState, target: str | TaskState) -> None:
    if not can_transition(current, target):
        raise ValueError(f"Invalid task state transition: {current} -> {target}")


def retry_exhausted(retry_count: int, max_retries: int = 3) -> bool:
    return retry_count >= max_retries
