<!--
Sync Impact Report
Version change: template -> 1.0.0
Modified principles:
- Template Principle 1 -> I. Schema-Driven Traceability
- Template Principle 2 -> II. Orchestrated State and Human Control
- Template Principle 3 -> III. Two-Layer Quality Gates
- Template Principle 4 -> IV. Observable Agent Execution
- Template Principle 5 -> V. Compliance and Privacy by Design
Added sections:
- System Architecture Constraints
- Development Workflow and Quality Gates
Removed sections:
- Template placeholder sections
Templates requiring updates:
- updated: .specify/templates/plan-template.md
- updated: .specify/templates/spec-template.md
- updated: .specify/templates/tasks-template.md
- reviewed: .specify/templates/commands/*.md (directory absent; no update required)
- reviewed: README.md / AGENTS.md / frontend/AGENTS.md; no principle references required updates
Deferred items: none
-->
# Competitive Analyzer Constitution

## Core Principles

### I. Schema-Driven Traceability
Every competitive-analysis result MUST be generated from the active dynamic
schema and MUST retain evidence metadata from source to rendered report. Any
claim, metric, comparison row, SWOT item, or recommendation MUST be linked to
at least one source record containing quote text or extracted evidence,
source URL, fetch timestamp, responsible agent node, and trust status. Missing
or degraded data MUST be represented explicitly; fabricated fallback values are
forbidden.

Rationale: The product value depends on structured consistency and business
users being able to audit conclusions back to public evidence.

### II. Orchestrated State and Human Control
Agent work MUST flow through a LangGraph-style orchestrated state graph with
durable task state, checkpoints, and resumable execution. Features that affect
schema generation, data collection, analysis, report generation, or local
reruns MUST define their state transitions, SSE events, persistence behavior,
and user intervention points. Step-by-step mode MUST block at review gates until
the user confirms, while auto-run mode MUST preserve snapshots that support
later review and partial rerun.

Rationale: The system is a controllable research workflow, not an opaque batch
generator; users must be able to inspect, pause, correct, and resume work.

### III. Two-Layer Quality Gates
Collector outputs MUST pass deterministic L1 validation before entering shared
state: required fields, schema types, non-empty values, valid source URLs, retry
limits, and degraded-field markers. Analyzer outputs MUST pass L2 semantic
review by Critic or equivalent logic before being accepted as final: every
conclusion must have evidence support, contradiction checks, and hallucination
risk handling. L1/L2 failures MUST produce structured feedback and bounded
retry behavior; repeated failures MUST surface clear manual-intervention
guidance instead of looping indefinitely.

Rationale: Code-level validation controls predictable data errors cheaply, while
semantic review protects users from unsupported model conclusions.

### IV. Observable Agent Execution
Every task and agent node MUST emit enough runtime telemetry for live monitoring
and post-run replay. Required telemetry includes state changes, active agent,
current URL or module when applicable, status, duration, token usage estimate,
error class, retry count, prompt/context summary, and input/output JSON access
for debug mode. Backend traces SHOULD be compatible with LangSmith or an
equivalent trace sink, and frontend SSE consumers MUST degrade gracefully during
disconnects and replay recent events when possible.

Rationale: Debuggability, cost control, and trust require visibility into how
the multi-agent workflow made decisions.

### V. Compliance and Privacy by Design
Collector behavior MUST respect public-data boundaries and site access rules.
Before fetching public pages, the system MUST check robots.txt or an equivalent
policy cache and record allowed, blocked, timeout, and degraded decisions.
User-provided text and collected text MUST be scanned for PII before LLM
processing; emails, phone numbers, identity numbers, and comparable sensitive
tokens MUST be redacted locally. API access MUST enforce authentication and task
ownership before exposing task state, raw materials, traces, reports, or export
files.

Rationale: The product handles external web data and user research inputs, so
legal access, privacy, and tenant isolation are core product requirements.

## System Architecture Constraints

The backend is a FastAPI service using an orchestrated multi-agent workflow with
Collector, Analyzer, Critic, and Orchestrator responsibilities. PostgreSQL is
the source of truth for tasks, dynamic schemas, raw materials, checkpoints,
analysis results, intervention logs, and reports; Redis or an equivalent event
bus may be used for live event fan-out and reconnect buffers.

The frontend is a Next.js and React application driven by backend state and
dynamic schema data. Views MUST not hard-code competitive-analysis dimensions
when the active schema can provide them. The UI MUST support task creation,
schema review/editing, collection status, evidence drawers, comparison views,
SWOT, structured reports, debug telemetry, and responsive layouts for desktop,
tablet, and mobile breakpoints.

External network and LLM calls MUST use bounded timeout and retry policies.
Long-text extraction MUST use chunking before summarization or analysis. Failed
non-critical sources MUST degrade individual fields or modules without blocking
the whole task, while critical failures MUST leave recoverable task state.

## Development Workflow and Quality Gates

Plans MUST pass the Constitution Check before design proceeds and MUST be
rechecked after contracts and data models are drafted. Specs MUST define user
scenarios that can be tested independently, including success criteria for
schema behavior, evidence traceability, state transitions, observability,
responsiveness, and compliance when applicable.

Implementation tasks MUST include focused validation for changed behavior.
Contract tests are REQUIRED for new or changed API endpoints and SSE event
payloads. Integration tests are REQUIRED for state transitions, checkpoint
resume, partial rerun, L1/L2 quality gates, evidence propagation, and security
or privacy controls. Frontend changes to major workflow views MUST include
responsive layout verification for the documented breakpoints or an explicit
manual-test note.

Development MUST keep backend, frontend, and documentation contracts aligned:
API payloads, SSE event names, dynamic schema fields, database entities, and UI
states cannot diverge without updating the relevant spec, plan, contracts, and
tasks. Any deliberate violation of this constitution MUST be recorded in the
plan Complexity Tracking table with rationale and a simpler rejected
alternative.

## Governance

This constitution supersedes conflicting project guidance for feature planning,
implementation, and review. Amendments require a documented change to this file,
an updated Sync Impact Report, and review of dependent Spec Kit templates and
runtime guidance documents.

Versioning follows semantic versioning:
- MAJOR: Removes or redefines a core principle in a backward-incompatible way.
- MINOR: Adds a principle or materially expands required governance or gates.
- PATCH: Clarifies wording without changing required behavior.

Every feature review MUST verify that the Constitution Check passed, any
violations were justified, and required tests or manual verification notes were
completed before the feature is considered done.

**Version**: 1.0.0 | **Ratified**: 2026-05-25 | **Last Amended**: 2026-05-25
