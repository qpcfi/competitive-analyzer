# Contracts: API and SSE Events

The completed frontend already calls the endpoints below. Implementation must
preserve these URLs and payload shapes while replacing mock behavior with real
task state.

## Frontend Coverage Rule

Every existing frontend action must have one of these outcomes:
- A backend endpoint or SSE event defined in this file.
- A truthful disabled/empty state in the frontend with no mock data.

No user-visible workflow may rely on static analysis data, static source data,
`href="#"`, `return; // mock: not implemented`, or a response containing
`mock`/`mocked`.

## REST Endpoints

### POST `/api/v1/tasks`

Create a task and start schema generation.

**Request**:

```json
{
  "task_name": "AI大模型分析_20260525",
  "domain": "AI大模型",
  "competitors": ["GPT-4o", "Claude 3.5", "Gemini 1.5"],
  "execution_mode": "step_by_step",
  "predefined_schema": [
    {
      "name": "API响应速度",
      "type": "number",
      "source": "official_docs"
    }
  ]
}
```

**Success 201/200**:

```json
{
  "task_id": "task_ab12cd34",
  "state": "INITIALIZING",
  "stream_url": "/api/v1/tasks/task_ab12cd34/stream"
}
```

**Validation errors**:
- `400` missing domain
- `400` fewer than two competitors
- `400` unsupported execution mode
- `400` malformed predefined schema

### GET `/api/v1/tasks/{task_id}`

Return current persisted task state for reload/reconnect.

**Success 200**:

```json
{
  "task_id": "task_ab12cd34",
  "task_name": "AI大模型分析_20260525",
  "domain": "AI大模型",
  "competitors": ["GPT-4o", "Claude 3.5", "Gemini 1.5"],
  "execution_mode": "step_by_step",
  "state": "SCHEMA_REVIEW",
  "progress": 30,
  "dynamic_schema": {},
  "raw_materials": [],
  "analysis_results": {},
  "critic_feedback": [],
  "updated_at": "2026-05-25T18:30:00Z"
}
```

### GET `/api/v1/tasks`

Back the sidebar history view.

**Query**: `page`, `limit`, `state`, `q`

**Success 200**:

```json
{
  "items": [
    {
      "task_id": "task_ab12cd34",
      "task_name": "AI model analysis",
      "domain": "AI models",
      "state": "COMPLETED",
      "progress": 100,
      "snapshot_count": 4,
      "created_at": "2026-05-25T18:00:00Z",
      "updated_at": "2026-05-25T18:45:00Z"
    }
  ],
  "page": 1,
  "limit": 20,
  "total": 1
}
```

### GET `/api/v1/tasks/{task_id}/stream?since={sequence}`

Open an SSE stream. If `since` is provided, replay persisted events with a
higher sequence before live events.

**SSE frame**:

```text
event: task_state_changed
data: {"sequence":1,"state":"SCHEMA_GENERATING","previous_state":"INITIALIZING"}
```

### PUT `/api/v1/tasks/{task_id}/schema`

Save draft schema edits.

**Request**:

```json
{
  "dynamic_schema": {
    "核心基础信息": [
      {
        "id": "basic.product_name",
        "name": "产品名称",
        "type": "text",
        "required": true
      }
    ]
  }
}
```

**Success 200**:

```json
{
  "status": "updated",
  "schema_version": 2,
  "state": "SCHEMA_REVIEW"
}
```

### POST `/api/v1/tasks/{task_id}/resume`

Confirm schema review or resume a paused task.

**Success 200**:

```json
{
  "status": "resumed",
  "state": "COLLECTING"
}
```

### POST `/api/v1/tasks/{task_id}/reject_schema`

Reject current schema and request regeneration.

**Success 202/200**:

```json
{
  "status": "regenerating",
  "state": "SCHEMA_GENERATING"
}
```

No response may contain `mock`, `mocked`, or static placeholder status.

### POST `/api/v1/tasks/{task_id}/pause`

Pause a recoverable task state.

**Success 200**:

```json
{
  "status": "paused",
  "state": "PAUSED"
}
```

### POST `/api/v1/tasks/{task_id}/force_next`

Force transition from a recoverable blocked or paused state to the next
workflow node. This backs the information dashboard's "force next node" button.
The endpoint must write an intervention log and must reject unsafe transitions.

**Request**:

```json
{
  "reason": "User accepted degraded collection results"
}
```

**Success 200**:

```json
{
  "status": "advanced",
  "state": "ANALYZING"
}
```

### POST `/api/v1/tasks/{task_id}/partial_rerun`

Request targeted rerun.

**Request**:

```json
{
  "target_module": "swot.threats",
  "new_instruction": "增加对开源协议的分析",
  "rerun_scope": "current_only",
  "override_system_prompt": null
}
```

**Success 202/200**:

```json
{
  "status": "rerunning",
  "module_id": "swot.threats",
  "state": "ANALYZING"
}
```

### GET `/api/v1/tasks/{task_id}/events?since={sequence}&limit=100`

Return persisted events for reconnect/debug.

**Success 200**:

```json
{
  "task_id": "task_ab12cd34",
  "events": [
    {
      "sequence": 12,
      "event_type": "schema_ready",
      "payload": {"dynamic_schema": {}},
      "created_at": "2026-05-25T18:30:01Z"
    }
  ]
}
```

### GET `/api/v1/tasks/{task_id}/snapshots`

Return persisted workflow checkpoints for the history/snapshot UI.

**Success 200**:

```json
{
  "task_id": "task_ab12cd34",
  "snapshots": [
    {
      "checkpoint_id": "cp_001",
      "state": "SCHEMA_REVIEW",
      "created_at": "2026-05-25T18:12:00Z",
      "summary": "Schema ready for review"
    }
  ]
}
```

### POST `/api/v1/tasks/{task_id}/restore_snapshot`

Clone or restore from a checkpoint for execution history.

**Request**:

```json
{
  "checkpoint_id": "cp_001",
  "mode": "clone"
}
```

**Success 200**:

```json
{
  "task_id": "task_clone_001",
  "state": "SCHEMA_REVIEW"
}
```

### GET `/api/v1/tasks/{task_id}/source-materials`

Back the information dashboard and data intervention drawer.

**Success 200**:

```json
{
  "items": [
    {
      "id": "src_001",
      "competitor": "GPT-4o",
      "source_url": "https://example.com",
      "quote_text": "quoted evidence",
      "validation_status": "accepted",
      "trust_status": "official",
      "is_noise": false
    }
  ]
}
```

### GET `/api/v1/tasks/{task_id}/source-materials/{source_id}`

Back the source drawer.

**Success 200**:

```json
{
  "id": "src_001",
  "source_url": "https://example.com",
  "quote_text": "quoted evidence",
  "fetch_timestamp": "2026-05-25T18:35:00Z",
  "agent_node": "collector",
  "trust_status": "official",
  "validation_status": "accepted",
  "metadata": {}
}
```

### POST `/api/v1/tasks/{task_id}/source-materials`

Add a user-specified URL or evidence item from the intervention drawer.

**Request**:

```json
{
  "source_url": "https://new-source.example/report",
  "competitor": "GPT-4o",
  "reason": "User-added source"
}
```

**Success 202/200**:

```json
{
  "status": "queued",
  "source_id": "src_new_001"
}
```

### POST `/api/v1/tasks/{task_id}/source-materials/{source_id}/refetch`

Back the source drawer's refetch button.

**Success 202/200**:

```json
{
  "status": "refetching",
  "source_id": "src_001"
}
```

### POST `/api/v1/tasks/{task_id}/source-materials/{source_id}/trust`

Back "mark untrusted", "credible", and "suspicious" actions.

**Request**:

```json
{
  "trust_status": "untrusted",
  "reason": "User marked source as unreliable"
}
```

**Success 200**:

```json
{
  "status": "updated",
  "source_id": "src_001",
  "trust_status": "untrusted"
}
```

### POST `/api/v1/tasks/{task_id}/interventions`

Apply source cleanup actions from the intervention drawer.

**Request**:

```json
{
  "remove_source_ids": ["src_001"],
  "restore_noise_ids": ["noise_001"],
  "add_urls": ["https://new-source.example/report"],
  "reason": "Manual data cleanup"
}
```

**Success 200**:

```json
{
  "status": "applied",
  "affected_sources": 2
}
```

### GET `/api/v1/tasks/{task_id}/schema/advice?field_id={field_id}`

Back the schema advice drawer.

**Success 200**:

```json
{
  "field_id": "enterprise.compliance",
  "reason": "Enterprise buyers frequently compare compliance posture.",
  "recommended_queries": ["<competitor> SOC2 compliance"],
  "source_types": ["official", "docs"],
  "examples": ["SOC 2 Type II", "ISO 27001"]
}
```

### POST `/api/v1/tasks/{task_id}/feedback`

Persist claim/source feedback from "credible", "suspicious", and similar
buttons.

**Request**:

```json
{
  "target_type": "analysis_result",
  "target_id": "result_001",
  "feedback": "credible",
  "comment": "Matches official source"
}
```

**Success 200**:

```json
{
  "status": "recorded"
}
```

### POST `/api/v1/tasks/{task_id}/notes`

Persist user notes from analysis views.

**Request**:

```json
{
  "target_type": "competitor",
  "target_id": "GPT-4o",
  "note": "Check enterprise SLA later"
}
```

**Success 200**:

```json
{
  "status": "saved",
  "note_id": "note_001"
}
```

### GET `/api/v1/tasks/{task_id}/report`

Return the final structured report used by `StructuredReport`.

**Success 200**:

```json
{
  "task_id": "task_ab12cd34",
  "report": {
    "summary": "",
    "findings": [],
    "recommendations": [],
    "source_appendix": []
  }
}
```

### GET `/api/v1/tasks/{task_id}/export?format={pdf|markdown|json}`

Back export buttons.

**Success 200**: file response with matching content type.

### POST `/api/v1/tasks/{task_id}/share`

Back share button.

**Success 200**:

```json
{
  "share_url": "http://localhost:3000/share/report_token_001",
  "expires_at": "2026-06-01T00:00:00Z"
}
```

### POST `/api/v1/tasks/{task_id}/verify_links`

Back "verify all links" button.

**Success 200**:

```json
{
  "status": "checked",
  "results": [
    {
      "source_id": "src_001",
      "source_url": "https://example.com",
      "reachable": true
    }
  ]
}
```

## Frontend Action Coverage Matrix

| Frontend action | Required contract |
|-----------------|-------------------|
| New task submit | `POST /api/v1/tasks` |
| Schema save draft | `PUT /api/v1/tasks/{task_id}/schema` |
| Schema confirm/resume | `POST /api/v1/tasks/{task_id}/resume` |
| Schema reject/regenerate | `POST /api/v1/tasks/{task_id}/reject_schema` |
| SSE progress/debug/token/data | `GET /api/v1/tasks/{task_id}/stream` plus persisted events |
| History menu | `GET /api/v1/tasks` |
| Snapshot restore | `GET /snapshots`, `POST /restore_snapshot` |
| Pause collection | `POST /pause` |
| Force next node | `POST /force_next` |
| Source drawer open | `GET /source-materials/{source_id}` |
| Refetch source | `POST /source-materials/{source_id}/refetch` |
| Mark source untrusted | `POST /source-materials/{source_id}/trust` |
| Data intervention add/remove/apply | `GET /source-materials`, `POST /source-materials`, `POST /interventions` |
| Schema advice drawer | `GET /schema/advice` |
| Partial rerun drawer | `POST /partial_rerun` |
| Credible/suspicious feedback | `POST /feedback` |
| Add note | `POST /notes` |
| Report view | `GET /report` or `analysis_progress`/`task_completed` payload report |
| Export PDF/Markdown/JSON | `GET /export?format=...` |
| Share report | `POST /share` |
| Verify all links | `POST /verify_links` |

## SSE Event Payloads

### `task_state_changed`

```json
{
  "sequence": 1,
  "state": "SCHEMA_REVIEW",
  "previous_state": "SCHEMA_GENERATING",
  "progress": 30
}
```

### `schema_ready`

```json
{
  "sequence": 2,
  "dynamic_schema": {},
  "schema_version": 1,
  "stats": {
    "total_fields": 18,
    "user_defined": 3,
    "agent_supplement": 15
  }
}
```

### `raw_materials_updated`

```json
{
  "sequence": 3,
  "data": [
    {
      "id": "src_001",
      "competitor": "GPT-4o",
      "source_url": "https://example.com",
      "quote_text": "quoted evidence",
      "fetch_timestamp": "2026-05-25T18:35:00Z",
      "agent_node": "collector",
      "validation_status": "accepted",
      "trust_status": "third_party"
    }
  ],
  "source_stats": {
    "accepted": 10,
    "degraded": 1,
    "failed": 0,
    "blocked": 0
  }
}
```

### `analysis_progress`

```json
{
  "sequence": 4,
  "module_id": "comparison",
  "data": {
    "comparison": [],
    "swot": {},
    "report": {}
  }
}
```

### `progress_update`

```json
{
  "sequence": 5,
  "progress": 60,
  "stage": "COLLECTING"
}
```

### `debug_log`

```json
{
  "sequence": 6,
  "agent": "Collector",
  "event": "end",
  "message": "Data collection completed",
  "duration_ms": 1200,
  "retry_count": 0,
  "error_class": null
}
```

### `token_update`

```json
{
  "sequence": 7,
  "total_used": 8500,
  "budget": 50000,
  "estimated_remaining": 41500
}
```

### `module_updated`

```json
{
  "sequence": 8,
  "module_id": "swot.threats",
  "new_content": {},
  "updated_at": "2026-05-25T18:45:00Z"
}
```

### `task_failed`

```json
{
  "sequence": 9,
  "state": "ERROR",
  "message": "Model output could not be parsed after retry limit",
  "recoverable": true,
  "next_actions": ["retry_analysis", "manual_intervention"]
}
```

### `task_completed`

```json
{
  "sequence": 10,
  "final_report_url": "/reports/task_ab12cd34",
  "state": "COMPLETED"
}
```
