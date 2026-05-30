# Implementation Tasks: Agentic RAG Router

**Phase 1: Environment & Configuration**

- [ ] **Task 1: Add Dependencies**
  - Add `crawl4ai` to `backend/requirements.txt`.
  - Also ensure any required asynchronous runtime features are configured.

- [ ] **Task 2: Create Knowledge Base**
  - Create `backend/agents/collector/knowledge_base.yaml`.
  - Add dummy or real sample data for at least one competitor and one general domain source, including `url`, `name`, `description`, `tags`, and `competitors` fields.

**Phase 2: Semantic Router & Crawling**

- [ ] **Task 3: Implement Semantic Routing Logic**
  - In `backend/agents/collector/node.py` (or a new `router.py`), implement a function to load the YAML file.
  - Implement hard filtering: reject URLs if `competitors` is defined but does not contain the current competitor.
  - Implement soft filtering (LLM): Prompt the LLM to select the most relevant remaining URLs based on the `task_context` (domain and competitor).

- [ ] **Task 4: Integrate Crawl4ai**
  - Implement an asynchronous function to fetch the selected URLs using `crawl4ai.AsyncWebCrawler`.
  - Store the extracted Markdown in an in-memory dictionary cache to prevent redundant fetching during the field iteration.

**Phase 3: Extraction & Fallback Modification**

- [ ] **Task 5: Refactor Extraction Loop**
  - In `run_collector_for_skill` (`node.py`), insert the routing and fetching steps *before* the inner `schema_fields` loop.
  - Modify the extraction logic to iterate over the cached Markdown from the routed URLs first.
  - Explicitly check if the LLM response is exactly `"NOT_FOUND"`. If so, do not use the raw excerpt. Move to the next URL.
  - If all routed URLs return `"NOT_FOUND"` or no URLs were routed, fall back to the existing `search_public_web` (DuckDuckGo) flow.
