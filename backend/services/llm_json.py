import json
import re
from typing import Any


def extract_json_object(text: str) -> dict[str, Any]:
    if not text:
        raise ValueError("Empty model output")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    payload = match.group(0) if match else text
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object")
    return parsed


def extract_json_array(text: str) -> list[Any]:
    if not text:
        raise ValueError("Empty model output")
    match = re.search(r"\[.*\]", text, re.DOTALL)
    payload = match.group(0) if match else text
    parsed = json.loads(payload)
    if not isinstance(parsed, list):
        raise ValueError("Expected JSON array")
    return parsed
