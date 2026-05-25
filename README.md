# Competitive Analyzer (竞品分析智能 Agent 系统)

本项目是一个基于多 Agent 协作（LangGraph）的“数字调研小组”，通过统一调度（Orchestrator）整合公开数据抓取、大模型深度推导与结构化报告生成。

项目整体包含两部分：
- `backend/`：基于 FastAPI + LangGraph + Playwright + PostgreSQL 的后端服务。
- `frontend/`：基于 Next.js + React 的可视化操作面板。

---

## 🛠️ 一、 前置环境服务依赖

在启动任何项目代码之前，请确保您的本机已经启动并配置了以下服务：

### 1. PostgreSQL 数据库
项目后端状态机和执行快照深度依赖 PostgreSQL，并使用 `asyncpg` 异步驱动。
- 请确保本地已安装并启动 PostgreSQL 服务 (默认端口: `5432`)
- 默认使用的连接账号密码为：用户 `postgres`，密码 `123456`
- **必须**在 PostgreSQL 中提前创建名为 `competitive_analyzer` 的空数据库：
  ```sql
  CREATE DATABASE competitive_analyzer;
  ```
*(注：如果想修改账号密码或数据库名，请在 `backend/models_db.py` 的 `DATABASE_URL` 中修改)*

### 2. DeepSeek 大语言模型 API
项目中 Agent 的规划与分析推理需要使用大模型，默认集成了 `DeepSeek-v4-pro`。
如果您想更改使用的 API Key，请打开 `backend/agents.py` 并修改这一行：
```python
os.environ["DEEPSEEK_API_KEY"] = "您的_DEEPSEEK_API_KEY"
```

---

## 🚀 二、 启动后端服务 (Backend)

后端需要 Python 3.12+ 的环境。请新开一个终端窗口（Terminal）执行以下命令：

**1. 进入后端目录**
```bash
cd backend
```

**2. 创建并激活虚拟环境**
```bash
# Windows 系统:
python -m venv venv
.\venv\Scripts\activate

# Mac/Linux 系统:
python3 -m venv venv
source venv/bin/activate
```

**3. 安装 Python 依赖**
```bash
pip install -r requirements-mock.txt
pip install langchain langchain-openai langgraph playwright beautifulsoup4 psycopg2-binary asyncpg sqlalchemy
```

**4. 初始化 Playwright 无头浏览器环境**
> 用于 Collector Agent 执行真实的网页数据抓取
```bash
playwright install chromium
```

**5. 启动 FastAPI 后端服务**
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
看到 `Application startup complete.` 即代表后端启动成功，并已自动连接至 PostgreSQL 数据库建表。

---

## 🖥️ 三、 启动前端服务 (Frontend)

请另外新开一个终端窗口（Terminal）执行以下命令：

**1. 进入前端目录**
```bash
cd frontend
```

**2. 安装 Node.js 依赖**
```bash
npm install
```

**3. 启动 Next.js 运行环境**
```bash
npm run dev
```
启动成功后，请在浏览器中访问：**[http://localhost:3000](http://localhost:3000)**，即可打开智能竞品分析面板并开始使用！
