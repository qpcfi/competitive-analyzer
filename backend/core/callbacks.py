import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage

from services.events import event_broker


class RealtimeDebugCallbackHandler(AsyncCallbackHandler):
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.total_tokens = 0
        self.budget = 50000
        self.run_starts = {}

    async def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        self.run_starts[run_id] = time.time()
        system_prompt = prompts[0] if prompts else ""
        
        await event_broker.publish(
            self.task_id, 
            "debug_log", 
            {
                "agent": "LLM",
                "event": "start",
                "message": f"LLM execution started",
                "prompt": system_prompt,
                "input_json": kwargs.get("invocation_params", {})
            }
        )

    async def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        self.run_starts[run_id] = time.time()
        system_prompt = ""
        if messages and messages[0]:
            for m in messages[0]:
                if m.type == "system":
                    system_prompt = m.content
                    break
            if not system_prompt:
                system_prompt = messages[0][0].content
                
        input_data = [{"role": m.type, "content": m.content} for m in messages[0]] if messages else []
                
        await event_broker.publish(
            self.task_id, 
            "debug_log", 
            {
                "agent": "LLM",
                "event": "start",
                "message": f"Chat Model execution started",
                "prompt": system_prompt,
                "input_json": input_data
            }
        )

    async def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        latency = time.time() - self.run_starts.get(run_id, time.time())
        llm_output_text = response.generations[0][0].text if response.generations else ""
        
        token_usage = response.llm_output.get("token_usage", {}) if response.llm_output else {}
        used = token_usage.get("total_tokens", 0)
        if not used and hasattr(response.generations[0][0], "message"):
            msg = response.generations[0][0].message
            if hasattr(msg, "response_metadata") and msg.response_metadata:
                token_usage = msg.response_metadata.get("token_usage", {})
                used = token_usage.get("total_tokens", 0)
                
        if not used:
            # Estimate tokens roughly if API doesn't return
            used = len(llm_output_text) // 4
            
        self.total_tokens += used
        
        await event_broker.publish(
            self.task_id, 
            "debug_log", 
            {
                "agent": "LLM",
                "event": "end",
                "message": f"LLM execution finished",
                "latency": latency,
                "output_json": llm_output_text
            }
        )
        await event_broker.publish(
            self.task_id, 
            "token_update", 
            {
                "total_used": self.total_tokens,
                "budget": self.budget,
                "estimated_remaining": max(0, self.budget - self.total_tokens)
            }
        )

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        inputs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        self.run_starts[run_id] = time.time()
        await event_broker.publish(
            self.task_id,
            "debug_log",
            {
                "agent": "Tool",
                "event": "start",
                "message": f"Tool '{serialized.get('name', 'unknown')}' started",
                "input_json": inputs or input_str
            }
        )
        
    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        latency = time.time() - self.run_starts.get(run_id, time.time())
        await event_broker.publish(
            self.task_id,
            "debug_log",
            {
                "agent": "Tool",
                "event": "end",
                "message": f"Tool execution finished",
                "latency": latency,
                "output_json": str(output)
            }
        )
