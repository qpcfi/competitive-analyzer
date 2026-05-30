# Implementation Plan: Agentic RAG Router

**Branch**: `002-agentic-rag-router`
**Spec**: [spec.md](./spec.md)

## Summary
Implement a semantic routing system for the Collector agent to prioritize fetching structured data from a predefined set of curated URLs using `crawl4ai`. Only fall back to general DuckDuckGo searches if no relevant sources are found or if the sources lack the necessary information.

## Technical Context
- **Dependencies**: Add `crawl4ai` to `requirements.txt`.
- **Configuration**: Create `backend/agents/collector/knowledge_base.yaml` for data source metadata.
- **Routing Logic**: Implement an LLM call to semantically filter `knowledge_base.yaml` entries based on `domain` and `competitors`.
- **Extraction Logic**: Modify `collector/node.py` to prioritize `crawl4ai` fetched markdown, and properly handle "NOT_FOUND" responses from the LLM to trigger a fallback.

## Design Decisions
1. **Knowledge Base Format**: YAML is used for easy manual editing and readability.
2. **Semantic Routing**: Hard filter by `competitors` first, then use the LLM to evaluate the remaining URLs based on `description` and `tags` against the task context.
3. **Caching**: Fetched Markdown from `crawl4ai` must be cached per task execution to avoid redundant network calls during the field extraction loops.
4. **Strict Fallback**: The extraction LLM's "NOT_FOUND" output must be explicitly checked, preventing the entire excerpt from being saved as degraded data when a targeted URL misses a specific field.
