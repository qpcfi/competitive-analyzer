import json
from collections import Counter, defaultdict
from typing import Any

from services.privacy import contains_pii, redact_pii
from services.repositories import new_id


def synthesize_survey_materials(
    *,
    task_id: str,
    campaign_id: str,
    questionnaire: dict[str, Any],
    responses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    questions = questionnaire.get("questions") if isinstance(questionnaire.get("questions"), list) else []
    question_map = {str(q.get("id")): q for q in questions if isinstance(q, dict) and q.get("id")}
    normalized = [normalize_response(item, index) for index, item in enumerate(responses, start=1)]
    sample_size = len(normalized)
    if sample_size == 0:
        return []

    materials: list[dict[str, Any]] = []
    for question_id, question in question_map.items():
        answer_items = [
            {"answer": answer, "source": item["source"]}
            for item in normalized
            for answer in extract_answers(item["answers"], question_id)
        ]
        answers = [item["answer"] for item in answer_items]
        survey_sources = unique_survey_sources([item["source"] for item in answer_items])
        if not answers:
            continue
        q_type = question.get("type")
        title = str(question.get("title") or question_id)
        if q_type in {"single_choice", "multiple_choice", "ranking", "likert"}:
            counter = Counter(str(answer) for answer in answers if str(answer).strip())
            top = counter.most_common(5)
            quote = f"{sample_size} 份问卷中，问题「{title}」的高频回答为：" + "；".join(
                f"{value}({count}次)" for value, count in top
            )
            extracted = {
                "value": "；".join(f"{value}: {count}" for value, count in top),
                "sample_size": sample_size,
                "distribution": dict(counter),
                "confidence": confidence(sample_size, top[0][1] if top else 0),
                "survey_sources": survey_sources,
            }
        else:
            snippets = [str(answer).strip() for answer in answers if str(answer).strip()][:8]
            quote = f"{sample_size} 份问卷中，问题「{title}」的开放回答摘录：" + " / ".join(snippets)
            extracted = {
                "value": summarize_open_answers(snippets),
                "sample_size": sample_size,
                "supporting_quotes": snippets,
                "confidence": min(0.85, 0.35 + sample_size / 100),
                "survey_sources": survey_sources,
            }

        pii_redacted = contains_pii(quote) or contains_pii(json.dumps(extracted, ensure_ascii=False))
        redacted_quote = redact_pii(quote)
        redacted_extracted = json.loads(redact_pii(json.dumps(extracted, ensure_ascii=False)))
        materials.append(
            {
                "id": new_id("survey_src"),
                "competitor": infer_competitor(question, answers),
                "schema_field_id": question.get("schema_field_id") or f"Survey.{question_id}",
                "schema_field_name": title,
                "source_url": f"survey://{campaign_id}/{question_id}",
                "source_type": "survey_response",
                "quote_text": redacted_quote,
                "extracted_value": {
                    **redacted_extracted,
                    "campaign_id": campaign_id,
                    "question_id": question_id,
                    "question_title": title,
                },
                "agent_node": "survey",
                "access_status": "allowed",
                "validation_status": "accepted",
                "trust_status": "first_party",
                "retry_count": 0,
                "degraded_reason": None,
                "pii_redacted": pii_redacted,
            }
        )
    return materials


def normalize_response(response: dict[str, Any], index: int) -> dict[str, Any]:
    data = response.get("response_json") if isinstance(response.get("response_json"), dict) else response
    if isinstance(data.get("answers"), dict):
        answers = data["answers"]
    elif isinstance(data.get("answers"), list):
        answers = {str(item.get("question_id") or item.get("id")): item.get("value") for item in data["answers"] if isinstance(item, dict)}
    else:
        answers = data if isinstance(data, dict) else {}
    response_id = response.get("response_id") or response.get("id") or f"response_{index}"
    external_response_id = response.get("external_response_id")
    source = response.get("source") or "survey"
    return {
        "answers": answers,
        "source": {
            "label": build_survey_source_label(index, source, response_id, external_response_id),
            "response_id": response_id,
            "external_response_id": external_response_id,
            "source": source,
            "created_at": response.get("created_at"),
        },
    }


def build_survey_source_label(index: int, source: str, response_id: Any, external_response_id: Any) -> str:
    platform = str(source or "survey")
    if external_response_id:
        return f"答卷 {index} · {platform} · {external_response_id}"
    return f"答卷 {index} · {platform} · {response_id}"


def unique_survey_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    unique = []
    for source in sources:
        key = source.get("external_response_id") or source.get("response_id") or source.get("label")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return unique


def extract_answers(response: dict[str, Any], question_id: str) -> list[Any]:
    value = response.get(question_id)
    if value is None:
        value = response.get(f"{question_id}_answer")
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def summarize_open_answers(snippets: list[str]) -> str:
    if not snippets:
        return "未收集到可用开放回答"
    return "；".join(snippet[:120] for snippet in snippets[:5])


def confidence(sample_size: int, supporting_count: int) -> float:
    sample_factor = min(0.35, sample_size / 100)
    support_factor = min(0.45, (supporting_count / sample_size) * 0.45 if sample_size else 0)
    return round(0.2 + sample_factor + support_factor, 2)


def infer_competitor(question: dict[str, Any], answers: list[Any]) -> str:
    if question.get("competitor"):
        return str(question["competitor"])
    counter = Counter(str(answer) for answer in answers if str(answer).strip())
    return counter.most_common(1)[0][0] if counter and question.get("type") == "single_choice" else ""
