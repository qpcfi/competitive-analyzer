# Real Web Schema Analysis Design

## Goal

Make the task flow use real public-web collection for schema validation,
schema recommendations, competitor discovery, and schema-driven competitor
analysis. Static sample competitor rows and fabricated values must not appear
in the validated workflow.

## Scope

This change covers the path from clicking "下一步：配置Schema" through saving
the reviewed schema and rendering "竞品深度分析".

The selected data strategy is DuckDuckGo HTML search first. The backend may
degrade when public search is unavailable, but it must not invent values or
present static examples as task data.

## Backend Design

Task creation starts a schema evidence pass. The Orchestrator searches public
HTML result pages using the task domain, initial competitors, and user-defined
schema dimensions. It uses collected snippets to mark each user dimension with
`feasibility`, `evidence_refs`, and `recommended_queries`. It also recommends
additional dimensions only when search evidence supports them. Unsupported
recommendations are omitted rather than fabricated.

Saving and continuing a schema starts a collection pass. The Collector expands
the final schema into `competitor x schema_field` search jobs and stores source
materials with `competitor`, `schema_field_id`, `schema_field_name`,
`source_url`, `quote_text`, `validation_status`, and `degraded_reason`.

The Analyzer builds a matrix from source materials. The output contains
`discovered_competitors`, `schema_dimensions`, and `comparison_rows`. Every
cell is either evidence-backed or explicitly degraded as information missing.
No fixed competitor names or fixed example values are emitted.

## Frontend Design

`CompetitorAnalysis` renders only backend-provided analysis results. Columns
come from `discovered_competitors`; rows come from `comparison_rows`; dimension
labels come from the final schema. If no analysis is available, the view shows
a truthful waiting/empty state. It does not include static fallback rows.

Source buttons pass evidence IDs into the right drawer so the source surface
can load actual source material records.

## Error Handling

Public search failures produce degraded schema fields or degraded source cells
with reason strings. The workflow can continue if at least the task and schema
state are persisted. User-visible output must distinguish accepted evidence
from degraded/missing evidence.

## Verification

Backend tests cover schema evidence generation, schema-field collection, and
schema-driven analysis output. Frontend tests cover the absence of static
fallback competitor rows when `analysisResults` is missing and dynamic rendering
when real analysis data is supplied.
