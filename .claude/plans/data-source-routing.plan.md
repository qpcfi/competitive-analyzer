# Plan: 路由 skill 筛选 + 数据源扩展

**Complexity**: Medium

## Summary

两个独立任务：(A) 路由库加 skill 维度筛选；(B) Stage 2 搜索层扩展多引擎。评估结论：`SourceMaterialRecord` 加 `skill` 字段即可满足持久化需求，不新建表。

## 搜索引擎调研结论

| API | 价格/千次 | 免费额度 | 中文支持 | AI 友好 | 现状 |
|---|---|---|---|---|---|
| **Tavily** | ~$8 | 1000次/月 | ✅ 中英文兼顾 | ★★★★★ | AI Agent 生态最成熟，推荐首选 |
| Brave Search | ~$5 | $5/月 | ⚠️ 英文为主 | ★★★★ | 独立索引，中文偏弱 |
| Exa | ~$7 | 1000次/月 | ⚠️ 英文为主 | ★★★★★ | 语义搜索准确率最高 |
| Serper | ~$1 | 2500次一次性 | ⚠️ 依赖Google | ★★★★ | 最便宜，但仅摘要，需额外爬虫 |
| SerpAPI | ~$15 | 250次/月 | ⚠️ 依赖Google | ★★★ | 已被 Google 起诉 |
| Bing Search API | — | — | — | — | **已退役**（2025.8） |

**选用策略（你的场景 → 中文竞品分析）**：
1. **Tavily** — 主力搜索引擎，AI Agent 原生，中英文兼顾
2. **DuckDuckGo** — 兜底，不依赖 API key

## SourceMaterialRecord 评估

`source_materials` 表已有字段完全覆盖搜索爬取结果的持久化需求：

| 需求 | 已有字段 | 是否满足 |
|---|---|---|
| 区分采集阶段 | `source_stage` ("curated" / "search") | 符合 |
| 区分内容维度 | 无 | **需加 `skill` 字段** |
| 存原始内容 | `quote_text` (Text) | 符合 |
| 存提取结果 | `extracted_value` (JSON) | 符合 |
| 存储状态 | `access_status` / `validation_status` | 符合 |
| 关联任务 | `task_id` (FK) | 符合 |
| 关联查询 | `schema_field_id` / `competitor` | 符合 |

**结论**：`SourceMaterialRecord` + 加一个 `skill VARCHAR` 列即可，不改现有 API、不新建表、不影响前端 sources 页面。

**B2 澄清**：Stage 1（knowledge_base 路由筛选+爬取）和 Stage 2（搜索引擎+爬取）都走同一套 collector 流程，最终都调 `save_source_materials`。`knowledge_base.yaml` 的 curated URLs 提取结果同样写入 source_materials，同样带 `skill` 字段。共用 `source_stage` 区分（"curated" vs "search"）。

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| 数据库模型 | `models_db.py:53-73` | `SourceMaterialRecord` 列风格 |
| 仓储函数 | `repositories.py:194-225` | `save_source_materials` 批量 insert |
| 路由回退 | `router.py:103-106` | LLM/API 异常时 graceful fallback |
| 测试 mock | `tests/unit/test_web_search.py:58-83` | `httpx.MockTransport` mock 搜索 |
| 事件日志 | `collector/node.py:75` | 关键步骤 publish `debug_log` |
| 迁移 | `models_db.py:189-207` | `ALTER TABLE ADD COLUMN IF NOT EXISTS` 模式 |

## Files to Change

| File | Action | Why |
|---|---|---|
| `agents/shared/knowledge_base.yaml` | UPDATE | 每个 source 加 `skills` 标签 |
| `agents/shared/router.py` | UPDATE | `route_sources` 加 `skill_filter` 参数 |
| `models_db.py` | UPDATE | `SourceMaterialRecord` 加 `skill` 列 + ALTER TABLE |
| `services/repositories.py` | UPDATE | `save_source_materials` 写入 `skill` 字段 |
| `services/web_search.py` | UPDATE | 加 `search_tavily()`，合并为 `search_multi_engine()` |
| `agents/collector/node.py` | UPDATE | 路由传 skill；多引擎搜索 |
| `tests/unit/test_router_skill.py` | CREATE | 路由 skill 过滤测试 |
| `tests/unit/test_search_multi_engine.py` | CREATE | 多引擎搜索 + fallback 测试 |

## Tasks

### Task A1: knowledge_base.yaml + router.py skill 筛选

- **Action**:
  1. `knowledge_base.yaml`: 每个 source 加 `skills` 字段（如 `skills: ["company"]` 或 `skills: ["business", "technical"]`），缺失视为所有维度
  2. # `router.py`: `route_sources(domain, competitor, skill_filter=None)` 当传入 skill_filter 时只返回匹配的 sources。`skill_filter` 同时传给 LLM 软过滤 prompt
  3. `collector/node.py`: `route_sources(domain, competitor, skill_filter)` 传入当前 skill
- **Mirror**: `router.py:38-48` 竞品名硬过滤模式
- **Validate**: `python -m pytest tests/unit/test_router_skill.py -v`

### Task A2: SourceMaterialRecord 加 skill 字段

- **Action**:
  1. `models_db.py:SourceMaterialRecord` 加 `skill = Column(String, nullable=True)`
  2. `init_db()` 加 `ALTER TABLE source_materials ADD COLUMN IF NOT EXISTS skill VARCHAR`
  3. `repositories.py:save_source_materials` 从 material dict 中读 `skill` 字段写入
  4. collector/node.py 返回的 material dict 带 `skill` 值
- **Mirror**: `models_db.py:207` 现有 `ADD COLUMN IF NOT EXISTS` 迁移模式
- **Validate**: 启动后端确认日志无报错

### Task B1: web_search.py 加多引擎 ✅

- **Changes**:
  1. `services/web_search.py` 新增 `search_tavily()` — 读 `TAVILY_API_KEY`，异常静默返回空列表
  2. 新增 `search_multi_engine()` — 并行运行 Tavily + DuckDuckGo，URL 去重，Tavily 优先
  3. Tavily 客户端模块级懒初始化，无 Key 或无包时安全降级 DDG-only
- **Files**: `services/web_search.py`, `.env`/`.env.example`, `requirements.txt`
- **Note**: Brave 等搜索引擎扩展已移至 `crawler-search-enhance.plan.md`

### Task B2: collector/discoverer 集成 ✅

- **Changes**:
  1. `agents/collector/node.py` — 后备搜索 `search_public_web` → `search_multi_engine`
  2. `agents/discoverer/node.py` — 竞品发现搜索同步升级
  3. `scripts/diagnose_discovery.py` — 诊断脚本同步更新
- **Files**: `agents/collector/node.py`, `agents/discoverer/node.py`, `scripts/diagnose_discovery.py`
- **Note**: 多引擎返回统一 `SearchResult` 格式，下游 (Crawl4ai → LLM 提取) 零改动

### Task 5: 测试

- **Action**:
  1. `test_router_skill.py` — 按 skill 过滤、无 skills 全量返回、LLM 失败回退
  2. `test_search_multi_engine.py` — Tavily 正常/Tavily 失败降 DDG/双引擎全降返回空
- **Mirror**: `tests/unit/test_web_search.py` mock 风格
- **Validate**: `python -m pytest tests/unit/test_router_skill.py tests/unit/test_search_multi_engine.py -v`

## 依赖关系

```
Task A1 (路由skill) ─── 独立
Task A2 (DB加skill) ─── 独立（仅后端，不阻塞 B1）
Task B1 (多引擎)    ─── 独立
Task B2 (collector集成) ← 依赖 A1 + A2 + B1
Task 5 (测试)       ─── A1/B1 完成后可并行写
```

实现顺序建议：A1 + B1 同时开工 → T5 测试 → A2（简单，随时可插）→ B2（最后集成）

## Validation

```bash
# 单元测试
python -m pytest tests/unit/test_router_skill.py tests/unit/test_search_multi_engine.py -v

# 现有测试不回归
python -m pytest tests/unit/ -v

# 启动验证
cd backend && source venv/Scripts/activate && uvicorn main:app --host 0.0.0.0 --port 8000
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Tavily API key 未配置 | Medium | `search_tavily` 异常静默降 DuckDuckGo，零中断 |
| `save_source_materials` 新 `skill` 字段旧数据为 NULL | Low | 字段可空，现有查询兼容 NULL |
| 搜索结果质量在中国区仍不佳 | Medium | 后续可加 Brave 或其他引擎补国内内容 |

## Acceptance

- [ ] `knowledge_base.yaml` 有 sources 标注了 `skills` 标签
- [ ] `route_sources("AI", "千问", "technical")` 只返回 technical 源的 URL
- [ ] `SourceMaterialRecord` 有 `skill` 列，curated 和 search 两种来源保存时都写入
- [ ] Tavily 可用时优先用，不可用自动降 DuckDuckGo
- [ ] 同竞品同 skill 的多个 field 共享搜索结果缓存
- [ ] 所有现有单元测试通过
