import json
import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from .state import AgentState

llm = ChatOpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY', 'sk-1215aff0b7a548fd939746d863a945f8'),
    base_url="https://api.deepseek.com",
    model="deepseek-v4-pro"
)

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
