# Code Wiki

桌面应用，自动扫描本地代码仓库，借助 LLM 生成结构化 Wiki 文档，支持代码浏览、知识图谱、依赖分析、语义搜索和智能问答。

## 快速开始

### 前置依赖

- Python 3.10+
- Node.js 18+
- pnpm
- Rust (Tauri 编译需要)
- [可选] 本地 LLM (Ollama) 或 DeepSeek/OpenAI API Key

### 启动

```bash
# 后端 (终端 1)
cd backend
pip install -r requirements.txt
python main.py
# → http://127.0.0.1:8000

# 前端 + Tauri (终端 2)
cd code-wiki-frontend
pnpm install
npm run tauri dev
# → http://localhost:3000
```

前端也可以脱离 Tauri 在浏览器开发：

```bash
cd code-wiki-frontend && pnpm dev
# → http://localhost:3000 (Vite 代理 API 到 localhost:8000)
```

### 使用

1. 设置页 → 配置仓库路径和 LLM API
2. 分析页 → 点击「扫描分析」，等待完成
3. 在 Wiki / Code / 图谱页浏览分析结果

## 功能

| 功能 | 说明 |
|------|------|
| 🔍 **多语言扫描** | Python (AST) + TypeScript/JavaScript (regex) 静态分析 |
| 📄 **Wiki 生成** | LLM 为每个模块生成结构化 Markdown 文档，带源码锚点 |
| 📊 **知识图谱** | Cytoscape.js 交互式依赖图，5 种布局，搜索/缩放 |
| 🏗 **架构图** | Mermaid 自动生成架构图、类图、时序图 |
| 🔗 **源码跳转** | Wiki 中的 `[@src:path:line]` 可点击打开编辑器 |
| 💬 **智能问答** | 基于最新 Wiki + AST chunk 的 RAG 问答 (SSE 流式) |
| 🔄 **增量更新** | 文件变更后自动重新分析受影响的模块 |
| 🌳 **调用链分析** | 静态调用图 (call graph) |
| 📈 **代码指标** | 模块复杂度、数据流分析、影响范围评估 |
| 🔎 **语义搜索** | 跨模块代码搜索 (code search) |
| 🗺 **Schema 浏览** | 项目数据模型可视化 |
| 🗂 **文件管理** | 新建/重命名/删除，变更自动同步 |

## 架构

```
┌─ Tauri Desktop Shell (Rust) ──────────────────────────────┐
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐            │
│  │ 文件监听  │  │ 窗口管理  │  │ IPC (读文件)  │            │
│  └──────────┘  └──────────┘  └──────────────┘            │
│                                                           │
│  ┌───────────────────────────────────────────────────┐   │
│  │              React Frontend (TypeScript)           │   │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌────────┐  │   │
│  │  │ Code │ │ Wiki │ │ 图谱 │ │ 分析 │ │ 设置   │  │   │
│  │  └──────┘ └──────┘ └──────┘ └──────┘ └────────┘  │   │
│  └───────────────────────────────────────────────────┘   │
│                         │ HTTP / IPC                      │
│  ┌───────────────────────────────────────────────────┐   │
│  │              FastAPI Backend (Python)              │   │
│  │  Scanner → Analyzer → DependencyGraph → LLM Wiki  │   │
│  │                    ↓                               │   │
│  │  AST Chunker → FAISS + BM25 → RAG Chat            │   │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

## 技术栈

| 层 | 技术 |
|------|------|
| 桌面壳 | Tauri v2 (Rust) |
| 前端 | React 19 + TypeScript + Tailwind CSS 4 + shadcn/ui |
| 状态管理 | Zustand 5 |
| 代码编辑器 | Monaco Editor |
| 知识图谱 | Cytoscape.js |
| 图表 | Mermaid 11 |
| 后端 | FastAPI (Python 3.10+) |
| 分析 | Python AST + ts-morph (TypeScript) |
| LLM | DeepSeek API / OpenAI 兼容 |
| 向量检索 | FAISS (HNSW) + BM25 混合检索 + RRF 融合 |
| 重排序 | Cross-Encoder (FlagEmbedding) |

## API

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/scan` | 触发分析 |
| `POST` | `/api/scan/cancel` | 取消分析 |
| `GET` | `/api/status` | 分析进度 |
| `GET` | `/api/config` | 获取配置 |
| `PUT` | `/api/config` | 更新配置 |
| `GET` | `/api/wiki/tree` | Wiki 文件树 |
| `GET` | `/api/wiki/{path}` | Wiki 内容 |
| `GET` | `/api/files` | 文件树 |
| `GET` | `/api/files/content` | 文件内容 |
| `GET` | `/api/diagrams/architecture` | 架构图 (Mermaid) |
| `GET` | `/api/diagrams/classes` | 类图 |
| `GET` | `/api/diagrams/sequence/{fqn}` | 时序图 |
| `GET` | `/api/graph/data` | 知识图谱数据 |
| `POST` | `/api/chat` | 智能问答 (SSE) |
| `POST` | `/api/llm/test` | LLM 连接测试 |
| `GET` | `/api/events` | SSE 事件流 |
| `GET` | `/api/metrics/{path}` | 模块指标 |
| `GET` | `/api/impact/{path}` | 影响分析 |
| `GET` | `/api/search` | 代码搜索 |
| `GET` | `/api/schema` | 数据模型 |
| `GET` | `/api/guide` | 功能引导 |

## 项目结构

```
code-wiki/
├── backend/
│   ├── main.py                   # FastAPI 入口
│   ├── config.py                 # 全局配置
│   ├── models/entities.py        # 数据模型
│   ├── services/
│   │   ├── scanner.py            # 文件扫描
│   │   ├── analyzer.py           # Python AST 分析
│   │   ├── ts_analyzer.py        # TypeScript 分析
│   │   ├── tree_sitter_parser.py # Tree-sitter 增强解析
│   │   ├── dependency_graph.py   # 依赖图
│   │   ├── call_graph.py         # 调用图
│   │   ├── data_flow.py          # 数据流分析
│   │   ├── impact_analyzer.py    # 影响范围评估
│   │   ├── embedder.py           # 向量嵌入 & 检索
│   │   ├── embedding_client.py   # Embedding API 客户端
│   │   ├── ast_chunker.py        # AST 粒度分块
│   │   ├── hybrid_search.py      # BM25 + 余弦混合检索
│   │   ├── code_search.py        # 语义代码搜索
│   │   ├── search.py             # 关键词分词器
│   │   ├── reranker.py           # Cross-Encoder 重排序
│   │   ├── vector_store_faiss.py # FAISS 向量存储
│   │   ├── chat_service.py       # RAG 问答
│   │   ├── langchain_chat.py     # LangChain LCEL 问答
│   │   ├── knowledge_graph.py    # 知识图谱构建
│   │   ├── health_metrics.py     # 健康指标
│   │   ├── mermaid_utils.py      # Mermaid 清洗工具
│   │   ├── watcher.py            # 文件监听
│   │   └── wiki/                 # Wiki 生成子包
│   │       ├── generator.py      # 编排器
│   │       ├── prompt_builder.py # Prompt 构造
│   │       ├── llm_service.py    # LLM API
│   │       ├── markdown_builder.py
│   │       ├── wiki_state.py
│   │       └── wiki_writer.py
│   └── routes/
│       ├── scan.py               # 分析触发
│       ├── wiki.py               # Wiki 内容
│       ├── diagrams.py           # Mermaid 图表
│       ├── graph.py              # 知识图谱
│       ├── chat.py               # 问答
│       ├── files.py              # 文件管理
│       ├── config.py             # 配置
│       ├── metrics.py            # 代码指标
│       ├── schema.py             # Schema 浏览
│       ├── search.py → code_search
│       ├── guide.py              # 功能引导
│       ├── tour.py               # 新手教程
│       ├── health.py             # 健康检查
│       ├── llm_test.py           # LLM 连接测试
│       ├── events.py             # SSE 事件
│       ├── status.py             # 分析状态
│       └── watcher.py            # 文件监听控制
├── code-wiki-frontend/
│   └── src/
│       ├── components/
│       │   ├── layout/           # AppShell, TopBar, LeftNav, StatusBar
│       │   ├── code/             # CodePanel, CodeViewer
│       │   ├── wiki/             # WikiPanel, SourceLink
│       │   ├── analysis/         # 扫描配置
│       │   ├── settings/         # 设置表单
│       │   ├── chat/             # ChatDrawer, ChatPanel
│       │   ├── graph/            # KnowledgeGraph (Cytoscape)
│       │   ├── metrics/          # MetricsPanel, CFGPanel, ImpactPanel
│       │   ├── schema/           # SchemaPanel
│       │   ├── guide/            # GuidePanel
│       │   └── shared/           # MermaidRenderer, StatusBadge
│       ├── store/configStore.ts  # Zustand 全局状态
│       ├── lib/types.ts          # 类型定义
│       └── lib/utils.ts          # 工具函数
├── scripts/
│   └── check.sh                  # 快速编译检查
├── README.md
├── IMPLEMENTATION.md
└── REQUIREMENTS.md
```

## 开发

```bash
# 快速编译检查
bash scripts/check.sh

# 后端热重载
cd backend && uvicorn main:app --reload --host 127.0.0.1 --port 8000

# 前端热重载
cd code-wiki-frontend && pnpm dev
```

## License

MIT
