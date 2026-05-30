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
from core.callbacks import RealtimeDebugCallbackHandler

api_key = os.environ.get("DEEPSEEK_API_KEY")
base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
model_name = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
llm = (
    ChatOpenAI(api_key=api_key, base_url=base_url, model=model_name, timeout=90)
    if api_key and ChatOpenAI is not None
    else None
)

async def reporter_node(state: AgentState):
    analysis_results = state.get("analysis_results", {})
    
    if llm is None or ChatPromptTemplate is None:
        return state
    
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            PROMPT_CONFIG = yaml.safe_load(f)
    except Exception:
        return state

    prompt_template = ChatPromptTemplate.from_messages([
        ("system", PROMPT_CONFIG["reporter_agent"]["system_prompt"]),
        ("human", PROMPT_CONFIG["reporter_agent"]["human_template"])
    ])

    chain = prompt_template | llm
    
    try:
        task_id = state.get("task_id")
        callbacks = [RealtimeDebugCallbackHandler(task_id)] if task_id else None
        config = {"callbacks": callbacks} if callbacks else None
        response = await chain.ainvoke({
            "analysis_results": json.dumps(analysis_results, ensure_ascii=False)
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
        
        if "report" not in analysis_results:
            analysis_results["report"] = {}
            
        if "executive_summary" in parsed:
            analysis_results["report"]["summary"] = parsed["executive_summary"]
            
        if "key_takeaways" in parsed:
            analysis_results["report"]["recommendations"] = parsed["key_takeaways"]
            
        state["analysis_results"] = analysis_results
        
    except Exception as e:
        import logging
        logging.error(f"Error in reporter_node: {e}")

    return state
