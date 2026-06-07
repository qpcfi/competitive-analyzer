import os
from typing import Any

import httpx

from .base import SurveyPlatformResult


class WenjuanxingSurveyPlatform:
    platform = "wenjuanxing"

    def __init__(self) -> None:
        self.base_url = os.environ.get("WJX_API_BASE_URL", "").rstrip("/")
        self.api_key = os.environ.get("WJX_API_KEY", "")
        self.create_path = os.environ.get("WJX_CREATE_SURVEY_PATH", "/surveys")
        self.responses_path = os.environ.get("WJX_RESPONSES_PATH", "/surveys/{survey_id}/responses")

    async def create_survey(self, questionnaire: dict[str, Any]) -> SurveyPlatformResult:
        if not self.base_url or not self.api_key:
            return SurveyPlatformResult(
                platform=self.platform,
                external_survey_id=None,
                survey_url=None,
                status="configuration_required",
                raw_response={
                    "message": "Set WJX_API_BASE_URL and WJX_API_KEY to enable Wenjuanxing creation.",
                    "questionnaire": questionnaire,
                },
            )

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.post(
                f"{self.base_url}{self.create_path}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"questionnaire": questionnaire},
            )
            response.raise_for_status()
            data = response.json()

        external_id = str(data.get("survey_id") or data.get("id") or "")
        survey_url = data.get("survey_url") or data.get("url") or data.get("preview_url")
        return SurveyPlatformResult(
            platform=self.platform,
            external_survey_id=external_id or None,
            survey_url=survey_url,
            status="created" if survey_url or external_id else "created_without_url",
            raw_response=data if isinstance(data, dict) else {"response": data},
        )

    async def sync_responses(self, external_survey_id: str) -> list[dict[str, Any]]:
        if not self.base_url or not self.api_key or not external_survey_id:
            return []
        path = self.responses_path.format(survey_id=external_survey_id)
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            data = response.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("responses"), list):
            return data["responses"]
        return []
