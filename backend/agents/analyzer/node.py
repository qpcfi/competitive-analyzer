import json
import os
import re
import yaml
import logging
try:
    from langchain_core.messages import HumanMessage
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:
    HumanMessage = None
    ChatPromptTemplate = None
from ..state import AgentState
from ..schemas import AnalysisResult
from ..shared.analysis_angles import ANALYSIS_ANGLES, VALID_ANGLE_KEYS
from ..shared.llm import create_chat_llm
from core.callbacks import RealtimeDebugCallbackHandler
from services.events import event_broker

llm = create_chat_llm(timeout=90)

async def analyzer_node(state: AgentState):
    schema = state.get("dynamic_schema", {})
    materials = state.get("raw_materials", [])
    if llm is None or ChatPromptTemplate is None:
        state["analysis_results"] = build_deterministic_analysis(state)
        return state

    prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            PROMPT_CONFIG = yaml.safe_load(f)
    except Exception:
        state["analysis_results"] = build_deterministic_analysis(state)
        return state

    # ── Pre-analysis: angle selection ──
    task_id = state.get("task_id")
    analysis_goal = (state.get("task_context") or {}).get("analysis_goal") or ""
    selected_angles = []
    if analysis_goal:
        try:
            angle_prompt = ChatPromptTemplate.from_messages([
                ("system", PROMPT_CONFIG["analyzer_agent"]["angle_selector"]["system_prompt"]),
                ("human", PROMPT_CONFIG["analyzer_agent"]["angle_selector"]["human_template"])
            ])
            angle_chain = angle_prompt | llm
            callbacks = [RealtimeDebugCallbackHandler(task_id)] if task_id else None
            angle_response = await angle_chain.ainvoke({
                "analysis_goal": analysis_goal,
                "angles": json.dumps(ANALYSIS_ANGLES, ensure_ascii=False),
            }, config={"callbacks": callbacks} if callbacks else None)
            raw = str(angle_response.content)
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            parsed = json.loads(match.group(0) if match else raw)
            for item in parsed.get("selected_angles", []):
                if isinstance(item, dict) and str(item.get("angle", "")).lower() in VALID_ANGLE_KEYS:
                    item["angle"] = str(item["angle"]).lower()
                    selected_angles.append(item)
        except Exception:
            logging.warning("Angle selection pre-call failed, using fallback")
    if not selected_angles:
        selected_angles = [{"angle": a["key"], "relevance": "medium", "rationale": "默认角度"} for a in ANALYSIS_ANGLES]

    # ── Main analysis ──
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", PROMPT_CONFIG["analyzer_agent"]["system_prompt"]),
        ("human", PROMPT_CONFIG["analyzer_agent"]["human_template"])
    ])

    chain = prompt_template | llm

    try:
        callbacks = [RealtimeDebugCallbackHandler(task_id)] if task_id else None
        config = {"callbacks": callbacks} if callbacks else None
        materials_input = json.dumps(materials, ensure_ascii=False)
        critic_feedback = state.get("critic_feedback", []) or []
        # ── Rerun scope context (injected before critic feedback) ──
        rerun_scope = (state.get("task_context") or {}).get("analysis_rerun_scope")
        rerun_instruction = (state.get("task_context") or {}).get("analysis_rerun_instruction")
        if rerun_scope:
            rerun_text = "\n\n=== 局部重跑 - 请专注于以下范围 ===\n"
            rerun_text += f"范围: {json.dumps(rerun_scope, ensure_ascii=False)}\n"
            if rerun_instruction:
                rerun_text += f"指令: {rerun_instruction}\n"
            rerun_text += (
                "注意: 你只需要输出符合主提示结构的 comparison_rows。"
                "顶部 goal_analysis 会在局部补丁合并到完整结果后单独生成。\n"
            )
            materials_input = rerun_text + "\n" + materials_input
        # ── Critic feedback ──
        if critic_feedback:
            feedback_text = "\n\n=== CRITIC质量审查-请修复以下问题 ===\n"
            for item in critic_feedback:
                if isinstance(item, dict):
                    target = item.get("target") or item.get("target_id", "")
                    issue = item.get("issue") or item.get("message", "")
                    feedback_text += f"- [{target}] {issue}\n"
                else:
                    feedback_text += f"- {item}\n"
            materials_input = feedback_text + "\n" + materials_input
        response = await chain.ainvoke({
            "analysis_goal": analysis_goal,
            "selected_angles_json": json.dumps(selected_angles, ensure_ascii=False),
            "schema": json.dumps(schema, ensure_ascii=False),
            "materials": materials_input
        }, config=config)
        
        content = str(response.content)
        import re
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        match = re.search(r"\{.*\}", content, re.DOTALL)
        clean_content = match.group(0) if match else content
        try:
            parsed = json.loads(clean_content)
        except json.JSONDecodeError:
            clean_content = re.sub(r',\s*([\]}])', r'\1', clean_content)
            parsed = json.loads(clean_content)
            
        result = build_deterministic_analysis(state)
        llm_cells = parsed.get("comparison_rows", [])
        if isinstance(llm_cells, list):
            for row in result.get("comparison_rows", []):
                for comp in result.get("discovered_competitors", []):
                    cell = next((c for c in llm_cells if isinstance(c, dict) and c.get("field_name") == row.get("dimension") and c.get("competitor") == comp), None)
                    if cell:
                        if cell.get("dimension_group") and "group" not in row:
                            row["group"] = cell["dimension_group"]
                        old_cell = row["values"].get(comp, {})
                        row["values"][comp] = {
                            "value": cell.get("value", ""),
                            "status": "accepted" if cell.get("value") else "degraded",
                            "evidence_refs": old_cell.get("evidence_refs", []),
                            "degraded_reason": cell.get("degraded_reason", "") or old_cell.get("degraded_reason", "")
                        }
        goal_analysis = parsed.get("goal_analysis")
        if isinstance(goal_analysis, dict) and goal_analysis.get("direct_answer"):
            result["goal_analysis"] = goal_analysis

        if "executive_summary" in parsed and isinstance(parsed.get("executive_summary"), str):
            if "report" not in result:
                result["report"] = {}
            result["report"]["summary"] = parsed["executive_summary"]
    except Exception as e:
        import logging
        logging.error(f"Error in analyzer_node: {e}")
        result = build_deterministic_analysis(state)

    if not isinstance(result, dict) or "comparison_rows" not in result:
        result = build_deterministic_analysis(state)

    result["selected_angles"] = selected_angles

    # Rerun paths refresh goal_analysis after scoped patches are merged into
    # the complete analysis, so the conclusion is based on the final state.
    is_scoped_rerun = bool((state.get("task_context") or {}).get("analysis_rerun_scope"))
    if not is_scoped_rerun:
        goal = await generate_goal_analysis(state, result, reason="initial_analysis")
        if goal:
            result["goal_analysis"] = goal

    state["analysis_results"] = result
    return state


async def generate_goal_analysis(
    state: AgentState,
    analysis_results: dict,
    *,
    reason: str = "analysis",
) -> dict | None:
    """Generate *goal_analysis* from the complete merged analysis results.

    This is a separate, focused LLM call that reads the full ``comparison_rows``
    (not just a scoped subset) and answers the user's *analysis_goal*.

    Parameters
    ----------
    state :
        The current agent state (used for *analysis_goal* and *task_id*).
    analysis_results :
        The **complete** merged analysis (must contain ``comparison_rows``,
        ``discovered_competitors``, ``schema_dimensions``, ``selected_angles``).
    reason :
        A label for logging (e.g. ``"initial_analysis"``, ``"incremental_rerun"``).

    Returns
    -------
    A dict with ``direct_answer`` and ``key_findings``, or ``None`` on failure.
    """
    task_id = state.get("task_id")

    async def publish_goal_log(event: str, message: str, output_json: dict | None = None):
        if not task_id:
            return
        payload = {"agent": "GoalAnalysis", "event": event, "message": message}
        if output_json is not None:
            payload["output_json"] = output_json
        await event_broker.publish(task_id, "debug_log", payload)

    if llm is None or ChatPromptTemplate is None:
        await publish_goal_log("skip", "Goal analysis skipped: LLM or prompt runtime is unavailable.")
        return None

    rows = analysis_results.get("comparison_rows") or []
    if not rows:
        await publish_goal_log("skip", "Goal analysis skipped: comparison_rows is empty.", {
            "analysis_keys": list(analysis_results.keys()) if isinstance(analysis_results, dict) else [],
        })
        return None

    prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            PROMPT_CONFIG = yaml.safe_load(f)
    except Exception as e:
        await publish_goal_log("error", f"Goal analysis skipped: failed to load prompt config: {e}")
        return None

    goal_config = PROMPT_CONFIG.get("goal_analysis_agent")
    if not goal_config:
        await publish_goal_log("skip", "Goal analysis skipped: goal_analysis_agent prompt is missing.")
        return None

    try:
        await publish_goal_log("start", "Generating goal-focused conclusion from complete analysis.", {
            "reason": reason,
            "row_count": len(rows),
            "competitor_count": len(analysis_results.get("discovered_competitors") or []),
        })
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", goal_config["system_prompt"]),
            ("human", goal_config["human_template"]),
        ])
        chain = prompt_template | llm

        task_id = state.get("task_id")
        callbacks = [RealtimeDebugCallbackHandler(task_id)] if task_id else None
        config = {"callbacks": callbacks} if callbacks else None

        response = await chain.ainvoke({
            "analysis_goal": (state.get("task_context") or {}).get("analysis_goal") or "",
            "selected_angles_json": json.dumps(
                analysis_results.get("selected_angles") or [], ensure_ascii=False,
            ),
            "competitors_json": json.dumps(
                analysis_results.get("discovered_competitors") or [], ensure_ascii=False,
            ),
            "schema_dimensions_json": json.dumps(
                analysis_results.get("schema_dimensions") or [], ensure_ascii=False,
            ),
            "comparison_rows_json": json.dumps(rows, ensure_ascii=False),
        }, config=config)

        content = str(response.content)
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        match = re.search(r"\{.*\}", content, re.DOTALL)
        parsed = json.loads(match.group(0) if match else content)

        if isinstance(parsed, dict) and parsed.get("direct_answer"):
            await publish_goal_log("end", "Goal analysis generated.", {
                "reason": reason,
                "has_key_findings": bool(parsed.get("key_findings")),
            })
            return {
                "direct_answer": parsed["direct_answer"],
                "key_findings": parsed.get("key_findings", []),
            }
        await publish_goal_log("error", "Goal analysis response did not include direct_answer.", {
            "parsed_keys": list(parsed.keys()) if isinstance(parsed, dict) else [],
        })
    except Exception as e:
        logging.warning("generate_goal_analysis (%s) failed: %s", reason, e)
        await publish_goal_log("error", f"Goal analysis failed: {e}")

    return None


def build_deterministic_analysis(state: AgentState) -> dict:
    materials = state.get("raw_materials", [])
    schema_dimensions = flatten_schema_dimensions(state.get("dynamic_schema", {}))
    if not schema_dimensions and materials:
        schema_dimensions = [{"id": "__collected_evidence", "name": "Collected Evidence", "group": "Evidence"}]
    competitors = discovered_competitors(state)
    comparison_rows = []
    for dimension in schema_dimensions:
        values = {}
        for competitor in competitors:
            evidence = [
                item
                for item in materials
                if item.get("competitor") == competitor
                and (dimension["id"] == "__collected_evidence" or item.get("schema_field_id") == dimension["id"])
            ]
            values[competitor] = build_cell(evidence)
        comparison_rows.append(
            {
                "key": dimension["id"],
                "dimension_id": dimension["id"],
                "dimension": dimension["name"],
                "values": values,
            }
        )
    evidence_refs = [item.get("id") for item in materials if item.get("id")]
    legacy_comparison = build_legacy_comparison(competitors, materials)
    findings = build_report_findings(competitors, materials)
    return {
        "discovered_competitors": competitors,
        "schema_dimensions": schema_dimensions,
        "comparison_rows": comparison_rows,
        "comparison": legacy_comparison,
        "report": {
            "summary": "Analysis generated from collected public source materials.",
            "findings": findings,
            "recommendations": ["Review degraded sources before publishing."],
            "source_appendix": materials,
        },
        "evidence_refs": evidence_refs,
    }


def flatten_schema_dimensions(schema: dict) -> list[dict]:
    dimensions = []
    for group_name, fields in schema.items():
        if not isinstance(fields, list):
            continue
        for index, field in enumerate(fields):
            if not isinstance(field, dict):
                continue
            field_id = field.get("id") or f"{group_name}.{field.get('name', index)}"
            dimensions.append({"id": field_id, "name": field.get("name") or field_id, "group": group_name})
    return dimensions


def discovered_competitors(state: AgentState) -> list[str]:
    configured = [str(item) for item in state.get("task_context", {}).get("competitors", []) if str(item).strip()]
    collected = [
        str(item.get("competitor"))
        for item in state.get("raw_materials", [])
        if item.get("competitor")
    ]
    ordered = []
    for name in configured + collected:
        if name not in ordered:
            ordered.append(name)
    return ordered


def build_cell(evidence: list[dict]) -> dict:
    accepted = next((item for item in evidence if item.get("validation_status") == "accepted" and item.get("quote_text")), None)
    if not accepted:
        degraded = next((item for item in evidence if item.get("validation_status") == "degraded"), None)
        return {
            "value": "信息缺失",
            "status": "degraded",
            "evidence_refs": [degraded.get("id")] if degraded and degraded.get("id") else [],
            "degraded_reason": degraded.get("degraded_reason") if degraded else "no_evidence_for_schema_field",
        }
    return {
        "value": accepted.get("quote_text", ""),
        "status": "accepted",
        "source_url": accepted.get("source_url", ""),
        "source_type": accepted.get("source_type", ""),
        "survey_sources": (accepted.get("extracted_value") or {}).get("survey_sources", []),
        "evidence_refs": [accepted.get("id")] if accepted.get("id") else [],
    }


def build_legacy_comparison(competitors: list[str], materials: list[dict]) -> list[dict]:
    comparison = []
    for competitor in competitors:
        evidence = [item for item in materials if item.get("competitor") == competitor]
        accepted = next((item for item in evidence if item.get("validation_status") == "accepted" and item.get("quote_text")), None)
        degraded = next((item for item in evidence if item.get("validation_status") == "degraded"), None)
        selected = accepted or degraded
        comparison.append(
            {
                "competitor": competitor,
                "summary": selected.get("quote_text", "")[:240] if selected else "",
                "status": "accepted" if accepted else "degraded",
                "evidence_refs": [item.get("id") for item in evidence if item.get("id")],
            }
        )
    return comparison


def build_report_findings(competitors: list[str], materials: list[dict]) -> list[dict]:
    findings = []
    for competitor in competitors:
        evidence = [item for item in materials if item.get("competitor") == competitor]
        accepted = next((item for item in evidence if item.get("validation_status") == "accepted" and item.get("quote_text")), None)
        degraded = next((item for item in evidence if item.get("validation_status") == "degraded"), None)
        selected = accepted or degraded
        if accepted:
            summary = accepted.get("quote_text", "")
            status = "accepted"
        elif degraded:
            summary = degraded.get("degraded_reason") or degraded.get("quote_text") or "degraded_source"
            status = "degraded"
        else:
            summary = "no_evidence"
            status = "degraded"
        findings.append(
            {
                "competitor": competitor,
                "summary": summary[:240] if isinstance(summary, str) else str(summary)[:240],
                "status": status,
                "evidence_refs": [item.get("id") for item in evidence if item.get("id")],
            }
        )
    return findings
