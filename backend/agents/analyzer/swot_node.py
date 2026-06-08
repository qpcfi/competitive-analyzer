import json
import os
import re
import yaml
try:
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:
    ChatPromptTemplate = None
from ..state import AgentState
from ..shared.llm import create_chat_llm
from core.callbacks import RealtimeDebugCallbackHandler

llm = create_chat_llm(timeout=90)


async def swot_generator_node(state: AgentState) -> AgentState:
    """SWOT-only generator. Produces SWOT from existing analysis data."""
    if llm is None or ChatPromptTemplate is None:
        return state

    prompt_path = os.path.join(os.path.dirname(__file__), "swot_prompts.yaml")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            PROMPT_CONFIG = yaml.safe_load(f)
    except Exception:
        return state

    prompt_template = ChatPromptTemplate.from_messages([
        ("system", PROMPT_CONFIG["swot_generator"]["system_prompt"]),
        ("human", PROMPT_CONFIG["swot_generator"]["human_template"])
    ])
    chain = prompt_template | llm

    try:
        task_context = state.get("task_context") or {}
        analysis_results = state.get("analysis_results") or {}
        schema = state.get("dynamic_schema", {})
        materials = state.get("raw_materials", [])
        target_competitor = analysis_results.get("swot", {}).get("competitor") or ""
        comparison_rows = analysis_results.get("comparison_rows") or []
        task_id = state.get("task_id")

        callbacks = [RealtimeDebugCallbackHandler(task_id)] if task_id else None
        config = {"callbacks": callbacks} if callbacks else None

        response = await chain.ainvoke({
            "analysis_goal": task_context.get("analysis_goal") or "",
            "selected_angles_json": json.dumps(analysis_results.get("selected_angles") or [], ensure_ascii=False),
            "schema": json.dumps(schema, ensure_ascii=False),
            "materials": json.dumps(materials, ensure_ascii=False),
            "comparison_rows": json.dumps(comparison_rows[:5] if isinstance(comparison_rows, list) else [], ensure_ascii=False),
            "target_competitor": target_competitor,
        }, config=config)

        content = str(response.content)
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        match = re.search(r"\{.*\}", content, re.DOTALL)
        clean_content = match.group(0) if match else content
        try:
            parsed = json.loads(clean_content)
        except json.JSONDecodeError:
            clean_content = re.sub(r',\s*([\]}])', r'\1', clean_content)
            parsed = json.loads(clean_content)

        llm_swot = parsed.get("swot_analysis", {})
        if isinstance(llm_swot, dict) and llm_swot:
            def parse_item(t):
                if isinstance(t, dict):
                    return {"text": t.get("text", ""), "evidence_refs": t.get("evidence_refs", [])}
                return {"text": str(t), "evidence_refs": []}
            swot = {
                "competitor": llm_swot.get("competitor", target_competitor),
                "strengths": [parse_item(t) for t in llm_swot.get("strengths", []) if t],
                "weaknesses": [parse_item(t) for t in llm_swot.get("weaknesses", []) if t],
                "opportunities": [parse_item(t) for t in llm_swot.get("opportunities", []) if t],
                "threats": [parse_item(t) for t in llm_swot.get("threats", []) if t],
                "so_strategies": [parse_item(t) for t in llm_swot.get("so_strategies", []) if t],
                "wo_strategies": [parse_item(t) for t in llm_swot.get("wo_strategies", []) if t],
                "st_strategies": [parse_item(t) for t in llm_swot.get("st_strategies", []) if t],
                "wt_strategies": [parse_item(t) for t in llm_swot.get("wt_strategies", []) if t],
            }
            if "analysis_results" not in state:
                state["analysis_results"] = {}
            state["analysis_results"]["swot"] = swot
    except Exception as e:
        import logging
        logging.error(f"Error in swot_generator_node: {e}")

    return state
