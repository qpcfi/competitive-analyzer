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

async def critic_node(state: AgentState):
    analysis_results = state.get("analysis_results", {})
    
    prompt = f"""
    You are a Critic Agent. Evaluate the following analysis results for completeness and hallucination.
    If there are issues, output a JSON list of strings (feedback). If perfect, output an empty list [].
    
    Analysis: {json.dumps(analysis_results, ensure_ascii=False)}
    """
    res = await llm.ainvoke([HumanMessage(content=prompt)])
    try:
        import re
        content = res.content
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            feedback = json.loads(match.group(0))
        else:
            feedback = json.loads(content)
    except:
        feedback = ["Failed to parse critic feedback"]
        
    state["critic_feedback"] = feedback
    return state
