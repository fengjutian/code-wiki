# Code Wiki — 需求规格说明书 v3

> **一句话定位**：Code Wiki 是一款桌面应用，能自动扫描本地代码仓库，借助 LLM 生成结构化的 Wiki 文档（.md），支持源码双向跳转、文件变更自动更新以及基于最新 Wiki 的智能问答。

---

## 目录

1. [核心需求概述](#1-核心需求概述)
2. [前端页面布局](#2-前端页面布局)
3. [文件排除规则](#3-文件排除规则)
4. [分析模式：全量 / 部分](#4-分析模式全量--部分)
5. [Wiki 本地持久化](#5-wiki-本地持久化)
6. [设置页详细设计](#6-设置页详细设计)
7. [系统架构](#7-系统架构)
8. [技术栈](#8-技术栈)
9. [API 设计](#9-api-设计)
10. [项目结构](#10-项目结构)
11. [MVP 实施计划](#11-mvp-实施计划)
12. [验收标准](#12-验收标准)
13. [非 MVP 范围](#13-非-mvp-范围)

---

## 1. 核心需求概述

本需求的四个核心关注点：

| # | 需求 | 要点 |
|---|------|------|
| 1 | **前端布局** | 左侧垂直导航栏（Code → Wiki → 设置），右侧主内容区，顶栏 + 底栏状态条 |
| 2 | **文件排除** | 默认排除 + 自定义 glob 规则 + 右键排除，排除的文件不参与分析 |
| 3 | **分析模式** | 全部分析（整个仓库）或 部分分析（用户选定文件/目录） |
| 4 | **Wiki 持久化** | 分析结果保存为 `.md` 到项目 `.code-wiki/` 目录，重新分析时覆盖更新 |

---

## 2. 前端页面布局

### 2.1 整体框架

```
┌──────────────────────────────────────────────────────────┐
│  Code Wiki                              [🌙 主题] [⚙]  │  ← 顶栏 (TopBar)
├────────────┬─────────────────────────────────────────────┤
│            │                                             │
│  ┌──────┐  │                                             │
│  │ Code │  │         主内容区                             │
│  ├──────┤  │   (代码浏览 / Wiki 浏览 / 设置表单)           │
│  │ Wiki │  │                                             │
│  ├──────┤  │                                    ┌──────┐ │
│  │ 设置  │  │                                    │ Chat │ │  ← 右侧抽屉（始终可访问）
│  └──────┘  │                                    └──────┘ │
│            │                                             │
│  左侧导航   │                                             │
│  垂直 Tab   │                                             │
│            │                                             │
├────────────┴─────────────────────────────────────────────┤
│  ✅ Wiki 已是最新  |  上次更新: 2026-06-26 16:30          │  ← 状态栏 (StatusBar)
└──────────────────────────────────────────────────────────┘
```

### 2.2 左侧导航栏（LeftNav）

左侧为**垂直 Tab 导航**，从上到下依次为：

#### 2.2.1 Tab 1 — Code（代码浏览）

- **文件树**：展示仓库目录结构（树形组件）
- **搜索框**：顶部支持文件名模糊搜索
- **状态图标**：每个文件前显示分析状态
  - ✅ 已分析
  - ⏳ 未分析
  - 🔄 分析中
- **排除标记**：被排除的文件/目录 → 灰显 + 删除线
- **右键菜单**：
  - 「排除此文件 / 目录」
  - 「分析此文件」
  - 「取消排除」
- **多选支持**：Ctrl/Cmd + 点击多选文件
- **点击行为**：选中文件 → 主内容区展示代码（语法高亮）

#### 2.2.2 Tab 2 — Wiki（文档浏览）

- **Wiki 页面列表**：以树形结构镜像源码目录，展示所有 `.md` Wiki 文件
- **点击行为**：选中 → 主内容区渲染 Markdown
- **源码锚点链接**：Wiki 中的 `[@src:path:line]` 渲染为可点击的 `[→]` 链接
- **图表区域**（Tab 切换）：
  - 架构图（模块依赖图，Mermaid `graph TD`）
  - 类图（类继承关系，Mermaid `classDiagram`）
  - 时序图（函数调用链，Mermaid `sequenceDiagram`）
- **搜索 Wiki**：顶部搜索框支持 Wiki 内容全文搜索

#### 2.2.3 Tab 3 — 设置

进入设置主面板，包含所有配置区域（详见 [第 6 节](#6-设置页详细设计)）。

### 2.3 顶栏（TopBar）

- **应用标题**："Code Wiki"
- **主题切换按钮**：快捷切换亮色/暗色（☀️/🌙 图标）
- **设置齿轮**：等同于点击左侧「设置」Tab
- **分析状态指示器**：显示当前分析进度（idle / 分析中 60% / ✅ 完成）

### 2.4 状态栏（StatusBar）

- Wiki 最新状态：✅ 最新 / ⚠️ 有变更未更新 / 🔄 分析中
- 上次更新时间
- 分析的实体数量（模块数 / 类数 / 函数数）
- LLM 模型信息（当前使用的模型名称）

### 2.5 Chat 面板（右侧抽屉）

始终可从右侧滑出，不随左侧 Tab 切换消失：

- **输入框**：用户提问
- **消息列表**：对话历史，支持流式输出（SSE）
- **引用来源**：回答中 `[src:path:line]` 渲染为可点击跳转链接
- **上下文**：仅基于 Chroma 检索到的 Wiki chunk，不直接读取源码
- **关闭/打开**：按钮切换，不影响主内容区

### 2.6 交互细节

| 交互 | 行为 |
|------|------|
| 左侧 Tab 切换 | 主内容区切换对应内容 |
| 主题切换 | 即时生效，无需刷新 |
| Chat 抽屉 | 独立于左侧 Tab，可随时呼出/关闭 |
| 文件树右键 | 弹出上下文菜单 |
| 源码链接点击 | 调用系统编辑器打开文件并跳转到指定行 |
| 窗口尺寸 | 最小 1024×680，可自由缩放 |
| 响应式 | MVP 阶段仅支持桌面端，不处理移动端 |

---

## 3. 文件排除规则

### 3.1 排除规则体系

文件排除规则由三层合并而成，按优先级从高到低：

```
① 硬编码排除（不可修改）
   └── .code-wiki/    ← 避免循环分析自身产物

② 默认排除（可取消）
   └── __pycache__/   .git/   node_modules/   .venv/
       dist/           build/  *.pyc

③ 用户自定义排除（设置页自由增删）
   └── glob 模式，例如：*.test.py  migrations/*  tests/
```

### 3.2 排除规则的配置方式

#### 方式一：设置页编辑

- 在设置的「仓库配置」区域，一个**多行文本输入框**
- 每行一个 glob 模式
- 预填充默认排除项（可删除/修改）
- 保存后即时生效，下次分析时应用

#### 方式二：文件树右键菜单

- 在 Code Tab 文件树中，右键文件或目录
- 选择「排除此文件」或「排除此目录」
- 自动将对应 glob 规则追加到设置中
- 文件树即时更新为灰显+删除线

### 3.3 排除规则存储

```
.code-wiki/config.json
{
  "exclude_patterns": [
    "__pycache__/",
    ".git/",
    "node_modules/",
    ".venv/",
    "dist/",
    "build/",
    "*.pyc",
    "*.test.py"       // 用户自定义
  ]
}
```

- 保存在项目 `.code-wiki/config.json` 中
- 可随 `.git` 提交到团队仓库，团队成员共享排除规则
- 与 `.gitignore` 语义一致但独立管理

### 3.4 排除规则的行为

| 行为 | 说明 |
|------|------|
| 扫描阶段 | 被排除的文件不在文件树中展示（或灰显标记） |
| 分析阶段 | 被排除的文件不送入 AST 分析器 |
| Wiki 生成 | 被排除的文件不生成 Wiki 页面 |
| 文件监听 | 被排除目录的变更不触发增量分析 |
| 重新分析 | 被排除的文件对应的旧 Wiki 页面会被清理 |

---

## 4. 分析模式：全量 / 部分

### 4.1 两种分析模式

| 模式 | 触发入口 | 行为 |
|------|----------|------|
| **全部分析** | 设置页 → 点击「开始分析」 | 扫描仓库所有非排除文件，生成完整 Wiki |
| **部分分析** | Code Tab 选中文件 → 右键 →「分析选中」 | 仅分析选中的文件/目录，增量更新 Wiki |

### 4.2 全部分析流程

```
用户点击「开始分析」（设置页）
  → Scanner 扫描仓库文件树
  → 应用排除规则 + .gitignore 规则
  → 收集所有 .py 文件列表
  → Analyzer 逐个 AST 解析
  → Wiki Generator 调用 DeepSeek 生成 .md
  → 写入 .code-wiki/ （全量覆盖）
  → Chroma 重新向量化
  → SSE 推送进度 → 前端更新状态
```

### 4.3 部分分析流程

```
用户在 Code Tab 文件树中多选文件/目录
  → 右键 → 「分析选中」
  → Scanner 仅收集选中文件
  → Analyzer 分析选中文件 + 受影响的依赖文件
  → Wiki Generator 仅重写受影响页面的 .md
  → 局部更新 .code-wiki/ 对应文件
  → Chroma 增量更新向量索引
  → SSE 推送进度 → 前端更新状态
```

### 4.4 分析模式 UI 设计

#### 设置页中的分析控制区

```
┌─────────────────────────────────────────┐
│  分析设置                                │
│                                         │
│  ○ 全部分析  （分析整个仓库）             │
│  ○ 部分分析  （选择指定文件/目录分析）     │
│                                         │
│  [选择文件] 已选: services/user.py ...   │  ← 部分分析时可用
│                                         │
│  ┌─────────────────────────┐  85%      │
│  │ ████████████████████░░░ │           │  ← 进度条
│  └─────────────────────────┘           │
│  状态: 正在生成 Wiki...  模块 12/15     │  ← 实时状态
│                                         │
│  [开始分析]  [取消]                     │
└─────────────────────────────────────────┘
```

#### Code Tab 中的部分分析

```
文件树中 Ctrl/Cmd + 点击多选文件
  → 右键菜单:
    ├── 📊 分析选中文件
    ├── 🚫 排除此文件
    └── 📋 复制路径
```

### 4.5 增量分析（文件监听自动触发）

- **触发条件**：文件变更（修改/新增/删除）
- **防抖**：500ms 内的多次变更合并为一次
- **范围**：仅分析变更文件 + 受影响的依赖（如 import 了变更模块的文件）
- **更新**：局部覆盖 `.code-wiki/` 中受影响的 .md 文件
- **状态推送**：SSE 事件 → 前端状态栏更新

---

## 5. Wiki 本地持久化

### 5.1 存储位置

```
<repo_root>/
└── .code-wiki/
    ├── config.json          # 用户配置（排除规则、LLM 设置等）
    ├── state.json           # 分析状态元数据
    ├── index.md             # 架构概览（项目概述 + 模块依赖图）
    ├── modules/
    │   ├── services/
    │   │   ├── user.md      # 对应 services/user.py
    │   │   └── auth.md      # 对应 services/auth.py
    │   └── models/
    │       └── user.md      # 对应 models/user.py
    └── chroma/              # Chroma 向量数据库文件
```

### 5.2 覆盖策略

| 场景 | 行为 |
|------|------|
| **首次分析** | 创建 `.code-wiki/` 目录，写入所有 Wiki 文件 |
| **全量重新分析** | **全覆盖**所有 .md 文件 + Chroma 索引；`config.json` 和 `state.json` 不覆盖（更新 time/hash 字段） |
| **部分分析** | **局部覆盖**仅受影响的 .md 文件 + 增量更新 Chroma |
| **增量分析** | **局部覆盖**仅变更文件对应的 .md + 增量更新 Chroma |

### 5.3 文件格式

#### Wiki 页面（.md）示例

```markdown
# services/user.py

> 源码: `services/user.py` | 最后分析: 2026-06-26 16:30

## 模块概述

UserService 是用户管理的核心服务模块，负责用户认证、注册和个人资料管理
[@src:services/user.py:1]。

## 类

### UserService

用户服务类，继承自 `BaseService` [@src:services/user.py:15]。

**方法：**

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `authenticate` | `username: str, password: str` | `User \| None` | 用户认证 [@src:services/user.py:22] |
| `register` | `data: UserCreate` | `User` | 新用户注册 [@src:services/user.py:45] |
| `get_profile` | `user_id: int` | `UserProfile` | 获取用户资料 [@src:services/user.py:68] |

## 依赖

- `models.user` — User, UserCreate, UserProfile 数据模型
- `utils.crypto` — 密码哈希/验证

---

*由 Code Wiki 自动生成 · DeepSeek-V4-Flash*
```

#### state.json 示例

```json
{
  "last_analysis": "2026-06-26T16:30:00+08:00",
  "mode": "full",
  "total_modules": 15,
  "total_classes": 42,
  "total_functions": 128,
  "file_hashes": {
    "services/user.py": "a1b2c3d4...",
    "models/user.py": "e5f6g7h8..."
  },
  "excluded_count": 8,
  "llm_model": "deepseek-v4-flash",
  "wiki_version": "3"
}
```

### 5.4 重新分析时 .md 的处理

- **全量覆盖**：所有 Wiki .md 文件删除后重新生成（config.json 除外）
- **增量更新**：仅重写变更文件对应的 .md
- **孤立清理**：源码文件被删除后，对应的 .md 也会被清理
- **用户不会丢失数据**：重新分析不会清空用户配置

### 5.5 Wiki 文件的生命周期

```
源码存在 + 已分析  →  .md 存在
源码修改          →  重新分析 → .md 覆盖更新
源码删除          →  .md 自动清理
文件被排除        →  对应 .md 被清理
用户手动删除 .md  →  下次分析时重新生成
```

---

## 6. 设置页详细设计

设置页整合所有配置项，左侧「设置」Tab 选中后主内容区展示。

### 6.1 区域一：仓库配置

| 配置项 | 组件 | 说明 |
|--------|------|------|
| 仓库路径 | 文本输入框 + 「浏览」按钮 | 调用系统文件夹选择对话框 |
| 排除规则 | 多行文本输入框 | 每行一个 glob，默认预填排除项 |
| 当前状态 | 只读文本 | 显示上次分析时间、实体数量等 |

### 6.2 区域二：LLM 配置

| 配置项 | 组件 | 默认值 | 说明 |
|--------|------|--------|------|
| API Key | 密码输入框（可切换显示） | 空 | 必填，否则无法使用 LLM |
| 模型选择 | 下拉框 | `deepseek-v4-flash` | Flash（快/便宜）或 Pro（强/贵） |
| API Base URL | 文本输入框 | `https://api.deepseek.com` | 兼容 OpenAI 协议 |
| Temperature | 滑块（0.0–1.0） | 0.3 | 较低以保持一致性 |
| 连接测试 | 「测试连接」按钮 | — | 调用 API 验证 Key 有效性 |

### 6.3 区域三：主题切换

| 选项 | 说明 |
|------|------|
| ☀️ 亮色 | 强制亮色模式 |
| 🌙 暗色 | 强制暗色模式 |
| 💻 跟随系统 | 根据操作系统设置自动切换 |

实现方式：TailwindCSS `dark:` 前缀 + CSS 变量，切换即时生效无需刷新。

### 6.4 区域四：分析设置

- 分析模式选择（全部分析 / 部分分析）
- 部分分析时的文件选择器
- 「开始分析」按钮
- 实时进度条 + 状态文字
- 「取消分析」按钮

### 6.5 区域五：关于

- 应用名称 + 版本号
- 技术栈信息
- 开源协议（MIT）
- GitHub 仓库链接

### 6.6 配置的存储安全

| 配置类型 | 存储位置 | 安全性 |
|----------|----------|--------|
| API Key | Tauri Store（系统加密） | 🔒 加密，不入 Git |
| LLM 模型/温度 | `.code-wiki/config.json` | 📄 明文，可提交 Git |
| 排除规则 | `.code-wiki/config.json` | 📄 明文，可提交 Git |
| 主题偏好 | Tauri Store / localStorage | 🔒 本地存储 |

---

## 7. 系统架构

### 7.1 架构分层

```
┌──────────────────────────────────────────────────────┐
│                 Tauri Desktop App                     │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │            React Frontend (UI Layer)            │  │
│  │  LeftNav | Code | Wiki | Settings | Chat       │  │
│  └──────────────────┬─────────────────────────────┘  │
│                     │ HTTP (localhost:8787)           │
│  ┌──────────────────┴─────────────────────────────┐  │
│  │         Tauri Rust Shell (Bridge Layer)         │  │
│  │  - Sidecar 管理 FastAPI 进程                    │  │
│  │  - 文件监听 (notify)                            │  │
│  │  - 系统对话框 (文件选择/编辑器打开)              │  │
│  └──────────────────┬─────────────────────────────┘  │
└─────────────────────┼────────────────────────────────┘
                      │
┌─────────────────────┴────────────────────────────────┐
│              FastAPI Backend (Engine Layer)            │
│                                                      │
│  Pipeline: Scan → Analyze → Generate Wiki → Embed    │
│                                                      │
│  ┌───────────┐  ┌───────────┐  ┌────────────────┐   │
│  │  Scanner  │  │ Analyzer  │  │ Wiki Generator │   │
│  │  (文件收集)│  │ (AST解析) │  │ (DeepSeek生成) │   │
│  └─────┬─────┘  └─────┬─────┘  └───────┬────────┘   │
│        │              │                │              │
│  ┌─────┴──────────────┴────────────────┴────────┐    │
│  │              Chroma Vector Store              │    │
│  │           (Wiki Chunk → Embedding)            │    │
│  └──────────────────────┬───────────────────────┘    │
│                         │                             │
│  ┌──────────────────────┴───────────────────────┐    │
│  │          RAG Chat Service                     │    │
│  │  检索 Top-5 chunk → DeepSeek Chat → 流式回答   │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

### 7.2 数据流

```
[1] 扫描阶段
  用户触发 → Scanner 扫描文件树 → 应用排除规则 → 得到文件列表

[2] 分析阶段
  文件列表 → AST 解析 → 提取实体（模块/类/函数/依赖）→ 构建依赖图

[3] Wiki 生成阶段
  结构化实体摘要 → DeepSeek API → Markdown + 源码锚点

[4] 持久化阶段
  Markdown → 写入 .code-wiki/ → 更新 state.json

[5] 向量化阶段
  Wiki chunk → DeepSeek Embedding → Chroma

[6] 增量更新
  文件变更 → Watcher 检测 → 增量 Pipeline → 局部更新 .md + Chroma

[7] Chat 问答
  用户提问 → Chroma 检索 Top-5 chunk → DeepSeek Chat → SSE 流式回答
```

---

## 8. 技术栈

| 层 | 技术 | 用途 |
|----|------|------|
| Desktop Shell | **Tauri v2** (Rust) | 窗口管理、文件系统、文件监听、进程管理 |
| Frontend | **React 18** + TypeScript + **TailwindCSS** + **shadcn/ui** + Vite | UI 渲染、组件库、状态管理 |
| State | **Zustand** | 前端全局状态（配置、分析状态、Wiki 树） |
| Charts | **Mermaid** (npm) | 架构图、类图、时序图前端渲染 |
| Backend | **FastAPI** (Python 3.11+) | 代码分析引擎、Wiki 生成、LLM 编排 |
| LLM | **DeepSeek API** (V4-Flash / V4-Pro) | Wiki 内容生成 + Chat 问答 |
| Vector DB | **FAISS** (HNSW) + BM25 (嵌入式) | Wiki chunk embedding → RAG 检索 |
| File Watch | **notify** crate (Rust) | 仓库文件变更监听 |
| Editor | VS Code / Cursor 协议 | 源码跳转打开编辑器 |

---

## 9. API 设计

### 9.1 REST API（FastAPI → React）

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/scan` | 触发分析。Body: `{ mode: "full" \| "partial", files?: string[] }` |
| `GET` | `/api/status` | 获取分析状态：`{ status, progress, current_step }` |
| `GET` | `/api/wiki/{*path}` | 获取指定 Wiki 页面 Markdown 内容 |
| `GET` | `/api/wiki/tree` | 获取 Wiki 文件树结构 |
| `GET` | `/api/diagrams/architecture` | 获取架构图 Mermaid DSL |
| `GET` | `/api/diagrams/classes` | 获取类图 Mermaid DSL |
| `GET` | `/api/diagrams/sequence/{fqn}` | 获取时序图 Mermaid DSL |
| `POST` | `/api/chat` | LLM Chat（SSE 流式），Body: `{ question, history }` |
| `GET` | `/api/files` | 获取仓库文件树（含排除状态、分析状态） |
| `GET` | `/api/config` | 获取当前配置 |
| `PUT` | `/api/config` | 更新配置（排除规则、LLM 设置、主题） |
| `GET` | `/api/events` | SSE 事件流（分析进度、文件变更通知） |

### 9.2 关键请求/响应示例

#### POST /api/scan（全部分析）

```json
{
  "mode": "full"
}
```

#### POST /api/scan（部分分析）

```json
{
  "mode": "partial",
  "files": ["services/user.py", "models/user.py"]
}
```

#### GET /api/status 响应

```json
{
  "status": "generating",
  "progress": 62,
  "current_step": "正在生成 Wiki: models/user.py",
  "started_at": "2026-06-26T16:30:00+08:00"
}
```

#### GET/PUT /api/config

```json
{
  "repo_path": "/home/user/my-project",
  "exclude_patterns": ["__pycache__/", ".git/", "*.test.py"],
  "llm": {
    "api_key": "sk-***",
    "model": "deepseek-v4-flash",
    "base_url": "https://api.deepseek.com",
    "temperature": 0.3
  },
  "theme": "dark"
}
```

### 9.3 Tauri Commands（Rust → React）

| Command | Description |
|---------|-------------|
| `pick_repository()` | 打开系统文件夹选择对话框，返回路径 |
| `open_in_editor(path, line)` | 调用系统默认编辑器打开文件到指定行 |
| `get_system_theme()` | 获取 OS 主题偏好（light/dark） |
| `store_secure(key, value)` | 加密存储敏感配置（API Key） |
| `load_secure(key)` | 读取加密存储的配置 |
| `manage_sidecar(action)` | 启动/停止/重启 FastAPI 进程 |

---

## 10. 项目结构

```
code-wiki/
├── src-tauri/                    # Tauri Rust Shell
│   ├── src/
│   │   ├── main.rs               # 窗口创建，全局状态，sidecar 管理
│   │   ├── commands.rs           # Tauri commands 定义
│   │   └── watcher.rs            # 文件监听 (notify crate)
│   ├── Cargo.toml
│   └── tauri.conf.json
│
├── src/                          # React Frontend
│   ├── App.tsx                   # 根组件：布局 + 主题 Provider
│   ├── main.tsx                  # 入口
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AppShell.tsx      # 三栏布局（LeftNav + Main + Chat）
│   │   │   ├── TopBar.tsx        # 顶栏
│   │   │   ├── StatusBar.tsx     # 底栏状态条
│   │   │   └── LeftNav.tsx       # 左侧垂直 Tab 导航
│   │   ├── code/
│   │   │   ├── FileTree.tsx      # 文件树组件（含排除标记、右键菜单）
│   │   │   └── CodeViewer.tsx    # 代码查看（语法高亮）
│   │   ├── wiki/
│   │   │   ├── WikiViewer.tsx    # Wiki 列表 + 内容切换
│   │   │   ├── WikiPage.tsx      # 单页 Markdown 渲染
│   │   │   ├── SourceLink.tsx    # 源码锚点链接渲染
│   │   │   └── DiagramViewer.tsx # Mermaid 图表容器
│   │   ├── chat/
│   │   │   ├── ChatDrawer.tsx    # Chat 抽屉面板
│   │   │   ├── ChatMessage.tsx   # 单条消息（含引用来源）
│   │   │   └── ChatInput.tsx     # 消息输入框
│   │   └── settings/
│   │       ├── SettingsPanel.tsx # 设置主面板（组装各区域）
│   │       ├── RepoConfig.tsx    # 仓库路径 + 排除规则
│   │       ├── LLMConfig.tsx     # LLM API Key + 模型 + 参数
│   │       ├── ThemeSwitch.tsx   # 主题选择
│   │       └── AnalysisControl.tsx # 分析模式 + 触发按钮
│   ├── hooks/
│   │   ├── useWiki.ts            # Wiki 数据获取
│   │   ├── useChat.ts            # 聊天逻辑
│   │   ├── useSSE.ts             # SSE 事件流订阅
│   │   ├── useTheme.ts           # 主题状态管理
│   │   └── useAnalysis.ts        # 分析状态轮询
│   ├── lib/
│   │   ├── api.ts                # FastAPI HTTP 客户端封装
│   │   └── constants.ts          # 默认值、排除规则、API 路径
│   ├── store/
│   │   └── configStore.ts        # Zustand 全局配置 store
│   └── styles/
│       └── globals.css           # TailwindCSS + 主题 CSS 变量
│
├── backend/                      # FastAPI Backend
│   ├── main.py                   # FastAPI 应用入口，CORS 配置
│   ├── config.py                 # 配置管理（从文件/环境加载）
│   ├── routes/
│   │   ├── scan.py               # POST /scan
│   │   ├── wiki.py               # GET /wiki/*
│   │   ├── chat.py               # POST /chat (SSE)
│   │   ├── status.py             # GET /status
│   │   ├── diagrams.py           # GET /diagrams/*
│   │   ├── files.py              # GET /files
│   │   └── config.py             # GET/PUT /config
│   ├── services/
│   │   ├── scanner.py            # 文件扫描 + 排除规则
│   │   ├── analyzer.py           # Python AST 实体提取
│   │   ├── dependency_graph.py   # 模块依赖图构建
│   │   ├── wiki_generator.py     # DeepSeek → Markdown 生成
│   │   ├── diagram_generator.py  # Mermaid 图表生成
│   │   ├── embedder.py           # Chroma 向量化
│   │   └── chat_service.py       # RAG 检索 + DeepSeek Chat
│   ├── models/
│   │   ├── entities.py           # 领域模型（Module, Class, Function）
│   │   └── schemas.py            # Pydantic 请求/响应模型
│   ├── pipeline.py               # Pipeline 编排器（全量/增量/部分）
│   └── requirements.txt
│
├── package.json
├── tsconfig.json
├── vite.config.ts
└── README.md
```

---

## 11. MVP 实施计划

### Phase 0：项目脚手架（1–2 天）

- [ ] P0.1 初始化 Tauri v2 + React 18 + TypeScript + TailwindCSS + Vite
- [ ] P0.2 初始化 FastAPI 项目，配置 CORS（localhost:1420）
- [ ] P0.3 Tauri sidecar 启动/管理 FastAPI 进程
- [ ] P0.4 Vite 开发代理 → localhost:8787
- [ ] P0.5 基础布局组件：AppShell + LeftNav + TopBar + StatusBar
- [ ] P0.6 TailwindCSS 亮/暗主题变量 + `useTheme` hook

### Phase 1：扫描与分析引擎（2–3 天）

- [ ] P1.1 `scanner.py`：递归扫描 + 排除规则 + 全量/部分模式
- [ ] P1.2 `analyzer.py`：Python AST 实体提取
- [ ] P1.3 `dependency_graph.py`：import 依赖图
- [ ] P1.4 数据模型 `entities.py`
- [ ] P1.5 API: `POST /scan` + `GET /status` + `GET /files`
- [ ] P1.6 API: `GET/PUT /config`
- [ ] P1.7 单元测试：analyzer + scanner

### Phase 2：设置页 & 配置（1–2 天）

- [ ] P2.1 `RepoConfig.tsx`：路径选择 + 排除规则编辑
- [ ] P2.2 `LLMConfig.tsx`：API Key + 模型 + 参数
- [ ] P2.3 `ThemeSwitch.tsx`：亮/暗/跟随系统
- [ ] P2.4 `SettingsPanel.tsx`：组装配置区域
- [ ] P2.5 配置持久化（Tauri Store + .code-wiki/config.json）

### Phase 3：Wiki 生成 & 本地持久化（2–3 天）

- [ ] P3.1 `wiki_generator.py`：DeepSeek → Markdown + 锚点
- [ ] P3.2 Wiki 本地存储：`.code-wiki/` 目录 + 覆盖策略
- [ ] P3.3 API: `GET /wiki/{*path}` + `GET /wiki/tree`
- [ ] P3.4 `WikiViewer.tsx` + `WikiPage.tsx`：Markdown 渲染
- [ ] P3.5 `SourceLink.tsx`：锚点解析 + 可点击跳转

### Phase 4：Code 浏览 & 文件树（1–2 天）

- [ ] P4.1 `FileTree.tsx`：文件树 + 状态图标 + 右键菜单
- [ ] P4.2 `CodeViewer.tsx`：语法高亮
- [ ] P4.3 部分分析入口：多选 → 右键 → 分析选中

### Phase 5：图表生成（1–2 天）

- [ ] P5.1 `diagram_generator.py`：Mermaid DSL 生成
- [ ] P5.2 API: `GET /diagrams/*`
- [ ] P5.3 `DiagramViewer.tsx`：Mermaid 渲染

### Phase 6：源码跳转（1 天）

- [ ] P6.1 Tauri `open_in_editor` command
- [ ] P6.2 SourceLink 点击 → 系统编辑器打开

### Phase 7：文件监听 & 增量更新（1–2 天）

- [ ] P7.1 Rust `watcher.rs`：notify crate
- [ ] P7.2 事件转发：Rust → React → FastAPI
- [ ] P7.3 `pipeline.py` 增量模式
- [ ] P7.4 SSE `GET /api/events`

### Phase 8：RAG & Chat（2–3 天）

- [ ] P8.1 Chroma 集成 + Wiki chunk embedding
- [ ] P8.2 `chat_service.py`：检索 + DeepSeek Chat
- [ ] P8.3 API: `POST /api/chat` (SSE streaming)
- [ ] P8.4 `ChatDrawer.tsx` + `ChatMessage.tsx` + `ChatInput.tsx`

### Phase 9：集成测试 & Polish（2 天）

- [ ] P9.1 端到端测试：真实 Python 仓库全流程
- [ ] P9.2 三态覆盖：loading / empty / error
- [ ] P9.3 打包验证：`tauri build`

---

## 12. 验收标准

| # | 验收项 | 验证方式 |
|---|--------|----------|
| 1 | 左侧导航三个 Tab（Code / Wiki / 设置）正常切换 | 点击各 Tab，主内容区正确切换 |
| 2 | 主题切换（亮/暗/跟随系统）即时生效 | 切换主题，全局样式变化 |
| 3 | 排除规则正确过滤文件，排除文件不出现在分析结果中 | 设置排除规则 → 分析 → Code Tab 中检查 |
| 4 | 全量分析正确生成所有 .md 文件 | 点击「全部分析」→ 检查 `.code-wiki/` 目录 |
| 5 | 部分分析仅分析选中文件 | 多选文件 → 右键分析 → 仅对应 .md 更新 |
| 6 | 重新分析正确覆盖旧 Wiki 文件 | 全量分析两次 → 对比 .md 文件内容与时间 |
| 7 | Wiki 中的源码锚点可点击跳转 | 点击 `[@src:...]` → 编辑器打开正确行 |
| 8 | 文件变更后自动增量更新 Wiki | 修改源码 → 等待 → 检查对应 .md 已更新 |
| 9 | Chat 问答基于 Wiki，引用来源正确 | 提问 → 检查回答引用指向真实 Wiki 片段 |
| 10 | API Key 加密存储，不泄露到 .code-wiki/ | 检查 config.json 不含 api_key |
| 11 | Python 仓库（~50 文件）30s 内完成全量分析 | 计时测试 |
| 12 | 架构图/类图/时序图正常渲染 | 打开图表 Tab 检查 Mermaid 渲染 |

---

## 13. 非 MVP 范围

以下功能**明确不在 MVP 范围内**：

- ❌ 多语言支持（Go / Rust / Java）
- ❌ Git 历史分析（commit 关联、变更追踪）
- ❌ 用户手动编辑 Wiki 内容
- ❌ 多仓库同时管理
- ❌ 导出 PDF / 静态 HTML 站点
- ❌ CI/CD GitHub Action 集成
- ❌ 自定义 Prompt 模板
- ❌ 本地模型支持（Ollama / llama.cpp）
- ❌ 移动端适配

---

*文档版本: v3 · 最后更新: 2026-06-26 · 状态: 待评审*
