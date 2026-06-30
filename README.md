# Code Wiki

一款桌面应用，能自动扫描本地代码仓库，借助 LLM 生成结构化的 Wiki 文档（.md），支持源码双向跳转、文件变更自动更新以及基于最新 Wiki 的智能问答。

## 快速开始

### 前置依赖

- Python 3.10+
- Node.js 18+
- pnpm
- [可选] 本地 LLM（Ollama）或 OpenAI API Key

### 启动后端

```bash
cd backend
pip install -r requirements.txt
python main.py
```

后端默认运行在 `http://127.0.0.1:8788`。

### 启动前端

```bash
cd code-wiki-frontend
pnpm install
pnpm dev
```

前端开发服务器默认运行在 `http://localhost:1420`。

### 使用

1. 打开前端页面，进入「设置」页面
2. 配置仓库路径和 LLM API（本地 Ollama 或 OpenAI）
3. 回到「分析」页面，点击「扫描分析」
4. 分析完成后，在「Wiki」页面查看自动生成的文档和类图

## 功能特性

| 功能 | 说明 |
|---|---|
| 🔍 代码扫描 | 扫描本地仓库，识别模块、类、方法和依赖关系 |
| 📄 Wiki 生成 | 借助 LLM 为每个模块生成结构化文档（Markdown） |
| 📊 Mermaid 图表 | 自动生成架构图、类图、时序图，支持全屏 + 缩放/平移 |
| 🔗 源码跳转 | Wiki 文档中的引用可点击跳转到对应源码位置 |
| 💬 智能问答 | 基于最新 Wiki 内容的 RAG 问答（支持 @ 引用模块） |
| 🔄 增量更新 | 文件变更后自动重新分析受影响的模块 |
| 🗂 文件管理 | 新建、重命名、删除文件，变更自动同步到 Wiki |

## 原理

### 1. 静态代码分析原理

Code Wiki 的核心是从源代码中提取结构化信息，这一过程基于**抽象语法树（AST）**分析：

```
源码文件 → 词法分析 → 语法分析 → AST → 遍历抽取 → ModuleInfo（结构化模型）
```

- **Python 分析**：使用 Python 内置 `ast` 模块解析 `.py` 文件，提取模块 docstring、类定义（含方法签名、装饰器、继承关系）、顶级函数、导入关系（内部/外部）、源码行号锚点。对语法错误的文件返回最小化 ModuleInfo，保证流水线不中断。
- **TypeScript/JavaScript 分析**：通过 `ts-morph` 库（TypeScript Compiler API 的封装）解析 `.ts/.tsx/.js/.jsx` 文件，提取接口、类型别名、枚举等 TS 特有的语言构造。两类语言的输出统一为相同的 `ModuleInfo` 数据模型。
- **依赖图构建**：从导入语句中提取模块间依赖关系，构建有向依赖图，用于增量更新时确定受影响的模块集合。

所有分析结果被序列化为统一的 `ModuleInfo` 和 `ClassInfo` / `FunctionInfo` 数据类，供后续 Wiki 生成和向量索引阶段使用。

### 2. LLM 文档生成原理

生成阶段将结构化代码摘要转化为人类可读的 Markdown 文档，采用**角色感知提示工程（Role-Aware Prompt Engineering）**：

```
ModuleInfo → PromptBuilder（构造 system + user prompt）→ LLM API → Markdown → WikiPage
```

- **PromptBuilder**：根据实体类型（模块、类、函数）选择不同的 prompt 模板，注入结构化摘要作为上下文。v2 版本还加入了**跨模块上下文注入**——将依赖模块的摘要一并送入 prompt，使 LLM 能写出模块间的关系描述。
- **LLMService**：封装 API 调用，支持重试（指数退避）、速率限制、流式/非流式两种模式。默认使用 DeepSeek 模型，兼容 OpenAI API 协议，可切换至本地 Ollama。
- **MarkdownBuilder**：在 LLM 调用失败时提供降级方案——基于结构模板生成无 AI 内容的纯结构化 Markdown，保证 Wiki 始终可用。
- **WikiWriter + WikiState**：将生成的 Markdown 写入 `.code-wiki/` 目录，并维护 `state.json` 记录每个模块的生成时间戳和版本，支持增量更新。

关键规则：所有文档使用中文撰写（全项目统一）；每个实体标注 `[@src:路径:行号]` 源码锚点支持前端跳转；以 `_` 开头的私有成员只列名称不展开描述。

### 3. 混合检索原理（RAG）

问答系统采用**混合检索 + 重排序（Hybrid Search + Reranking）** 架构，兼顾关键词匹配的精确性与语义检索的泛化能力：

```
用户提问 → 嵌入向量化 + BM25 关键词检索 → Top-K 候选 → RRF 融合排序 → Reranker → Top-5 → Prompt 构造 → LLM 生成
```

- **文档分块**：支持两种索引模式：
  - **AST 分块（v2 新方案）**：按函数/类/方法为粒度，将 `ModuleInfo` 切分为语义独立的 AST Chunk，每个 chunk 包含代码签名 + 文档字符串，保留源码锚点。
  - **Markdown 分块（向后兼容）**：将生成的 Wiki 页面按 `##` 标题切分为段落级 chunk。
- **向量嵌入**：通过 DeepSeek Embedding API 将 chunk 转为高维稠密向量，存入 FAISS 向量索引（取代旧版 ChromaDB/JSON 存储）。
- **BM25 关键词检索**：对 chunk 文本建立 BM25 倒排索引，作为语义检索的互补——对专有名词（类名、函数名）匹配效果更佳。
- **RRF 融合排序（Reciprocal Rank Fusion）**：将向量余弦相似度排名和 BM25 排名按 `RRF score = 1 / (k + rank)` 融合，取 Top-20 候选。
- **Cross-Encoder 重排序（可选）**：对 Top-20 候选使用 cross-encoder 模型做细粒度相关性判定，输出 Top-5。
- **Prompt 构造**：将 Top-5 片段拼入 system prompt，要求 LLM **仅基于 Wiki 内容回答**，引用格式为 `[src:path:line]`，不编造信息。
- **流式输出**：通过 SSE（Server-Sent Events）逐 token 流式返回 LLM 生成结果。

### 4. 增量更新原理

当仓库文件发生变更时，Code Wiki 通过**依赖图分析 + 标记-清理（Mark-and-Sweep）**策略实现最小化更新：

```
文件变更事件 → 识别变更模块 → 依赖图反向追踪 → 标记受影响模块 → 重新分析 + 重新生成 Wiki → 更新向量索引
```

- **文件监听**：后端通过文件系统 watcher 监听仓库目录变更（新建/修改/删除/重命名）。
- **影响范围计算**：从依赖图中反向遍历所有引用变更模块的模块，得到需要重新分析的最小集合。
- **状态持久化**：`WikiState` 维护每个模块的生成时间戳和校验和，避免重复生成未变更的模块。
- **增量索引**：Embedder 仅对变更模块的旧 chunk 进行失效标记，新增/更新 chunk 的向量，无需重建全量索引。

### 5. 跨语言分析架构

系统通过**策略模式（Strategy Pattern）**统一处理多语言分析：

```
Analyzer.analyze_file(rel_path)
  ├─ 扩展名 .py     → PythonAnalyzer（ast 模块）
  ├─ 扩展名 .ts/.tsx → TypeScriptAnalyzer（ts-morph）
  └─ 扩展名 .js/.jsx → TypeScriptAnalyzer（ts-morph）
```

所有分析器输出相同的 `ModuleInfo` / `ClassInfo` / `FunctionInfo` 数据模型，后续的 Wiki 生成、向量索引、RAG 检索完全与语言无关。添加新语言支持只需实现对应的分析器适配器。

## 项目结构

```
code-wiki/
├── backend/                      # FastAPI 后端
│   ├── main.py                   # 应用入口
│   ├── config.py                 # 全局配置
│   ├── models/entities.py        # 数据模型
│   ├── services/
│   │   ├── scanner.py            # 文件扫描器
│   │   ├── analyzer.py           # Python AST 分析器
│   │   ├── ts_analyzer.py        # TypeScript 分析器
│   │   ├── dependency_graph.py   # 依赖图构建
│   │   ├── embedder.py           # 向量嵌入（FAISS + BM25）
│   │   ├── ast_chunker.py        # AST 粒度分块
│   │   ├── hybrid_search.py      # 混合检索（RRF 融合）
│   │   └── wiki/                 # Wiki 生成子包
│   │       ├── generator.py      # Wiki 生成编排
│   │       ├── prompt_builder.py # Prompt 构造
│   │       ├── llm_service.py    # LLM API 调用
│   │       └── markdown_builder.py # Markdown 生成
│   └── routes/
│       ├── scan.py               # 扫描 API
│       ├── wiki.py               # Wiki 内容 API
│       ├── diagrams.py           # Mermaid 图表 API
│       ├── config.py             # 配置 API
│       └── files.py              # 文件管理 API
├── code-wiki-frontend/           # React 前端
│   └── src/
│       ├── components/
│       │   ├── layout/           # AppShell, TopBar, LeftNav, StatusBar
│       │   ├── wiki/             # WikiPanel, SourceLink, Mermaid 图表
│       │   ├── code/             # CodePanel (Monaco 编辑器)
│       │   ├── analysis/         # AnalysisPanel (扫描配置)
│       │   ├── settings/         # SettingsPanel
│       │   ├── chat/             # Chat 面板
│       │   └── shared/           # MermaidRenderer, StatusBadge
│       ├── store/configStore.ts  # Zustand 全局状态
│       ├── lib/types.ts          # TypeScript 类型
│       └── styles/globals.css    # Tailwind + shadcn/ui 主题
├── IMPLEMENTATION.md             # 技术实现文档
├── REQUIREMENTS.md               # 需求规格说明书
└── README.md                     # 本文件
```

## 技术栈

| 层 | 技术 |
|---|---|
| 前端框架 | React 19 + TypeScript |
| 构建工具 | Vite 8 |
| 样式 | Tailwind CSS 4 + shadcn/ui |
| 状态管理 | Zustand 5 |
| 编辑器 | Monaco Editor |
| 图表 | Mermaid 11 |
| 桌面壳 | Tauri 2 |
| 后端框架 | FastAPI (Python) |
| 代码分析 | AST (Python) + ts-morph (TypeScript) |
| LLM 集成 | Ollama / OpenAI API |
| 向量检索 | FAISS (HNSW) + BM25 |

## API 概览

| 端点 | 说明 |
|---|---|
| `POST /api/scan` | 触发全量/增量扫描 |
| `GET /api/analysis/status` | 获取分析进度（SSE） |
| `GET /api/wiki/tree` | Wiki 文件树 |
| `GET /api/wiki/content/{path}` | Wiki 页面内容 |
| `GET /api/diagrams/classes` | 类图（Mermaid） |
| `GET /api/diagrams/architecture` | 架构图（Mermaid） |
| `GET /api/diagrams/sequence/{path}` | 时序图（Mermaid） |
| `POST /api/chat` | 智能问答 |
| `POST /api/config` | 更新配置 |
| `GET /api/files/list` | 文件列表 |
| `POST /api/files/save` | 保存文件 |

## 配置

通过前端设置页或直接编辑 `config.yaml`：

```yaml
repo_path: /path/to/your/repo
llm:
  provider: ollama  # 或 openai
  model: qwen2.5-coder:7b
  base_url: http://localhost:11434
excludes:
  - node_modules
  - .git
  - __pycache__
```

## 开发

```bash
# 后端热重载
cd backend && uvicorn main:app --reload --host 127.0.0.1 --port 8788

# 前端热重载
cd code-wiki-frontend && pnpm dev

# 桌面端（Tauri）
cd code-wiki-frontend && pnpm tauri dev
```

## License

MIT
