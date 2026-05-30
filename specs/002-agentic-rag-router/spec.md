# Feature Specification: Agentic RAG Router

**Feature Branch**: `002-agentic-rag-router`

**Created**: 2026-05-30

**Status**: Draft

**Input**: User description: "Introduce crawl4ai as scraping engine, add data source file with URLs and metadata (name, description, tags, competitors). Agent progressively loads/routes to relevant URLs based on search context, falling back to DuckDuckGo if NOT_FOUND."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Targeted Competitor Scraping (Priority: P1)

As a user analyzing a specific competitor, I want the system to exclusively use pre-configured official URLs for that competitor if they exist, so that the data is highly accurate and free of search engine noise.

**Why this priority**: Core value proposition of this feature. High precision data retrieval.

**Independent Test**: Can be tested by adding a mock URL for "OpenAI" in the knowledge base, running an analysis for "OpenAI", and verifying the agent only crawls that URL and doesn't hit DuckDuckGo.

**Acceptance Scenarios**:

1. **Given** a knowledge base with an entry for competitor X, **When** a task is created for competitor X, **Then** the agent routes to and crawls the configured URL.
2. **Given** a knowledge base with an entry for competitor X, **When** a task is created for competitor Y, **Then** the agent ignores competitor X's URLs.

### User Story 2 - General Domain Routing (Priority: P2)

As a user analyzing a domain without competitor-specific URLs, I want the system to route to pre-configured general domain URLs (like review sites) so that it can still leverage curated sources.

**Why this priority**: Enhances fallback capabilities before hitting the open web.

**Independent Test**: Can be tested by running an analysis for an unconfigured competitor in a configured domain.

**Acceptance Scenarios**:

1. **Given** a knowledge base with a general domain URL, **When** a task matches the domain but not specific competitors, **Then** the agent routes to the general URL.

### User Story 3 - DuckDuckGo Fallback (Priority: P1)

As a user, if the curated URLs fail to provide the necessary information, I want the system to gracefully fall back to a DuckDuckGo web search so that the analysis can still complete.

**Why this priority**: Crucial for robustness and avoiding failures.

**Independent Test**: Can be tested by configuring a URL that lacks pricing info, then asking for pricing. It should fall back to DDG.

**Acceptance Scenarios**:

1. **Given** a routed URL that returns "NOT_FOUND" for a field, **When** the extraction completes, **Then** the system triggers a DuckDuckGo search for that field.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST read a YAML configuration file (`knowledge_base.yaml`) defining data sources with `url`, `name`, `description`, `tags`, and optional `competitors`.
- **FR-002**: System MUST use an LLM-based router to filter the configured URLs based on the current task's domain and competitor context before collection begins.
- **FR-003**: System MUST fetch the routed URLs using the `crawl4ai` asynchronous crawler to extract clean Markdown.
- **FR-004**: System MUST prompt the extraction LLM with the crawled Markdown for specific schema fields.
- **FR-005**: System MUST explicitly detect "NOT_FOUND" in the LLM response.
- **FR-006**: System MUST fall back to DuckDuckGo search if all routed URLs return "NOT_FOUND" or if no URLs were routed.

### Key Entities

- **Knowledge Source**: Represents a curated URL with metadata used for semantic routing.
- **Routed URL**: A URL selected by the LLM router as relevant for the current context.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of configured competitor-specific URLs are correctly routed when that competitor is analyzed.
- **SC-002**: 0% of competitor-specific URLs are routed when a different competitor is analyzed.
- **SC-003**: Fallback to DuckDuckGo occurs automatically if curated URLs fail to provide information.

## Assumptions

- Users have valid `crawl4ai` and `playwright` dependencies installable in the environment.
- The `knowledge_base.yaml` is manually managed by developers/administrators.
