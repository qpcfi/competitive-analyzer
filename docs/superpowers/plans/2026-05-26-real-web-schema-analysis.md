# Real Web Schema Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a real public-web-driven schema validation, collection, and competitor analysis path with no static sample analysis rows.

**Architecture:** Add a small backend web-search helper used by Orchestrator and Collector. Orchestrator performs schema evidence discovery before `schema_ready`; Collector gathers source materials per final schema field; Analyzer converts source materials into a schema-dimension matrix. Frontend analysis rendering consumes only backend analysis data.

**Tech Stack:** FastAPI, httpx, BeautifulSoup, pytest, React, Next.js, Ant Design, TypeScript.

---

## File Structure

- Create `backend/services/web_search.py`: public DuckDuckGo HTML search helper and result parser.
- Modify `backend/agents/orchestrator.py`: use web search results to validate/recommend schema fields.
- Modify `backend/agents/collector.py`: collect source materials per competitor and schema field.
- Modify `backend/agents/analyzer.py`: emit schema-driven matrix output.
- Modify `frontend/src/components/views/CompetitorAnalysis.tsx`: remove static fallback data and render dynamic results only.
- Add/modify backend tests under `backend/tests/unit/`.
- Add frontend component-level or static-source tests if the project test stack supports them; otherwise use source-level assertion in existing test command scope.

## Tasks

### Task 1: Backend Web Search Helper

**Files:**
- Create: `backend/services/web_search.py`
- Test: `backend/tests/unit/test_web_search.py`

- [ ] Write a failing test that parses DuckDuckGo-style result HTML into title, URL, and snippet.
- [ ] Run `pytest backend/tests/unit/test_web_search.py -v` and confirm it fails because `services.web_search` does not exist.
- [ ] Implement `SearchResult`, `parse_duckduckgo_results`, and `search_public_web`.
- [ ] Run `pytest backend/tests/unit/test_web_search.py -v` and confirm it passes.

### Task 2: Evidence-Backed Schema Generation

**Files:**
- Modify: `backend/agents/orchestrator.py`
- Test: `backend/tests/unit/test_orchestrator_schema_evidence.py`

- [ ] Write a failing async test that monkeypatches Orchestrator search to return evidence for one user field and asserts the field gets `feasibility: high`, evidence refs, and recommended queries.
- [ ] Run the test and confirm it fails because schema evidence metadata is missing.
- [ ] Update Orchestrator to search public web for user fields and recommended dimensions.
- [ ] Run the new Orchestrator test and relevant existing schema tests.

### Task 3: Schema-Field Collection

**Files:**
- Modify: `backend/agents/collector.py`
- Test: `backend/tests/unit/test_collector_schema_fields.py`

- [ ] Write a failing async test that passes two competitors and two schema fields, monkeypatches search results, and expects four materials with `schema_field_id`.
- [ ] Run the test and confirm it fails because Collector only collects one material per competitor.
- [ ] Update Collector to collect per competitor and schema field.
- [ ] Run the Collector test and existing collection integration tests.

### Task 4: Schema-Driven Analyzer Matrix

**Files:**
- Modify: `backend/agents/analyzer.py`
- Test: `backend/tests/unit/test_analyzer_schema_matrix.py`

- [ ] Write a failing test that passes final schema and raw materials, then asserts `comparison_rows` dimensions exactly match schema fields and competitors match collected materials.
- [ ] Run the test and confirm it fails because Analyzer emits only summary comparison data.
- [ ] Update deterministic analysis builder and LLM fallback normalization to emit `discovered_competitors`, `schema_dimensions`, and `comparison_rows`.
- [ ] Run Analyzer tests and existing evidence traceability tests.

### Task 5: Frontend Dynamic Analysis Rendering

**Files:**
- Modify: `frontend/src/components/views/CompetitorAnalysis.tsx`

- [ ] Add a source-level test or assertion that `CompetitorAnalysis.tsx` no longer contains static competitor fallback names like `GPT-4o`, `Claude 3.5`, `Gemini 1.5`, or fixed values like `$20/月`.
- [ ] Run the assertion and confirm it fails before editing.
- [ ] Replace static columns/data/focus cards with dynamic rendering from `analysisResults.discovered_competitors` and `analysisResults.comparison_rows`.
- [ ] Run the assertion and frontend build/typecheck.

### Task 6: End-to-End Verification

**Files:**
- Modify only if verification exposes contract mismatches.

- [ ] Run backend unit tests for modified modules.
- [ ] Run backend contract/integration tests around task lifecycle and schema resume.
- [ ] Run frontend typecheck/build.
- [ ] If local services are available, run the existing real E2E Playwright test against backend and PostgreSQL.
- [ ] Search `frontend/src` and `backend` for remaining user-visible static analysis fallback data and remove any findings.

## Self-Review

This plan covers the approved design: schema evidence pass, schema-field collection, schema matrix analysis, frontend dynamic rendering, and verification. No task asks for fabricated fallback data. Public web failures are represented as degraded source materials or empty states.
