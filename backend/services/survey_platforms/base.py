from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class SurveyPlatformResult:
    platform: str
    external_survey_id: str | None
    survey_url: str | None
    status: str
    raw_response: dict[str, Any]


class SurveyPlatformAdapter(Protocol):
    platform: str

    async def create_survey(self, questionnaire: dict[str, Any]) -> SurveyPlatformResult:
        ...

    async def sync_responses(self, external_survey_id: str) -> list[dict[str, Any]]:
        ...
