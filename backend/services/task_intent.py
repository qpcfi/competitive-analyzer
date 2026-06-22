"""Task intent parsing for competitive-analysis workflows.

Task intent is intentionally small: it captures the target object, primary
analysis axes, and conclusions that should be derived later. It does not create
schema fields, discover competitors, or perform analysis.
"""

import json
import re

try:
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:
    ChatPromptTemplate = None

from agents.shared.llm import create_chat_llm

_INTENT_LLM = create_chat_llm(timeout=30)

DEFAULT_AXIS_INTENT = "围绕用户分析目标进行事实采集和对比分析"

SYSTEM_PROMPT = """\
You are a task-intent analyzer for a competitive-analysis workflow.

Your job is to interpret the user's main domain and analysis goal before
competitor discovery and schema generation.

FIELD RESPONSIBILITIES:
- The main domain defines the target object and competitive landscape.
- The analysis goal defines the primary analysis axes and conclusions expected later.
- Do NOT generate schema fields.
- Do NOT generate competitor names.
- Do NOT perform final analysis.
- Only extract stable task intent that downstream agents can reuse.

STEP 1: Identify target_object
Determine what kind of entity should be analyzed based on the main domain.
The target_object should describe the analyzed object type, not the research perspective.

Good:
- "工程机械与重型设备制造企业或设备品牌"
- "新能源汽车品牌"
- "企业级 CRM SaaS 产品"
- "跨境电商物流服务商"

Bad:
- "独立站模式"
- "营销策略"
- "履约方式"
- "SEO 优化"

STEP 2: Identify primary_axes
Extract explicit focus terms, comparison axes, classification criteria, or
decision dimensions from analysis_goal.

If the analysis goal says "按 A、B、C 区分/比较/归纳", then A, B, and C should
normally become primary_axes.

Each primary axis must include:
- name: concise axis name
- source_phrase: original phrase from analysis_goal
- intent: what question this axis should help answer

STEP 3: Identify deferred_outputs
Identify conclusions that should NOT be collected as raw facts, but should be
derived later from factual fields.

Examples:
- 模式分类
- 策略建议
- 优劣判断
- 规划启示
- 组合关系总结
- 趋势判断

IMPORTANT RULES:
- Keep the result compact.
- Do not invent analysis axes that are not implied by analysis_goal.
- Do not replace explicit focus terms with broad adjacent topics.
- Do not over-expand generic company, marketing, UX, compliance, or product topics unless they are clearly part of analysis_goal.
- Write all textual output in Chinese, except domain-specific terminology.

Return ONLY valid JSON with this exact structure:
{{
  "target_object": "string",
  "primary_axes": [
    {{
      "name": "string",
      "source_phrase": "string",
      "intent": "string"
    }}
  ],
  "deferred_outputs": ["string"]
}}
"""

HUMAN_TEMPLATE = (
    "Main domain:\n{domain}\n\nAnalysis goal:\n{analysis_goal}\n\n"
    "Extract the stable task intent."
)

_TARGET_NOISE_TERMS = (
    "独立站",
    "官网",
    "网站",
    "模式",
    "策略",
    "方案",
    "规划",
    "参考",
    "分析",
    "研究",
    "调研",
    "出海",
)

_AXIS_PREFIXES = (
    "重点按",
    "主要按",
    "按照",
    "按",
    "围绕",
    "从",
)

_AXIS_STOP_PHRASES = (
    "进行分类",
    "分类",
    "进行比较",
    "比较",
    "进行归纳",
    "归纳",
    "判断",
    "为",
    "用于",
    "以便",
)


async def build_task_intent(domain: str, analysis_goal: str) -> dict:
    """Parse domain + analysis_goal into a stable task_intent dict."""
    if not analysis_goal or not domain:
        return fallback_task_intent(domain, analysis_goal, source="fallback_missing_input")

    if _INTENT_LLM is None or ChatPromptTemplate is None:
        return fallback_task_intent(domain, analysis_goal, source="fallback_no_runtime")

    # Capture LLM input messages
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", HUMAN_TEMPLATE),
    ])
    input_messages = prompt_template.format_messages(
        domain=domain,
        analysis_goal=analysis_goal,
    )
    llm_input = [{"role": m.type, "content": m.content} for m in input_messages]

    try:
        chain = prompt_template | _INTENT_LLM
        res = await chain.ainvoke({
            "domain": domain,
            "analysis_goal": analysis_goal,
        })
    except Exception as exc:
        return fallback_task_intent(
            domain, analysis_goal,
            source="fallback_error",
            error_stage="invoke",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
            llm_input=llm_input,
        )

    raw_content = str(getattr(res, "content", res))
    try:
        parsed = json.loads(_extract_json_object(raw_content))
    except Exception as exc:
        return fallback_task_intent(
            domain, analysis_goal,
            source="fallback_error",
            error_stage="parse",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
            content_preview=raw_content,
            llm_input=llm_input,
        )

    return normalize_task_intent(
        parsed, domain, analysis_goal,
        source="llm",
        llm_input=llm_input,
        llm_raw_output=raw_content,
    )


def fallback_task_intent(
    domain: str,
    analysis_goal: str,
    *,
    source: str = "fallback_rule",
    error_stage: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    content_preview: str | None = None,
    llm_input: list[dict] | None = None,
) -> dict:
    """Return a safe fallback with light, generic parsing of common goal wording."""
    clean_domain = domain.strip()
    clean_goal = analysis_goal.strip()
    axis_source = clean_goal or clean_domain
    axes = _extract_axes(clean_goal)
    if not axes and axis_source:
        axes = [axis_source[:40]]

    meta = {"source": source}
    if error_stage:
        meta["error_stage"] = error_stage
    if error_type:
        meta["error_type"] = error_type
    if error_message:
        meta["error_message"] = _compact_text(error_message, 220)
    if content_preview:
        meta["content_preview"] = _compact_text(content_preview, 220)
    if llm_input is not None:
        meta["llm_input"] = llm_input

    return {
        "target_object": _clean_target_object(clean_domain),
        "primary_axes": [
            {
                "name": axis[:40],
                "source_phrase": axis,
                "intent": DEFAULT_AXIS_INTENT,
            }
            for axis in axes
            if axis
        ],
        "deferred_outputs": _infer_deferred_outputs(clean_goal),
        "_meta": meta,
    }


def normalize_task_intent(
    value: object,
    domain: str,
    analysis_goal: str,
    *,
    source: str = "llm",
    llm_input: list[dict] | None = None,
    llm_raw_output: str | None = None,
) -> dict:
    """Normalize LLM output to the stable task_intent shape."""
    if not isinstance(value, dict):
        return fallback_task_intent(domain, analysis_goal, source="fallback_bad_shape")

    target = _clean_target_object(str(value.get("target_object") or domain or "").strip())
    axes_raw = value.get("primary_axes", [])
    deferred = value.get("deferred_outputs", [])

    axes = []
    for item in axes_raw if isinstance(axes_raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:40]
        if not name:
            continue
        axes.append({
            "name": name,
            "source_phrase": str(item.get("source_phrase") or name).strip(),
            "intent": str(item.get("intent") or DEFAULT_AXIS_INTENT).strip(),
        })

    if not axes and (analysis_goal.strip() or domain.strip()):
        return fallback_task_intent(domain, analysis_goal, source="fallback_empty_axes")

    meta = {"source": source}
    if llm_input is not None:
        meta["llm_input"] = llm_input
    if llm_raw_output is not None:
        meta["llm_raw_output"] = llm_raw_output

    return {
        "target_object": target,
        "primary_axes": axes,
        "deferred_outputs": [
            str(item).strip()
            for item in (deferred if isinstance(deferred, list) else [])
            if str(item).strip()
        ],
        "_meta": meta,
    }


def _clean_target_object(domain: str) -> str:
    target = domain.strip()
    for term in _TARGET_NOISE_TERMS:
        target = target.replace(term, "")
    target = re.sub(r"\s+", " ", target).strip(" ，。-")
    return target or domain.strip()


def _extract_axes(analysis_goal: str) -> list[str]:
    if not analysis_goal:
        return []

    segment = ""
    for prefix in _AXIS_PREFIXES:
        index = analysis_goal.find(prefix)
        if index >= 0:
            segment = analysis_goal[index + len(prefix):]
            break
    if not segment:
        return []

    stop_positions = [
        pos for phrase in _AXIS_STOP_PHRASES
        if (pos := segment.find(phrase)) >= 0
    ]
    comma_positions = [
        pos for marker in ("，判断", "，为", "。", "，", ";")
        if (pos := segment.find(marker)) >= 0
    ]
    all_positions = stop_positions + comma_positions
    if all_positions:
        segment = segment[:min(all_positions)]

    parts = re.split(r"[、，,；;]|(?:\s+和\s+)|(?:\s+与\s+)|(?:\s+及\s+)", segment)
    axes = []
    seen = set()
    for part in parts:
        axis = part.strip(" ，。；;、")
        if not axis or len(axis) > 40:
            continue
        if axis in seen:
            continue
        seen.add(axis)
        axes.append(axis)
    return axes[:8]


def _infer_deferred_outputs(analysis_goal: str) -> list[str]:
    outputs = []
    if any(term in analysis_goal for term in ("模式", "分类", "归纳")):
        outputs.append("模式分类")
    if any(term in analysis_goal for term in ("作用", "判断")):
        outputs.append("作用判断")
    if any(term in analysis_goal for term in ("规划", "启示", "参考", "建议")):
        outputs.append("规划参考")
    if any(term in analysis_goal for term in ("组合", "关系")):
        outputs.append("组合关系总结")
    return list(dict.fromkeys(outputs))


def _extract_json_object(content: str) -> str:
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        return content[start: end + 1]
    return content


def _compact_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."
