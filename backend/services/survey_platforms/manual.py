from typing import Any

from .base import SurveyPlatformResult


class ManualSurveyPlatform:
    platform = "manual"

    async def create_survey(self, questionnaire: dict[str, Any]) -> SurveyPlatformResult:
        return SurveyPlatformResult(
            platform=self.platform,
            external_survey_id=None,
            survey_url=None,
            status="manual_required",
            raw_response={"questionnaire": questionnaire, "message": "Copy this questionnaire into your survey platform, then paste the URL back."},
        )

    async def sync_responses(self, external_survey_id: str) -> list[dict[str, Any]]:
        return []
