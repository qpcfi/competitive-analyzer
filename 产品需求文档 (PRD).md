# 产品需求文档 (PRD)：AI 驱动的竞品分析 Agent 协作系统

## 1. 产品概述

### 1.1 业务背景

企业产品团队在竞品分析中长期面临信息搜集分散、功能对比非标准化、结论溯源困难等痛点。现有流程高度依赖分析人员的个人经验与手工操作，导致产出周期长、信息覆盖率低、结构化一致性差。

### 1.2 产品目标

构建基于多 Agent 协作的“数字调研小组”，通过 Orchestrator（中枢调度）模式整合公开数据泛搜、垂直源精搜、逻辑推导与结构化报告生成。系统将竞品调研过程白盒化，支持业务人员进行细粒度的人工干预与数据溯源。

### 1.3 核心指标预期

- **效率指标**：单次标准竞品分析（3-5 个竞品对象）的耗时从人工的 3-5 天缩短至 2 小时以内。
- **覆盖率指标**：信息源覆盖官网、主流科技资讯、应用商店与公开评测体系。
- **结构化指标**：输出数据 100% 符合系统动态生成的竞品知识 Schema，无格式断层。

### 1.4 产品目标与扩展性定义

- **细分与扩展兼顾**：系统可针对特定细分方向（如特定企业服务软件或全球特定区域产品）进行深度定制分析，但底层架构与 Schema 必须具备高度的可扩展性，支持跨行业、跨领域的无缝切换 。

## 2. 用户角色与系统边界

### 2.1 目标用户群体

- **产品经理 (PM)**：定义竞品对象、核心对比维度；提取产品规划输入。
- **商业分析师 (BA)**：审查 SWOT 推理逻辑；干预并修正动态分析框架（Schema）。
- **用户研究员 (UXR)**：分析用户画像与情感倾向；下钻查阅原始客诉或口碑溯源链路。

### 2.2 系统边界

系统负责全网公开数据的采集、清洗、结构化对齐与推理生成。系统不接入任何未授权的内部商业数据库，所有外部抓取行为受合规策略管控。

## 3. 核心业务流与交互控制

### 3.1 双轨执行工作流

系统支持两种级别的流程控制机制：

| **模式**                        | **运行机制**                                                 | **核心应用场景**                                 |
| ------------------------------- | ------------------------------------------------------------ | ------------------------------------------------ |
| **步进确认模式 (Step-by-Step)** | 在“Schema 生成”与“采集完成”等关键节点阻断运行，强制等待用户审核或修改底层数据，确认无误后方可释放进入下一节点。 | 深度竞品研究；强依赖精确分析框架的高复杂度任务。 |
| **全自动模式 (Auto-Run)**       | 接收初始指令后静默执行至全流程结束。期间保留各节点的 State 快照，用户可在报告生成后进行历史节点的回溯与局部重跑。 | 行业概览；快速摸底调研。                         |

### 3.2 人工介入与节点打回操作

- **Schema 定义层**：支持用户增删分析维度（如增加“API 开放能力”对比）、修改字段类型。
- **数据底座层**：支持用户手动剔除低质量 URL 或结构化表单中的噪音数据，支持定向追加指定 URL 让系统补录。
- **分析推理层**：支持在 Web 看板内框选特定推导结论，输入修改指令触发局部模块重跑。

## 4. 多 Agent 架构与状态流转

### 4.1 Orchestrator 核心调度架构

系统摒弃静态串行流水线，采用基于 LangGraph 的 Orchestrator (规划中枢) 架构，包含 4 个专职 Agent：

1. **Orchestrator Agent (规划中枢)**：
   - 意图识别与任务拆解。
   - 动态生成行业适配的竞品 Schema。
   - 控制 State Graph 的全局路由流转。
2. **Collector Agent (采集执行器)**：
   - 接收明确抓取指令（URL 或特定搜索词）。
   - 执行网页解析、信息抽取与格式清洗。
3. **Analyzer Agent (分析生成器)**：
   - 执行交叉对比与 SWOT 逻辑推导。
   - 输出符合 Web 看板渲染规范的最终结构化 JSON。
4. **Critic Agent (质检评估器)**：
   - 审查逻辑一致性与事实支撑度。
   - 输出结构化的修正意见与补录需求反馈给 Orchestrator。

### 4.2 全局共享状态 (State Graph)

Agent 间通信使用标准化状态空间传递数据，核心结构如下：

- `task_context`: 用户初始指令与目标对象。
- `dynamic_schema`: 当前生效的结构化字段标准。
- `raw_materials`: 带溯源标签的基础数据块。
- `critic_feedback`: 质检打回的错误定位与建议。

## 5. 漏斗式双层质检闭环

保障输出可信度与控制算力成本的核心机制：

### 5.1 L1 强规则校验 (代码阻断)

- **执行节点**：Collector Agent 输出后，进入 State Graph 汇总前。
- **校验逻辑**：纯代码正则/类型判空校验。检查关键维度是否缺失、是否有绑定有效的 `source_url`。
- **处置策略**：未通过则直接抛出异常类型，系统自动打回 Collector 触发重试，不消耗 LLM 算力。

### 5.2 L2 语义校验 (LLM 质检)

- **执行节点**：Analyzer Agent 阶段性输出后。
- **校验逻辑**：Critic Agent 判断结论是否具有足够的数据支撑，是否存在模型幻觉。
- **处置策略**：发现断层则通过 Function Calling 记录缺陷状态至 `critic_feedback`，由 Orchestrator 调度 Analyzer 重新推理或调度 Collector 补充搜寻。

## 6. Web 分析看板需求 (前端交互)

### 6.1 动态大纲与可视化渲染

- **大纲导航**：左侧悬浮呈现结构化目录（功能树、定价策略、SWOT），支持锚点双向绑定。
- **组件化渲染**：解析 Analyzer 产出的 JSON，将功能对比数据渲染为雷达图/对比表格，将情感偏好渲染为分布图。

### 6.2 细粒度数据溯源 (Traceability)

- 报告内的每一条结论、数据引用必须携带可视化溯源标识。
- 点击标识触发侧边栏 (Drawer) 展示完整证据链：
  - 原文数据切片 (Quote)
  - 外链跳转入口 (Source URL)
  - 数据获取时间戳与负责节点

### 6.3 局部模块重执行

- 单个分析模块（如 SWOT 的“威胁”象限）提供干预入口。
- 修改请求仅传递该模块的子 State 与新 Prompt，实现业务流的局部唤醒与页面组件的无刷新重载。

## 7. 非功能需求与工程标准

### 7.1 可观测性与日志大盘

- **调试模式**：Web 看板内置 Debug 开关，开启后模块底部展开任务流转详情。
- **日志字段**：
  - 包含具体节点的执行耗时、状态 (Running/Success/Failed)。
  - 完整展示底层交互的 System Prompt、Context 及消耗的 Token 预估。
  - 提供输入输出 JSON 的 Raw Data 折叠视图。
- **Agent Trace 追踪**：全面集成 `LangSmith` 等监控组件。不仅在前端提供 Debug 视图，系统后台需持续收集和记录每个 Agent 的决策执行路径 (Trace)、底层 Prompt 交互及数据调用链，保障系统“决策回放”功能的完整性与输出结论的权威性 。  

### 7.2 性能容错与降级机制

- **超时重试**：外部网络请求与 LLM API 采取阶梯式超时退避策略，最大重试阈值设定为 3 次。
- **超长文本处理**：针对超过单次 Token 限制的长文本（如深度研报），强制触发分片 (Chunking) 提取再合并机制。
- **自动降级**：非核心 URL 抓取失败触发系统降级，该字段标记为“信息缺失”并继续流转主干任务，防止全局阻塞。

### 7.3 合规与隐私安全

- **抓取合规**：Collector Agent 强制校验目标站点的 `robots.txt` 协议，系统留存合规拦截日志。
- **数据脱敏**：任何用户真实文本（含 PII 个人身份信息，如电话、邮箱），进入大模型处理前必须在本地执行正则替换与匿名化清洗。







## 全链路运行交互时序图

```Mermaid
sequenceDiagram
    autonumber
    actor User as Web 前端 (Next.js)
    participant BFF as Next.js API Routes (BFF)
    participant API as FastAPI 后端
    participant DB as PostgreSQL (状态与数据持久化)
    participant Orchestrator as 规划中枢 (LangGraph)
    participant Agents as 底层执行 Agent 集群

    %% 阶段 1：任务初始化与 SSE 通道建立
    rect rgb(240, 248, 255)
    Note over User, Agents: 阶段 1：任务初始化与流式订阅
    User->>BFF: 提交竞品分析指令 (分析对象/行业)
    BFF->>API: POST /api/v1/tasks (初始化任务)
    API->>DB: 初始化任务记录与初始 State
    DB-->>API: 返回 Task ID
    API-->>BFF: 返回 Task ID
    BFF-->>User: 任务创建成功 (Task ID)
    User->>BFF: 建立 SSE 连接 (GET /events/{task_id})
    BFF->>API: 转发 SSE 请求，监听事件流
    end

    %% 阶段 2：动态 Schema 构建与人工干预
    rect rgb(255, 250, 240)
    Note over API, Agents: 阶段 2：规划调度与人工阻断
    API->>Orchestrator: 唤醒图执行 (传入初始 State)
    Orchestrator->>Agents: 调度大模型提取动态 Schema
    Agents-->>Orchestrator: 返回初版 Schema
    Orchestrator->>DB: Checkpoint 持久化 (状态挂起)
    Orchestrator-->>API: 触发 Schema_Ready 事件
    API-->>User: [SSE 推送] 展示初版 Schema，等待确认
    User->>BFF: 修改并确认 Schema (放行节点)
    BFF->>API: POST /api/v1/tasks/{id}/resume
    API->>Orchestrator: 恢复执行流转
    end

    %% 阶段 3：定向采集与 L1 规则质检
    rect rgb(240, 255, 240)
    Note over API, Agents: 阶段 3：定向采集与代码层拦截
    Orchestrator->>Agents: 分发定向采集任务 (Collector)
    loop 网页抓取与解析
        Agents->>Agents: 抓取、脱敏、信息抽取
        Agents-->>API: [SSE 推送] Log: Token消耗 / 当前抓取URL
    end
    Agents->>Orchestrator: 提交结构化底座数据
    Orchestrator->>Orchestrator: L1 强规则校验 (判空/URL校验)
    alt L1 校验未通过
        Orchestrator->>Agents: 规则阻断，直接打回重试
    else L1 校验通过
        Orchestrator->>DB: 保存溯源数据快照 (Raw Materials)
    end
    end

    %% 阶段 4：推理分析与 L2 语义质检闭环
    rect rgb(255, 240, 245)
    Note over API, Agents: 阶段 4：推理推导与反幻觉打回
    Orchestrator->>Agents: 分发分析任务 (Analyzer)
    Agents->>Agents: 交叉对比、SWOT 推理
    Agents-->>API: [SSE 推送] Log: 推理进度与阶段结论
    Agents->>Orchestrator: 提交分析报告草稿 JSON
    Orchestrator->>Agents: 调度质检任务 (Critic)
    Agents->>Agents: L2 语义校验 (证据链/幻觉核查)
    alt L2 发现逻辑缺陷
        Agents-->>Orchestrator: 写入 Critic Feedback，要求重试
        Orchestrator->>Agents: 根据反馈重定向至 Collector 或 Analyzer
    else L2 校验通过
        Agents-->>Orchestrator: 质检放行
    end
    end

    %% 阶段 5：任务结束与前端渲染
    rect rgb(245, 245, 255)
    Note over User, DB: 阶段 5：状态完结与最终渲染
    Orchestrator->>DB: 更新最终 State 与报告结构数据
    Orchestrator-->>API: 触发 Task_Completed 事件
    API-->>User: [SSE 推送] 任务完成，返回全量 JSON 结果
    API->>BFF: 关闭 SSE 流
    User->>User: 前端渲染动态大纲、可溯源图表与看板组件
    end
```

**核心交互节点说明：**

1. **异步任务流**：前端不阻塞等待长耗时任务，获取 Task ID 后通过 SSE 监听状态。
2. **状态机挂起（Checkpointing）**：在阶段 2 中，LangGraph 的状态机在生成 Schema 后自动挂起，等待 `resume` 接口的外部触发，实现了非阻塞的人工确认逻辑。
3. **事件透传机制**：底层的日志（如 Token 消耗、当前正在执行的 Agent、抓取的 URL）均通过图节点的 hook 或回调，由 FastAPI 转化为 SSE 数据块，实时透传至前端进行状态可视化。
4. **内部闭环对前端透明**：阶段 3 和阶段 4 中的 L1/L2 循环打回在后端 LangGraph 引擎内部闭环完成，前端仅接收状态变更的 SSE 通知（如“质检未通过，重新采集中”），无需处理重试逻辑。