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

async def orchestrator_node(state: AgentState):
    context = state.get('task_context', {})
    prompt = f"""
    You are the Orchestrator for a competitive analyzer.
    Domain: {context.get('domain', 'Unknown')}
    Competitors: {context.get('competitors', [])}
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
