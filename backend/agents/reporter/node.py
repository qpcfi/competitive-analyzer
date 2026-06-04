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
    import sys
    print(f"[REPORTER] entered, task_id={state.get('task_id')}, llm={'ok' if llm else 'none'}", flush=True)
    analysis_results = state.get("analysis_results", {})
    task_id = state.get("task_id")

    if llm is None or ChatPromptTemplate is None:
        print("[REPORTER] llm or ChatPromptTemplate is None, returning early", flush=True)
        return state

    print("[REPORTER] loading prompts.yaml...", flush=True)
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            PROMPT_CONFIG = yaml.safe_load(f)
        print("[REPORTER] prompts.yaml loaded successfully", flush=True)
    except Exception as e:
        print(f"[REPORTER] failed to load prompts.yaml: {e}", flush=True)
        return state

    print("[REPORTER] building chain...", flush=True)
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", PROMPT_CONFIG["reporter_agent"]["system_prompt"]),
        ("human", PROMPT_CONFIG["reporter_agent"]["human_template"])
    ])

    chain = prompt_template | llm
    print("[REPORTER] chain built, about to invoke LLM...", flush=True)

    try:
        callbacks = [RealtimeDebugCallbackHandler(task_id)] if task_id else None
        config = {"callbacks": callbacks} if callbacks else None
        analysis_json = json.dumps(analysis_results, ensure_ascii=False)
        print(f"[REPORTER] invoking LLM with {len(analysis_json)} chars of data...", flush=True)
        response = await chain.ainvoke({
            "analysis_results": analysis_json
        }, config=config)
        print("[REPORTER] LLM returned successfully", flush=True)

        content = str(response.content)
        print(f"[REPORTER] raw response length: {len(content)} chars", flush=True)
        import re
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        match = re.search(r"\{.*\}", content, re.DOTALL)
        clean_content = match.group(0) if match else content
        try:
            parsed = json.loads(clean_content)
        except json.JSONDecodeError:
            print(f"[REPORTER] JSON decode error, trying to fix trailing commas...", flush=True)
            clean_content = re.sub(r',\s*([\]}])', r'\1', clean_content)
            parsed = json.loads(clean_content)

        print(f"[REPORTER] parsed JSON keys: {list(parsed.keys())}", flush=True)

        if "report" not in analysis_results:
            analysis_results["report"] = {}

        if "executive_summary" in parsed:
            analysis_results["report"]["summary"] = parsed["executive_summary"]
            print(f"[REPORTER] set summary, length={len(str(parsed['executive_summary']))}", flush=True)

        if "key_takeaways" in parsed:
            analysis_results["report"]["recommendations"] = parsed["key_takeaways"]
            print(f"[REPORTER] set recommendations, count={len(parsed['key_takeaways'])}", flush=True)

        state["analysis_results"] = analysis_results

    except Exception as e:
        import logging
        import traceback
        logging.error(f"Error in reporter_node: {e}\n{traceback.format_exc()}")
        print(f"[REPORTER] EXCEPTION: {e}", flush=True)

    print("[REPORTER] returning state", flush=True)
    return state
