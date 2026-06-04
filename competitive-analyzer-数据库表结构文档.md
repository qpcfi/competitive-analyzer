# Competitive Analyzer 数据库表结构文档

> 数据库：PostgreSQL | ORM：SQLAlchemy (async) | 定义文件：`backend/models_db.py`

---

## 1. tasks（任务表）

核心业务表，存储每次竞争分析任务的完整生命周期数据。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | VARCHAR | 是 | - | 主键，任务唯一标识 |
| `task_name` | VARCHAR | 是 | - | 任务显示名称 |
| `domain` | VARCHAR | 是 | - | 分析领域（如 SaaS、电商、金融等） |
| `main_product` | VARCHAR | 否 | - | 被分析的主产品名称 |
| `competitors` | JSON | 是 | `[]` | 竞争对手名称列表 |
| `execution_mode` | VARCHAR | 是 | - | 执行模式：`step_by_step`（逐步执行）或 `auto`（全自动） |
| `state` | VARCHAR | 是 | - | 任务状态（见下方状态枚举） |
| `progress` | INTEGER | 是 | `0` | 任务进度百分比，范围 0-100 |
| `current_checkpoint_id` | VARCHAR | 否 | - | 当前检查点ID，用于任务恢复/重放 |
| `owner_id` | VARCHAR | 否 | - | 任务创建者标识 |
| `error` | JSON | 否 | - | 错误详情（仅在 ERROR 状态时有值） |
| `dynamic_schema` | JSON | 是 | `{}` | 当前生效的动态模式（字段定义） |
| `raw_materials` | JSON | 是 | `[]` | 采集到的原始资料汇总 |
| `analysis_results` | JSON | 是 | `{}` | 各模块分析输出结果汇总 |
| `critic_feedback` | JSON | 是 | `[]` | 质量评审反馈记录 |
| `final_report` | JSON | 是 | `{}` | 最终生成的竞争分析报告 |
| `created_at` | TIMESTAMP | 是 | - | 任务创建时间 |
| `updated_at` | TIMESTAMP | 是 | `now()` | 最后更新时间 |
| `completed_at` | TIMESTAMP | 否 | - | 任务完成时间（COMPLETED 状态时填充） |

**状态枚举（`TaskState`）**：

| 状态值 | 说明 |
|---|---|
| `INITIALIZING` | 初始化中 |
| `SCHEMA_GENERATING` | 正在生成分析模式/字段定义 |
| `SCHEMA_REVIEW` | 等待用户确认模式 |
| `COLLECTING` | 正在采集数据 |
| `ANALYZING` | 正在分析数据 |
| `QUALITY_REVIEW` | 质量评审中 |
| `COMPLETED` | 已完成 |
| `ERROR` | 发生错误 |
| `PAUSED` | 已暂停 |
| `NEEDS_INTERVENTION` | 需要人工干预 |

---

## 2. dynamic_schemas（动态模式版本表）

存储分析模式的版本历史，支持模式的迭代演进和回退。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | VARCHAR | 是 | - | 主键 |
| `task_id` | VARCHAR | 是 | - | 外键，关联 `tasks.id` |
| `version` | INTEGER | 是 | `1` | 模式版本号，自增 |
| `status` | VARCHAR | 是 | `draft` | 模式状态：`draft`（草稿）、`active`（生效中） |
| `schema_json` | JSON | 是 | `{}` | 模式字段定义（字段名、类型、描述等） |
| `field_index` | JSON | 是 | `[]` | 字段排序/索引，控制前端展示顺序 |
| `created_by` | VARCHAR | 是 | `agent` | 创建者：`agent`（AI生成）或 `user`（用户创建） |
| `created_at` | TIMESTAMP | 是 | `now()` | 创建时间 |
| `updated_at` | TIMESTAMP | 是 | `now()` | 最后修改时间 |

---

## 3. source_materials（源资料表）

存储 Collector 模块从各渠道采集的原始数据，每行对应一条信息来源。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | VARCHAR | 是 | - | 主键 |
| `task_id` | VARCHAR | 是 | - | 外键，关联 `tasks.id` |
| `schema_field_id` | VARCHAR | 否 | - | 对应模式中的字段ID，表示此资料服务于哪个分析维度 |
| `competitor` | VARCHAR | 是 | - | 该资料对应的竞争对手名称 |
| `source_url` | TEXT | 否 | - | 来源URL（网页采集时使用） |
| `source_type` | VARCHAR | 是 | `unknown` | 来源类型：`web`、`api`、`manual` 等 |
| `quote_text` | TEXT | 是 | `""` | 从来源中提取的引用原文 |
| `extracted_value` | JSON | 否 | - | 从原文中解析出的结构化数据 |
| `fetch_timestamp` | TIMESTAMP | 是 | `now()` | 数据采集时间 |
| `agent_node` | VARCHAR | 是 | `collector` | 创建此记录的 agent 节点名称 |
| `access_status` | VARCHAR | 是 | `not_checked` | 链接可访问性：`not_checked`、`accessible`、`blocked` |
| `validation_status` | VARCHAR | 是 | `pending` | 验证状态：`pending`、`valid`、`invalid` |
| `trust_status` | VARCHAR | 是 | `third_party` | 可信度评级：`official`（官方）、`third_party`（第三方）、`inferred`（推断）、`untrusted`（不可信）、`degraded`（已降级） |
| `retry_count` | INTEGER | 是 | `0` | 采集重试次数 |
| `degraded_reason` | TEXT | 否 | - | 降级原因说明（trust_status 为 degraded 时填充） |
| `pii_redacted` | BOOLEAN | 是 | `false` | 是否已对敏感个人信息做脱敏处理 |
| `is_noise` | BOOLEAN | 是 | `false` | 是否标记为噪音数据（不相关的内容） |

---

## 4. analysis_results（分析结果表）

存储 Analyzer 各模块的分析输出，支持同一模块多版本（重做）。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | VARCHAR | 是 | - | 主键 |
| `task_id` | VARCHAR | 是 | - | 外键，关联 `tasks.id` |
| `module_id` | VARCHAR | 是 | - | 分析模块标识（如 `analysis`、`swot` 等） |
| `module_type` | VARCHAR | 是 | - | 模块类型/类别 |
| `version` | INTEGER | 是 | `1` | 结果版本号（同一模块多次分析时递增） |
| `content` | JSON | 是 | `{}` | 分析输出内容（结构化数据） |
| `evidence_refs` | JSON | 是 | `[]` | 引用的源材料ID列表，用于证据溯源 |
| `quality_status` | VARCHAR | 是 | `pending` | 质量评审状态：`pending`、`passed`、`failed` |
| `created_at` | TIMESTAMP | 是 | `now()` | 创建时间 |
| `updated_at` | TIMESTAMP | 是 | `now()` | 最后修改时间 |

---

## 5. quality_feedback（质量反馈表）

存储 Critic 评审模块产生的质量检查反馈，驱动自动修复和重试逻辑。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | VARCHAR | 是 | - | 主键 |
| `task_id` | VARCHAR | 是 | - | 外键，关联 `tasks.id` |
| `level` | VARCHAR | 是 | - | 反馈级别：`L1`（格式校验）、`L2`（内容质量）、`L3`（业务逻辑） |
| `target_type` | VARCHAR | 是 | - | 被评审的目标类型（如 `analysis_result`） |
| `target_id` | VARCHAR | 是 | - | 被评审的目标记录ID |
| `module_id` | VARCHAR | 否 | - | 产生此反馈的评审模块ID |
| `severity` | VARCHAR | 是 | `warning` | 严重程度：`warning`（警告）或 `error`（错误） |
| `code` | VARCHAR | 是 | - | 机器可读的反馈代码（用于程序化处理） |
| `message` | TEXT | 是 | - | 人类可读的反馈描述 |
| `suggested_action` | VARCHAR | 是 | - | 建议处理动作：`retry_collection`（重新采集）、`retry_analysis`（重新分析）、`extend_schema`（扩展模式）、`human_review`（人工审核） |
| `retry_count` | INTEGER | 是 | `0` | 针对此反馈的重试次数 |
| `resolved` | BOOLEAN | 是 | `false` | 是否已解决 |
| `created_at` | TIMESTAMP | 是 | `now()` | 创建时间 |
| `resolved_at` | TIMESTAMP | 否 | - | 解决时间 |

---

## 6. task_events（任务事件日志表）

存储任务执行过程中的所有事件，用于前端实时状态推送和调试。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | INTEGER | 是 | 自增 | 主键，自增整数 |
| `task_id` | VARCHAR | 是 | - | 外键，关联 `tasks.id` |
| `sequence` | INTEGER | 是 | - | 事件序号，用于保证事件有序消费 |
| `event_type` | VARCHAR | 是 | - | 事件类型：`state_change`（状态变更）、`debug_log`（调试日志）、`token_update`（Token消耗更新）等 |
| `payload` | JSON | 是 | `{}` | 事件数据载荷 |
| `created_at` | TIMESTAMP | 是 | `now()` | 事件创建时间 |

---

## 7. intervention_logs（人工干预日志表）

记录人工对任务执行的干预操作，用于审计追溯。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | VARCHAR | 是 | - | 主键 |
| `task_id` | VARCHAR | 是 | - | 外键，关联 `tasks.id` |
| `action_type` | VARCHAR | 是 | - | 干预类型：`remove_source`（移除来源）、`restore_noise`（恢复噪音数据）、`add_url`（添加URL）等 |
| `payload` | JSON | 是 | `{}` | 干预操作的参数/数据 |
| `actor_id` | VARCHAR | 否 | - | 执行干预的用户或 agent 标识 |
| `created_at` | TIMESTAMP | 是 | `now()` | 干预操作时间 |

---

## 8. task_snapshots（任务快照表）

存储任务的完整状态快照，用于检查点和断点续跑。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | VARCHAR | 是 | - | 主键 |
| `task_id` | VARCHAR | 是 | - | 外键，关联 `tasks.id` |
| `checkpoint_id` | VARCHAR | 是 | - | 检查点标识，与 `tasks.current_checkpoint_id` 对应 |
| `state` | VARCHAR | 是 | - | 快照时的任务状态 |
| `summary` | TEXT | 是 | - | 快照内容的人类可读摘要 |
| `snapshot_data` | JSON | 是 | `{}` | 完整任务状态数据（含 schema、materials、results 等） |
| `created_at` | TIMESTAMP | 是 | `now()` | 快照创建时间 |

---

## 9. user_feedback（用户反馈表）

存储用户对分析结果或报告的评价反馈。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | VARCHAR | 是 | - | 主键 |
| `task_id` | VARCHAR | 是 | - | 外键，关联 `tasks.id` |
| `target_type` | VARCHAR | 是 | - | 反馈目标类型（如 `analysis`、`report`） |
| `target_id` | VARCHAR | 是 | - | 反馈目标记录ID |
| `feedback` | VARCHAR | 是 | - | 反馈值：`positive`（好评）、`negative`（差评）等 |
| `comment` | TEXT | 否 | - | 可选的文字评论 |
| `actor_id` | VARCHAR | 否 | - | 提供反馈的用户标识 |
| `created_at` | TIMESTAMP | 是 | `now()` | 反馈创建时间 |

---

## 10. user_notes（用户笔记表）

存储用户对任务/分析/报告的批注笔记。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | VARCHAR | 是 | - | 主键 |
| `task_id` | VARCHAR | 是 | - | 外键，关联 `tasks.id` |
| `target_type` | VARCHAR | 是 | - | 笔记关联的目标类型 |
| `target_id` | VARCHAR | 是 | - | 笔记关联的目标记录ID |
| `note` | TEXT | 是 | - | 笔记文本内容 |
| `actor_id` | VARCHAR | 否 | - | 笔记作者标识 |
| `created_at` | TIMESTAMP | 是 | `now()` | 创建时间 |
| `updated_at` | TIMESTAMP | 是 | `now()` | 最后修改时间 |

---

## 11. report_exports（报告导出表）

存储最终报告的导出记录，支持多种格式和临时分享。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | VARCHAR | 是 | - | 主键 |
| `task_id` | VARCHAR | 是 | - | 外键，关联 `tasks.id` |
| `format` | VARCHAR | 是 | - | 导出格式：`pdf`、`html`、`json`、`markdown` |
| `status` | VARCHAR | 是 | `pending` | 导出状态：`pending`、`completed`、`failed` |
| `file_path` | TEXT | 否 | - | 导出文件在服务器上的存储路径 |
| `share_token` | VARCHAR | 否 | - | 公开分享令牌，用于生成分享链接 |
| `expires_at` | TIMESTAMP | 否 | - | 分享链接过期时间 |
| `created_at` | TIMESTAMP | 是 | `now()` | 导出记录创建时间 |

---

## 12. link_verification_results（链接验证结果表）

存储对采集来源链接的可达性验证结果。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | VARCHAR | 是 | - | 主键 |
| `task_id` | VARCHAR | 是 | - | 外键，关联 `tasks.id` |
| `source_material_id` | VARCHAR | 否 | - | 关联的源材料ID（对应 `source_materials.id`） |
| `source_url` | TEXT | 是 | - | 被验证的URL |
| `reachable` | BOOLEAN | 是 | `false` | URL 是否可访问 |
| `status_code` | INTEGER | 否 | - | HTTP 响应状态码 |
| `checked_at` | TIMESTAMP | 是 | `now()` | 验证时间 |
| `error` | TEXT | 否 | - | 验证失败时的错误信息 |

---

## 表关系概览

```
tasks (核心表)
├── dynamic_schemas        (1:N)  模式版本历史
├── source_materials       (1:N)  采集源资料
├── analysis_results       (1:N)  分析结果
├── quality_feedback       (1:N)  质量反馈
├── task_events            (1:N)  事件日志
├── intervention_logs      (1:N)  干预记录
├── task_snapshots         (1:N)  状态快照
├── user_feedback          (1:N)  用户反馈
├── user_notes             (1:N)  用户笔记
├── report_exports         (1:N)  报告导出
└── link_verification_results (1:N) 链接验证
```

所有子表均通过 `task_id` 外键关联到 `tasks.id`，形成以任务为中心的星型数据模型。
