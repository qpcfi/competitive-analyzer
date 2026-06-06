# Plan: 爬虫增强 + 搜索引擎扩展

**Complexity**: Medium

## Summary

两个方向：(A) Crawl4ai 爬虫增强 — 并发、重试、反检测、SPA 等待；(B) 搜索引擎扩展 — 引入七牛云百度搜索、Brave Search 等补充国内站点覆盖。两者独立可并行。

## 搜索引擎调研

| API | 价格/千次 | 免费额度 | 中文支持 | AI 友好 | 现状 |
|---|---|---|---|---|---|
| **Tavily** | ~$8 | 1000次/月 | ✅ 中英文兼顾 | ★★★★★ | ✅ 已集成 |
| **七牛云百度搜索** | 按 Token 计费 | 300万 Token | ★★★★★ 中文最强 | ★★★★ | 百度索引，国内内容不可替代 |
| **Brave Search** | ~$5 | $5/月 | ⚠️ 英文为主 | ★★★★ | 独立索引，中文偏弱 |
| **Exa** | ~$7 | 1000次/月 | ⚠️ 英文为主 | ★★★★★ | 语义搜索准确率最高 |
| **Serper** | ~$1 | 2500次一次性 | ⚠️ 依赖Google | ★★★★ | 最便宜，仅摘要需额外爬虫 |
| **DuckDuckGo** | 免费 | 无限制 | ✅ 中英文兼顾 | ★★★ | ✅ 已集成（兜底） |

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| 搜索引擎函数 | `web_search.py:131-158` | `search_tavily()` — 可选 Key + 异常静默降级 |
| 多引擎聚合 | `web_search.py:163-194` | `search_multi_engine()` — 并行 gather + URL 去重 |
| 爬虫配置 | `crawler.py:61-81` | BrowserConfig + CrawlerRunConfig 模式 |
| 事件日志 | `collector/node.py:75` | 关键步骤 publish `debug_log` |

## Tasks

### Task A1: Crawl4ai 并发爬取

- **Action**: `crawl_urls()` 串行遍历改为 `asyncio.gather` 批量并发，加 `max_concurrent` 参数控制并发数（默认 5）
- **Mirror**: `crawler.py:74` 现有 `for url in urls` 串行模式
- **Validate**: 启动后端跑 task，观察日志中爬取耗时对比

### Task A2: 重试机制

- **Action**: 爬取失败 URL 加入重试队列，指数退避（1s → 3s → 9s），最多 3 次。仅重试网络类异常（超时、连接重置），4xx 不重试
- **Mirror**: `collector/node.py:135-137` 现有重试模式
- **Validate**: 停掉网络后启动，确认爬取日志显示重试序列

### Task A3: 浏览器指纹与反检测

- **Action**: `BrowserConfig` 加随机 User-Agent 池（预置 10+ 常见头）、`viewport`、`platform`。对 SPA 站点配置 `wait_until="networkidle"` + `scan_full_page`
- **Files**: `agents/shared/crawler.py`
- **Validate**: 爬取知乎/企查查等页面确认动态内容渲染完整

### Task B1: 七牛云百度搜索

- **Action**:
  1. 注册七牛云账号获取 API Key
  2. 新增 `search_qiniu_baidu(query, limit=5)` — 读 `QINIU_API_KEY`，异常静默降级
  3. 集成到 `search_multi_engine()` 中，优先级排在Tavily之后、DDG之前
- **Files**: `services/web_search.py`, `.env`/`.env.example`, `requirements.txt`
- **Validate**: 配 Key 后搜索中文竞品名称，确认返回百度来源结果

### Task B2: Brave Search（可选）

- **Action**:
  1. 新增 `search_brave(query, limit=5)` — 读 `BRAVE_API_KEY`
  2. 集成到 `search_multi_engine()` 中
- **Files**: `services/web_search.py`, `.env`/`.env.example`
- **Validate**: 配 Key 后搜索英文技术关键词确认返回结果
- **Note**: 中文覆盖弱，优先级低于七牛云

## 依赖关系

```
Task A1 (并发爬取) ─── 独立
Task A2 (重试)     ─── 建议在 A1 之后
Task A3 (反检测)   ─── 独立（可并行）
Task B1 (七牛云)   ─── 独立
Task B2 (Brave)   ─── 独立（可选）
```

## Validation

```bash
# 单元测试
python -m pytest tests/unit/test_search_multi_engine.py -v

# 启动验证
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| 七牛云百度搜索 API 变更 | Medium | 异常降级，不影响主流程 |
| 并发爬取触发目标站点反爬 | Medium | `max_concurrent` 可配 + 指数退避 + Proxy |
| Brave 中文结果质量低 | Low | 可配 `include_domains` 限定技术站点 |
| Crawl4ai 版本升级不兼容 | Low | 锁版本在 requirements.txt |

## Acceptance

- [ ] 并发爬取耗时显著降低（3+ URL 同时抓取）
- [ ] 失败 URL 自动重试（日志可见重试序列）
- [ ] SPA 站点动态内容渲染完整
- [ ] 七牛云百度搜索返回百度来源中文结果
- [ ] 所有搜索引擎异常降级不导致 task 失败
