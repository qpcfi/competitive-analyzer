import os
from typing import Any

import httpx

from .base import SurveyPlatformResult


class TencentWenjuanSurveyPlatform:
    platform = "tencent_wenjuan"

    def __init__(self) -> None:
        self.base_url = os.environ.get("TENCENT_WJ_API_BASE_URL", "https://open.wj.qq.com").rstrip("/")
        self.app_id = os.environ.get("TENCENT_WJ_APP_ID", "")
        self.secret = os.environ.get("TENCENT_WJ_SECRET", "")
        self.org = os.environ.get("TENCENT_WJ_ORG", "")
        self.user_id = os.environ.get("TENCENT_WJ_USER_ID", "")
        self.token_path = os.environ.get("TENCENT_WJ_TOKEN_PATH", "/api/oauth2/access_token")
        self.create_path = os.environ.get("TENCENT_WJ_CREATE_SURVEY_PATH", "/api/surveys")
        self.responses_path = os.environ.get("TENCENT_WJ_RESPONSES_PATH", "/api/surveys/{survey_id}/answers")

    async def create_survey(self, questionnaire: dict[str, Any]) -> SurveyPlatformResult:
        if not self.app_id or not self.secret or not self.org or not self.user_id:
            return SurveyPlatformResult(
                platform=self.platform,
                external_survey_id=None,
                survey_url=None,
                status="configuration_required",
                raw_response={
                    "message": "Set TENCENT_WJ_APP_ID, TENCENT_WJ_SECRET, TENCENT_WJ_ORG, and TENCENT_WJ_USER_ID to enable Tencent Wenjuan OpenAPI survey creation.",
                    "questionnaire_text": build_questionnaire_text(questionnaire),
                },
            )

        questionnaire_text = build_questionnaire_text(questionnaire)
        try:
            token = await self._get_access_token()
            data = await self._create_survey(token, questionnaire, questionnaire_text)
        except httpx.RequestError as exc:
            return SurveyPlatformResult(
                platform=self.platform,
                external_survey_id=None,
                survey_url=None,
                status="failed",
                raw_response={"message": "Cannot connect to Tencent Wenjuan OpenAPI.", "error": str(exc), "questionnaire_text": questionnaire_text},
            )
        except httpx.HTTPStatusError as exc:
            return SurveyPlatformResult(
                platform=self.platform,
                external_survey_id=None,
                survey_url=None,
                status="failed",
                raw_response={
                    "message": f"Tencent Wenjuan OpenAPI returned HTTP {exc.response.status_code}.",
                    "request_url": str(exc.request.url),
                    "error": exc.response.text,
                    "questionnaire_text": questionnaire_text,
                },
            )

        if data.get("code") and data.get("code") != "OK":
            return SurveyPlatformResult(
                platform=self.platform,
                external_survey_id=None,
                survey_url=None,
                status="failed",
                raw_response={**data, "message": "Tencent Wenjuan OpenAPI returned an application error.", "questionnaire_text": questionnaire_text},
            )
        external_id = first_value(data, ("survey_id", "id", "sid", "questionnaire_id"))
        survey_hash = first_value(data, ("hash", "survey_hash"))
        survey_url = first_value(data, ("survey_url", "url", "link", "publish_url"))
        if not survey_url and external_id and survey_hash:
            survey_url = f"https://wj.qq.com/s2/{external_id}/{survey_hash}/"
        return SurveyPlatformResult(
            platform=self.platform,
            external_survey_id=str(external_id) if external_id else None,
            survey_url=str(survey_url) if survey_url else None,
            status="created" if survey_url or external_id else "created_without_url",
            raw_response={**data, "questionnaire_text": questionnaire_text},
        )

    async def sync_responses(self, external_survey_id: str) -> list[dict[str, Any]]:
        if not self.responses_path or not external_survey_id or not self.app_id or not self.secret:
            return []
        token = await self._get_access_token()
        url = self._url(self.responses_path.format(survey_id=external_survey_id))
        items: list[dict[str, Any]] = []
        last_answer_id = 0
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            while True:
                response = await client.get(
                    url,
                    params={
                        "appid": self.app_id,
                        "access_token": token,
                        "per_page": 100,
                        "last_answer_id": last_answer_id,
                    },
                )
                response.raise_for_status()
                data = normalize_response(response.json())
                if data.get("code") and data.get("code") != "OK":
                    raise httpx.HTTPStatusError(f"Tencent Wenjuan answers error: {data}", request=response.request, response=response)
                page_items = first_value(data, ("list", "responses", "items", "answers"))
                if not isinstance(page_items, list) or not page_items:
                    break
                items.extend(page_items)
                next_last_answer_id = max(int(item.get("answer_id") or item.get("id") or 0) for item in page_items if isinstance(item, dict))
                if next_last_answer_id <= last_answer_id or len(page_items) < 100:
                    break
                last_answer_id = next_last_answer_id
        return [normalize_tencent_answer(item) for item in items if isinstance(item, dict)]

    async def _get_access_token(self) -> str:
        url = self._url(self.token_path)
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(
                url,
                params={"appid": self.app_id, "secret": self.secret, "grant_type": "client_credential"},
            )
            response.raise_for_status()
            data = normalize_response(response.json())
        if data.get("code") and data.get("code") != "OK":
            raise httpx.HTTPStatusError(f"Tencent Wenjuan token error: {data}", request=response.request, response=response)
        token = first_value(data, ("access_token", "token"))
        if not token:
            raise httpx.HTTPStatusError("Tencent Wenjuan token response did not include access_token.", request=response.request, response=response)
        return str(token)

    async def _create_survey(self, token: str, questionnaire: dict[str, Any], questionnaire_text: str) -> dict[str, Any]:
        url = self._url(self.create_path)
        payload = {
            "org": int(self.org),
            "user_id": int(self.user_id),
            "text": questionnaire_text,
        }
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.post(
                url,
                params={"appid": self.app_id, "access_token": token},
                json=payload,
            )
            response.raise_for_status()
            return normalize_response(response.json())

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"


def build_questionnaire_text(questionnaire: dict[str, Any]) -> str:
    lines = [
        str(questionnaire.get("title") or "用户体验调研"),
        "",
        str(questionnaire.get("description") or ""),
        "",
    ]
    for index, question in enumerate(questionnaire.get("questions") or [], start=1):
        question_type = question.get("type") or "open_text"
        lines.append(f"{index}. {question.get('title') or ''}[{label_for_type(question_type)}]")
        options = question.get("options") or []
        for option in options:
            lines.append(str(option))
        if question_type == "likert":
            lines.append(f"{question.get('scale_min', 1)}~{question.get('scale_max', 5)}")
        lines.append("")
    return "\n".join(lines).strip()


def label_for_type(question_type: str) -> str:
    return {
        "single_choice": "单选题",
        "multiple_choice": "多选题",
        "open_text": "多行文本题",
        "likert": "量表题",
        "ranking": "排序题",
    }.get(question_type, question_type)


def normalize_response(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"response": data}
    nested = data.get("data")
    if isinstance(nested, dict):
        return {**data, **nested}
    return data


def normalize_tencent_answer(item: dict[str, Any]) -> dict[str, Any]:
    answers = item.get("answer")
    if not isinstance(answers, list):
        answers = item.get("answers") if isinstance(item.get("answers"), list) else []
    normalized: dict[str, Any] = {}
    raw_answers: list[dict[str, Any]] = []
    for index, answer in enumerate(answers, start=1):
        if not isinstance(answer, dict):
            continue
        value = extract_tencent_answer_value(answer)
        normalized[f"q{index}"] = value
        question_id = answer.get("question_id") or answer.get("id")
        if question_id:
            normalized[str(question_id)] = value
        raw_answers.append(answer)
    return {
        "external_response_id": str(item.get("answer_id") or item.get("id") or ""),
        "respondent_meta_json": {
            "submit_time": item.get("submit_time") or item.get("created_at"),
            "ip": item.get("ip"),
            "openid": item.get("openid"),
        },
        "response_json": normalized,
        "raw_response": item,
        "raw_answers": raw_answers,
    }


def extract_tencent_answer_value(answer: dict[str, Any]) -> Any:
    for key in ("value", "text", "content", "answer_text"):
        value = answer.get(key)
        if value not in (None, ""):
            return value
    options = answer.get("options")
    if isinstance(options, list):
        values = [extract_tencent_option_value(option) for option in options if isinstance(option, dict)]
        values = [value for value in values if value not in (None, "")]
        return values
    option = answer.get("option")
    if isinstance(option, dict):
        return extract_tencent_option_value(option)
    if isinstance(option, list):
        values = [extract_tencent_option_value(item) for item in option if isinstance(item, dict)]
        return [value for value in values if value not in (None, "")]
    return answer


def extract_tencent_option_value(option: dict[str, Any]) -> Any:
    for key in ("text", "content", "value", "name", "title"):
        value = option.get(key)
        if value not in (None, ""):
            return value
    return option


def first_value(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = data.get(key)
        if value:
            return value
    return None
