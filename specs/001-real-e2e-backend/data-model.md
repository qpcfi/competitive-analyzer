# Data Model: Real End-to-End Backend

## Task

Represents one competitive-analysis workflow.

**Fields**:
- `id` string, primary identifier such as `task_<uuid-fragment>`
- `task_name` string
- `domain` string, required
- `competitors` JSON array of strings, minimum 2
- `execution_mode` enum: `step_by_step`, `auto`
- `state` enum: `INITIALIZING`, `SCHEMA_GENERATING`, `SCHEMA_REVIEW`,
  `COLLECTING`, `ANALYZING`, `QUALITY_REVIEW`, `COMPLETED`, `ERROR`, `PAUSED`,
  `NEEDS_INTERVENTION`
- `progress` integer 0-100
- `current_checkpoint_id` string, nullable
- `owner_id` string, nullable for local mode
- `error` JSON object, nullable
- `created_at`, `updated_at`, `completed_at` timestamps

**Relationships**:
- One Task has one active Dynamic Schema.
- One Task has many Source Materials, Analysis Results, Quality Feedback items,
  Task Events, and Intervention Logs.

**Validation rules**:
- `domain` must be non-empty after trimming.
- `competitors` must contain at least two unique non-empty names.
- `execution_mode` must be one of the supported enum values.
- Terminal `COMPLETED` tasks reject resume/reject unless creating a partial
  rerun sub-operation.

## Dynamic Schema

Represents the active analysis framework.

**Fields**:
- `id` string
- `task_id` string
- `version` integer
- `status` enum: `draft`, `active`, `rejected`, `archived`
- `schema_json` JSON object grouped by dimensions
- `field_index` JSON array with stable field IDs, names, types, required flags,
  source expectations, priority, feasibility, and origin
- `created_by` enum: `agent`, `user`, `system`
- `created_at`, `updated_at` timestamps

**Relationships**:
- Belongs to Task.
- Source Materials and Analysis Results reference schema field IDs where
  applicable.

**Validation rules**:
- Must include core identity fields: product name, company/owner, and source
  link expectations.
- Active schema must be valid JSON and have stable field IDs.
- User edits create a new version or update the draft before activation.

## Source Material

Represents evidence collected or added for a competitor/schema field.

**Fields**:
- `id` string
- `task_id` string
- `schema_field_id` string, nullable for general source records
- `competitor` string
- `source_url` string, nullable for user-provided evidence
- `source_type` enum: `official`, `docs`, `review`, `search`, `user_added`,
  `unknown`
- `quote_text` text
- `extracted_value` JSON, nullable
- `fetch_timestamp` timestamp
- `agent_node` string
- `access_status` enum: `allowed`, `blocked`, `timeout`, `error`, `not_checked`
- `validation_status` enum: `pending`, `accepted`, `failed`, `degraded`
- `trust_status` enum: `official`, `third_party`, `inferred`, `untrusted`,
  `degraded`
- `retry_count` integer
- `degraded_reason` string, nullable
- `pii_redacted` boolean

**Relationships**:
- Belongs to Task.
- May support many evidence references in Analysis Result content.

**Validation rules**:
- Accepted records require evidence text or extracted value.
- Records with blocked access cannot be marked accepted.
- Text sent to model processing must have `pii_redacted=true`.

## Analysis Result

Represents rendered modules derived from accepted evidence.

**Fields**:
- `id` string
- `task_id` string
- `module_id` string, e.g. `comparison`, `swot`, `report`,
  `competitor:<name>`
- `module_type` enum: `competitor_comparison`, `swot`, `report`, `debug`
- `version` integer
- `content` JSON object matching frontend expectations
- `evidence_refs` JSON array of source material IDs and schema field IDs
- `quality_status` enum: `pending`, `passed`, `failed`, `degraded`,
  `needs_intervention`
- `created_at`, `updated_at` timestamps

**Relationships**:
- Belongs to Task.
- Has many Quality Feedback records.

**Validation rules**:
- Final modules require evidence refs for every visible claim or an explicit
  degraded marker.
- Failed modules cannot be included in final report without visible feedback.

## Quality Feedback

Represents L1 or L2 validation output.

**Fields**:
- `id` string
- `task_id` string
- `level` enum: `L1`, `L2`
- `target_type` enum: `source_material`, `analysis_result`, `task`
- `target_id` string
- `module_id` string, nullable
- `severity` enum: `info`, `warning`, `error`, `blocking`
- `code` string
- `message` string
- `suggested_action` enum: `retry_collection`, `retry_analysis`,
  `manual_intervention`, `degrade`, `ignore`
- `retry_count` integer
- `resolved` boolean
- `created_at`, `resolved_at` timestamps

**Validation rules**:
- Blocking feedback must prevent `COMPLETED` until resolved, degraded, or
  explicitly marked for manual intervention.
- Retry count must not exceed configured bounds.

## Task Event

Represents a persisted live event for SSE and reconnect replay.

**Fields**:
- `id` integer or uuid
- `task_id` string
- `sequence` integer, monotonically increasing per task
- `event_type` string: `task_state_changed`, `schema_ready`,
  `raw_materials_updated`, `analysis_progress`, `progress_update`,
  `debug_log`, `token_update`, `module_updated`, `task_failed`,
  `task_completed`
- `payload` JSON object
- `created_at` timestamp

**Relationships**:
- Belongs to Task.

**Validation rules**:
- Every published event is persisted before live delivery.
- Reconnect queries return events ordered by `sequence`.

## Intervention Log

Represents user actions that modify workflow state.

**Fields**:
- `id` string
- `task_id` string
- `action_type` enum: `schema_update`, `schema_confirm`, `schema_reject`,
  `pause`, `resume`, `partial_rerun`, `source_add`, `source_remove`
- `payload` JSON object
- `actor_id` string, nullable
- `created_at` timestamp

**Validation rules**:
- Actions must be rejected when task state makes them invalid.
- Every state-changing endpoint writes an intervention log.

## Task Snapshot

Represents a restorable checkpoint shown in execution history.

**Fields**:
- `id` string
- `task_id` string
- `checkpoint_id` string
- `state` string
- `summary` string
- `snapshot_data` JSON object or checkpoint reference
- `created_at` timestamp

**Validation rules**:
- Snapshot restore must reject missing checkpoint IDs.
- Restore in `clone` mode creates a new Task record linked to the source task.

## User Feedback

Represents credibility and suspicion feedback from analysis/source views.

**Fields**:
- `id` string
- `task_id` string
- `target_type` enum: `source_material`, `analysis_result`, `claim`,
  `competitor`
- `target_id` string
- `feedback` enum: `credible`, `suspicious`, `untrusted`, `needs_review`
- `comment` string, nullable
- `actor_id` string, nullable
- `created_at` timestamp

**Validation rules**:
- Target must belong to the same task.
- Feedback changes that affect trust status must emit a task event.

## User Note

Represents notes added from competitor or report views.

**Fields**:
- `id` string
- `task_id` string
- `target_type` enum: `source_material`, `analysis_result`, `competitor`,
  `report`
- `target_id` string
- `note` text
- `actor_id` string, nullable
- `created_at`, `updated_at` timestamps

**Validation rules**:
- Notes must not alter source evidence or analysis content.
- Notes must be returned separately from machine-generated claims.

## Report Export

Represents generated files and share links for report actions.

**Fields**:
- `id` string
- `task_id` string
- `format` enum: `pdf`, `markdown`, `json`, `share_link`
- `status` enum: `pending`, `ready`, `failed`, `expired`
- `file_path` string, nullable
- `share_token` string, nullable
- `expires_at` timestamp, nullable
- `created_at` timestamp

**Validation rules**:
- Exports require task state `COMPLETED` or an explicit degraded-report state.
- Share links must not expose raw debug logs or unredacted source text.

## Link Verification Result

Represents "verify all links" output for the source appendix.

**Fields**:
- `id` string
- `task_id` string
- `source_material_id` string
- `source_url` string
- `reachable` boolean
- `status_code` integer, nullable
- `checked_at` timestamp
- `error` string, nullable

**Validation rules**:
- Verification results do not overwrite original fetch timestamps.
- Failed verification updates source trust/degraded display only after a
  user-visible event is emitted.

## State Transitions

```text
INITIALIZING -> SCHEMA_GENERATING
SCHEMA_GENERATING -> SCHEMA_REVIEW
SCHEMA_REVIEW -> SCHEMA_GENERATING      # reject/regenerate
SCHEMA_REVIEW -> COLLECTING             # confirm/resume
COLLECTING -> ANALYZING                 # L1 accepted or degraded enough
COLLECTING -> NEEDS_INTERVENTION        # L1 blocking after retry limit
ANALYZING -> QUALITY_REVIEW
QUALITY_REVIEW -> ANALYZING             # retry analysis
QUALITY_REVIEW -> COLLECTING            # needs more evidence
QUALITY_REVIEW -> NEEDS_INTERVENTION    # L2 blocking after retry limit
QUALITY_REVIEW -> COMPLETED
Any non-terminal state -> PAUSED
PAUSED -> previous recoverable state
Any recoverable state -> ERROR
COMPLETED -> ANALYZING                  # targeted rerun creates new module version
```
