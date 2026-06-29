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

前端开发服务器默认运行在 `http://localhost:5173`。

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
│   │   ├── wiki_generator.py     # Wiki 生成（LLM）
│   │   ├── embedder.py           # 向量嵌入
│   │   └── chat_service.py       # 聊天/RAG 服务
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
| 向量检索 | ChromaDB |

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
