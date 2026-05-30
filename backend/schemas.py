from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class TaskCreateRequest(BaseModel):
    task_name: str | None = None
    domain: str
    main_product: str | None = None
    competitors: list[str] = []
    execution_mode: Literal["step_by_step", "auto"] = "step_by_step"
    predefined_schema: list[dict[str, Any]] | None = None

    @field_validator("domain")
    @classmethod
    def domain_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("domain is required")
        return value

    @field_validator("competitors")
    @classmethod
    def normalize_competitors(cls, value: list[str]) -> list[str]:
        normalized = []
        seen = set()
        for item in value or []:
            name = item.strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                normalized.append(name)
        return normalized


class TaskCreateResponse(BaseModel):
    task_id: str
    state: str
    stream_url: str


class SchemaUpdateRequest(BaseModel):
    dynamic_schema: dict[str, Any]


class PartialRerunRequest(BaseModel):
    target_module: str = "analysis"
    new_instruction: str = ""
    rerun_scope: Literal["current_only", "cascading"] = "current_only"
    override_system_prompt: str | None = None


class ForceNextRequest(BaseModel):
    reason: str = Field(default="User accepted current state")


class SourceMaterialCreateRequest(BaseModel):
    source_url: str
    competitor: str | None = None
    reason: str | None = None


class TrustUpdateRequest(BaseModel):
    trust_status: Literal["official", "third_party", "inferred", "untrusted", "degraded"]
    reason: str | None = None


class InterventionRequest(BaseModel):
    remove_source_ids: list[str] = []
    restore_noise_ids: list[str] = []
    add_urls: list[str] = []
    reason: str | None = None


class FeedbackRequest(BaseModel):
    target_type: str
    target_id: str
    feedback: str
    comment: str | None = None


class NoteRequest(BaseModel):
    target_type: str
    target_id: str
    note: str
