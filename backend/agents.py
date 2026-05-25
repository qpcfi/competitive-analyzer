import os
import json
import asyncio
from typing import Dict, TypedDict, Any, List
from langgraph.graph import StateGraph, START, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage


os.environ["DEEPSEEK_API_KEY"] = "sk-1215aff0b7a548fd939746d863a945f8"

llm = ChatOpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com",
    model="deepseek-v4-pro"
)

class AgentState(TypedDict):
    task_id: str
    task_context: Dict[str, Any]
    dynamic_schema: Dict[str, Any]
    raw_materials: List[Dict[str, Any]]
    analysis_results: Dict[str, Any]
    critic_feedback: List[str]

async def orchestrator_node(state: AgentState):
    context = state['task_context']
    prompt = f"""
    You are the Orchestrator for a competitive analyzer.
    Domain: {context['domain']}
    Competitors: {context['competitors']}
    Generate a JSON schema of comparison dimensions for these competitors.
    Return ONLY valid JSON format.
    Example format:
    {{
      "核心基础信息": [{{"name": "产品名称", "type": "文本"}}]
    }}
    """
    res = await llm.ainvoke([HumanMessage(content=prompt)])
    try:
        import re
        content = res.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            schema = json.loads(match.group(0))
        else:
            schema = json.loads(content)
    except Exception as e:
        schema = {"核心基础信息": [{"name": "产品名称", "type": "文本"}]}
        
    state["dynamic_schema"] = schema
    return state

from bs4 import BeautifulSoup
import httpx

async def collector_node(state: AgentState):
    competitors = state['task_context']['competitors']
    
    results = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for comp in competitors:
            try:
                url = f"https://html.duckduckgo.com/html/?q={comp}+pricing+features"
                response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                soup = BeautifulSoup(response.text, 'html.parser')
                content = soup.get_text(separator=' ', strip=True)
                results.append({"competitor": comp, "content": content[:1500]})
            except Exception as e:
                results.append({"competitor": comp, "content": f"Failed to fetch data: {str(e)}"})
        
    state["raw_materials"] = results
    return state

async def analyzer_node(state: AgentState):
    schema = state.get("dynamic_schema", {})
    materials = state.get("raw_materials", [])
    
    prompt = f"""
    Analyze the following competitors based on the schema and provided raw materials.
    Schema: {json.dumps(schema, ensure_ascii=False)}
    Raw Materials: {json.dumps(materials, ensure_ascii=False)}
    
    Output a structured JSON containing the comparison and a SWOT analysis.
    """
    res = await llm.ainvoke([HumanMessage(content=prompt)])
    try:
        import re
        content = res.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            result = json.loads(match.group(0))
        else:
            result = json.loads(content)
    except:
        result = {"error": "Failed to parse LLM output"}
        
    state["analysis_results"] = result
    return state

workflow = StateGraph(AgentState)
workflow.add_node("orchestrator", orchestrator_node)
workflow.add_node("collector", collector_node)
workflow.add_node("analyzer", analyzer_node)

workflow.add_edge(START, "orchestrator")
workflow.add_edge("orchestrator", "collector")
workflow.add_edge("collector", "analyzer")
workflow.add_edge("analyzer", END)

app = workflow.compile()
