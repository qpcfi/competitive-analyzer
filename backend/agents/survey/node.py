import json
import os
import re
from typing import Any

import yaml

try:
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:
    ChatPromptTemplate = None

from ..state import AgentState
from ..shared.llm import create_chat_llm
from core.callbacks import RealtimeDebugCallbackHandler

llm = create_chat_llm(timeout=90)


async def survey_node(state: AgentState) -> dict[str, Any]:
    context = state.get("task_context", {})
    domain = str(context.get("domain") or "竞品分析").strip()
    main_product = str(context.get("main_product") or "").strip()
    competitors = [str(item) for item in context.get("competitors", []) if str(item).strip()]
    schema = state.get("dynamic_schema", {})

    if llm is not None and ChatPromptTemplate is not None:
        try:
            prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
            with open(prompt_path, "r", encoding="utf-8") as f:
                prompt_config = yaml.safe_load(f)["survey_agent"]
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", prompt_config["system_prompt"]),
                    ("human", prompt_config["human_template"]),
                ]
            )
            callbacks = [RealtimeDebugCallbackHandler(state.get("task_id"))] if state.get("task_id") else None
            response = await (prompt | llm).ainvoke(
                {
                    "domain": domain,
                    "main_product": main_product or "未指定",
                    "competitors": json.dumps(competitors, ensure_ascii=False),
                    "schema": json.dumps(schema, ensure_ascii=False),
                },
                config={"callbacks": callbacks} if callbacks else None,
            )
            return normalize_survey_output(parse_json_response(str(response.content)), domain, competitors, main_product)
        except Exception:
            pass

    return build_fallback_survey(domain, competitors, schema, main_product)


def parse_json_response(content: str) -> dict[str, Any]:
    cleaned = re.sub(r"```json\s*", "", content)
    cleaned = re.sub(r"```\s*", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    raw = match.group(0) if match else cleaned
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(re.sub(r",\s*([\]}])", r"\1", raw))


def normalize_survey_output(data: dict[str, Any], domain: str, competitors: list[str], main_product: str = "") -> dict[str, Any]:
    if not isinstance(data, dict):
        return build_fallback_survey(domain, competitors, {}, main_product)
    questionnaire = data.get("questionnaire") if isinstance(data.get("questionnaire"), dict) else {}
    questions = questionnaire.get("questions") if isinstance(questionnaire.get("questions"), list) else []
    normalized_questions = []
    for index, question in enumerate(questions[:12], start=1):
        if not isinstance(question, dict):
            continue
        q_type = question.get("type")
        if q_type not in {"single_choice", "multiple_choice", "likert", "ranking", "open_text"}:
            q_type = "open_text"
        item = {
            "id": question.get("id") or f"q{index}",
            "type": q_type,
            "title": question.get("title") or f"问题 {index}",
            "required": bool(question.get("required", index <= 6)),
        }
        if q_type in {"single_choice", "multiple_choice", "ranking"}:
            options = question.get("options") if isinstance(question.get("options"), list) else competitors + ["其他"]
            item["options"] = [str(option) for option in options if str(option).strip()][:12]
        if q_type == "likert":
            item["scale_min"] = int(question.get("scale_min") or 1)
            item["scale_max"] = int(question.get("scale_max") or 5)
        normalized_questions.append(item)

    if not normalized_questions:
        return build_fallback_survey(domain, competitors, {}, main_product)

    posts = data.get("recruitment_posts") if isinstance(data.get("recruitment_posts"), dict) else {}
    title = ensure_domain_text(str(questionnaire.get("title") or ""), domain, suffix="用户体验调研")
    description = ensure_domain_text(
        str(questionnaire.get("description") or "用于补充公开资料之外的真实用户反馈。"),
        domain,
        prefix="这份问卷聚焦",
    )
    return {
        "questionnaire": {
            "research_domain": domain,
            "main_product": main_product,
            "competitors": competitors,
            "title": title,
            "description": description,
            "questions": normalized_questions,
        },
        "recruitment_posts": normalize_posts(posts, domain),
    }


def normalize_posts(posts: dict[str, Any], domain: str) -> dict[str, dict[str, str]]:
    defaults = {
        "xiaohongshu": {
            "title": f"想请教大家关于{domain}的真实体验",
            "content": f"正在做一个{domain}相关调研，想听听真实使用体验。问卷大约 3 分钟，感谢参与：{{survey_url}}",
        },
    }
    for channel, default in defaults.items():
        value = posts.get(channel) if isinstance(posts.get(channel), dict) else {}
        defaults[channel] = {
            "title": ensure_domain_text(str(value.get("title") or default["title"]), domain),
            "content": ensure_domain_text(str(value.get("content") or default["content"]), domain, prefix="正在做一个"),
        }
    return defaults


def build_fallback_survey(domain: str, competitors: list[str], schema: dict[str, Any], main_product: str = "") -> dict[str, Any]:
    options = competitors or ["竞品 A", "竞品 B", "其他"]
    questions = [
        {"id": "q1", "type": "single_choice", "title": "你目前主要使用或了解哪一个产品？", "required": True, "options": options},
        {"id": "q2", "type": "multiple_choice", "title": "你选择该产品的主要原因是什么？", "required": True, "options": ["功能完整", "价格合适", "上手简单", "品牌可信", "团队推荐", "其他"]},
        {"id": "q3", "type": "likert", "title": "你对当前产品整体满意度如何？", "required": True, "scale_min": 1, "scale_max": 5},
        {"id": "q4", "type": "multiple_choice", "title": "你遇到过哪些明显痛点？", "required": True, "options": ["价格偏高", "功能不稳定", "学习成本高", "集成困难", "客服响应慢", "暂未遇到"]},
        {"id": "q5", "type": "ranking", "title": "请按重要性排序你选择产品时关注的因素。", "required": False, "options": ["价格", "核心功能", "易用性", "性能", "安全合规", "生态集成"]},
        {"id": "q6", "type": "open_text", "title": "如果只能改进一点，你最希望这类产品改进什么？", "required": False},
    ]
    schema_fields = []
    for fields in schema.values() if isinstance(schema, dict) else []:
        if isinstance(fields, list):
            schema_fields.extend(str(field.get("name")) for field in fields if isinstance(field, dict) and field.get("name"))
    if schema_fields:
        questions.append(
            {
                "id": "q7",
                "type": "multiple_choice",
                "title": "以下哪些维度最影响你的购买或使用决策？",
                "required": False,
                "options": schema_fields[:10],
            }
        )
    return {
        "questionnaire": {
            "research_domain": domain,
            "main_product": main_product,
            "competitors": competitors,
            "title": f"{domain} 用户体验调研",
            "description": f"这份问卷聚焦{domain}，用于补充公开资料之外的真实用户反馈，预计 3 分钟完成。",
            "questions": questions,
        },
        "recruitment_posts": normalize_posts({}, domain),
    }


def ensure_domain_text(text: str, domain: str, *, prefix: str = "", suffix: str = "") -> str:
    normalized = text.strip()
    if domain and domain not in normalized:
        if prefix:
            return f"{prefix}{domain}：{normalized}"
        if suffix:
            return f"{domain} {suffix}"
        return f"{domain}｜{normalized}" if normalized else domain
    return normalized or (f"{domain} {suffix}".strip() if suffix else domain)
