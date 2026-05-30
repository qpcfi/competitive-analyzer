import json
import os
import re
import yaml
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:
    ChatOpenAI = None
    HumanMessage = None
    ChatPromptTemplate = None
from ..state import AgentState
from ..schemas import AnalysisResult
from core.callbacks import RealtimeDebugCallbackHandler

api_key = os.environ.get("DEEPSEEK_API_KEY")
base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
model_name = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
llm = (
    ChatOpenAI(api_key=api_key, base_url=base_url, model=model_name, timeout=90)
    if api_key and ChatOpenAI is not None
    else None
)

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

    prompt_template = ChatPromptTemplate.from_messages([
        ("system", PROMPT_CONFIG["analyzer_agent"]["system_prompt"]),
        ("human", PROMPT_CONFIG["analyzer_agent"]["human_template"])
    ])

    chain = prompt_template | llm
    
    try:
        task_id = state.get("task_id")
        callbacks = [RealtimeDebugCallbackHandler(task_id)] if task_id else None
        config = {"callbacks": callbacks} if callbacks else None
        response = await chain.ainvoke({
            "schema": json.dumps(schema, ensure_ascii=False),
            "materials": json.dumps(materials, ensure_ascii=False)
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
                        old_cell = row["values"].get(comp, {})
                        row["values"][comp] = {
                            "value": cell.get("value", ""),
                            "status": "accepted" if cell.get("value") else "degraded",
                            "evidence_refs": old_cell.get("evidence_refs", []),
                            "degraded_reason": cell.get("degraded_reason", "") or old_cell.get("degraded_reason", "")
                        }
        llm_swot = parsed.get("swot_analysis", {})
        if isinstance(llm_swot, dict) and llm_swot:
            def parse_swot_item(t):
                if isinstance(t, dict):
                    return {"text": t.get("text", ""), "evidence_refs": t.get("evidence_refs", [])}
                return {"text": str(t), "evidence_refs": []}
            swot = {
                "competitor": llm_swot.get("competitor", "Target Competitor"),
                "strengths": [parse_swot_item(t) for t in llm_swot.get("strengths", []) if t],
                "weaknesses": [parse_swot_item(t) for t in llm_swot.get("weaknesses", []) if t],
                "opportunities": [parse_swot_item(t) for t in llm_swot.get("opportunities", []) if t],
                "threats": [parse_swot_item(t) for t in llm_swot.get("threats", []) if t],
                "so_strategies": [parse_swot_item(t) for t in llm_swot.get("so_strategies", []) if t],
                "wo_strategies": [parse_swot_item(t) for t in llm_swot.get("wo_strategies", []) if t],
                "st_strategies": [parse_swot_item(t) for t in llm_swot.get("st_strategies", []) if t],
                "wt_strategies": [parse_swot_item(t) for t in llm_swot.get("wt_strategies", []) if t],
            }
            result["swot"] = swot
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

    state["analysis_results"] = result
    return state


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
        "swot": {
            "competitor": competitors[0] if competitors else "Unknown",
            "strengths": [{"text": "Public information is available for comparison.", "evidence_refs": evidence_refs[:2]}],
            "weaknesses": [{"text": "Some fields may require manual verification.", "evidence_refs": evidence_refs[:2]}],
            "opportunities": [{"text": "Use verified sources to refine positioning.", "evidence_refs": evidence_refs[:2]}],
            "threats": [{"text": "Source gaps can reduce confidence.", "evidence_refs": evidence_refs[:2]}],
            "so_strategies": [{"text": "Leverage public info to improve positioning.", "evidence_refs": []}],
            "wo_strategies": [{"text": "Verify sources to capture opportunities.", "evidence_refs": []}],
            "st_strategies": [{"text": "Use public info to mitigate gaps.", "evidence_refs": []}],
            "wt_strategies": [{"text": "Verify fields to prevent source gaps.", "evidence_refs": []}],
        },
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
