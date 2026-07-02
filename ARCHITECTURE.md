# Code Wiki — 代码分析增强架构设计 v2.0

> 本文档描述 Code Wiki 代码分析引擎的 8 大升级方向的技术原理、数据结构和集成方案。
> 基于对当前代码库（`backend/services/analyzer.py`, `ts_analyzer.py`, `dependency_graph.py` 等）的深入审查编写。

---

## 目录

1. [Tree-sitter 统一解析引擎](#1-tree-sitter-统一解析引擎)
2. [调用图 Call Graph](#2-调用图-call-graph)
3. [代码知识图谱 Code Knowledge Graph](#3-代码知识图谱-code-knowledge-graph)
4. [数据流分析 & 污点分析](#4-数据流分析--污点分析-data-flow--taint-analysis)
5. [控制流分析 Control Flow Graph](#5-控制流分析-control-flow-graph-cfg)
6. [语义代码搜索 Semantic Code Search](#6-语义代码搜索-semantic-code-search)
7. [测试覆盖率 & 影响分析](#7-测试覆盖率--影响分析)
8. [项目健康度仪表盘](#8-项目健康度仪表盘)

---

## 1. Tree-sitter 统一解析引擎

### 1.1 技术原理

**Tree-sitter** 是一个增量解析库，由 GitHub 开发并用于其代码导航系统（semantic、stack-graphs）。

核心概念：

```
Source Code → Lexer (tokenize) → Parser → CST (Concrete Syntax Tree) → Query → 结构化提取
                                              ↑
                                         容错恢复（Error Recovery）
```

| 特性 | 说明 |
|------|------|
| **增量解析** | 文件修改后只 re-parse 变化的子树，复杂度 O(log n) |
| **容错解析** | 即使代码有语法错误，也能产出包含 ERROR 节点的部分树 |
| **零依赖 S-expression 查询** | 用模式匹配提取节点，比手写 AST walker 简洁 10x |
| **跨语言一致 API** | 40+ 语言（Python/TS/JS/Go/Rust/C++/Java...）统一接口 |

### 1.2 与当前实现的对比

| 维度 | 当前 (stdlib ast + regex) | Tree-sitter |
|------|---------------------------|-------------|
| Python 精度 | ✅ AST 精确 | ✅ AST 精确 + 容错 |
| TS/JS 精度 | ❌ 正则不可靠（泛型、嵌套箭头函数） | ✅ 完整 CST |
| 新增语言成本 | 需写新解析器（~500 行 regex） | 只需换 grammar（~10 行配置） |
| 查询速度 | 快（stdlib ast 是 C 扩展） | 快（C 核心，tree-sitter-cpython 绑定） |
| 增量更新 | ❌ 不支持 | ✅ 核心能力 |

### 1.3 实现方案

```python
# 新增: backend/services/tree_sitter_parser.py

from tree_sitter import Language, Parser, Query

class TreeSitterParser:
    """Unified multi-language parser based on tree-sitter."""
    
    LANGUAGE_MAP = {
        SupportedLanguage.PYTHON: "python",
        SupportedLanguage.TYPESCRIPT: "typescript",
        SupportedLanguage.JAVASCRIPT: "javascript",
        # 未来扩展:
        # "go", "rust", "java", "cpp", "c_sharp"
    }
    
    def __init__(self):
        self._parsers: dict[str, Parser] = {}
        self._lazy_init_parsers()
    
    def parse(self, source: str, language: str) -> Tree:
        """Parse source code into a tree-sitter CST."""
        ...
    
    def query(self, tree: Tree, pattern: str) -> list[QueryMatch]:
        """Run S-expression query against the tree."""
        ...
    
    # ---- 各语言提取规则 (S-expression queries) ----
    
    PYTHON_FUNCTIONS = """
    (function_definition
      name: (identifier) @func.name
      parameters: (parameters) @func.params
      return_type: (type)? @func.return_type
      body: (block) @func.body
      decorator: (decorator)? @func.decorator
    ) @func.def
    """
    
    TYPESCRIPT_FUNCTIONS = """
    (function_declaration
      name: (identifier) @func.name) @func.def
    (arrow_function
      .) @arrow.def
    (method_definition
      name: (property_identifier) @func.name) @method.def
    """
```

### 1.4 对现有代码的影响

- **替换**: `analyzer.py` 中的 `_analyze_python_file` 改用 tree-sitter query
- **替换**: `ts_analyzer.py` 整个文件 → 统一到 `TreeSitterParser` 中
- **保留**: `ModuleInfo` / `FunctionInfo` / `ClassInfo` 等实体类型不变（向后兼容）
- **新增依赖**: `tree-sitter>=0.23` + language packages

---

## 2. 调用图 Call Graph

### 2.1 技术原理

调用图是**有向图** `G = (V, E)` 其中：
- **V**: 函数/方法节点，标识为 `(file_path, func_name, line)`
- **E**: 调用边 `Caller → Callee`，边可能标注调用位置

```
┌─────────────────────────────────────────┐
│  main()                                │
│    ├── CALLS → init_config()           │
│    ├── CALLS → load_data()             │
│    │             ├── CALLS → read_csv()│
│    │             └── CALLS → validate()│
│    └── CALLS → render()                │
└─────────────────────────────────────────┘
```

### 2.2 构建算法

#### Step 1: 收集所有可调用实体
```python
CallableEntity = NamedTuple("CallableEntity", [
    ("module", str),       # e.g. "services/user.py"
    ("name", str),         # e.g. "get_user"
    ("parent_class", str), # e.g. "UserService" or None
    ("anchor", SourceAnchor),
])
```

#### Step 2: 提取每个函数体内的调用点
使用 tree-sitter query 识别调用表达式：
```scheme
; Python 调用
(call
  function: (identifier) @call.name
  arguments: (argument_list) @call.args
) @call.expr

; 方法调用 obj.method()
(call
  function: (attribute
    object: (_) @call.receiver
    attribute: (identifier) @call.method)
) @call.expr
```

#### Step 3: 名称解析 (Name Resolution)
将调用名解析到具体定义：
1. **同模块内解析**：在当前文件中查找 `def call_name`
2. **同目录解析**：检查同目录其他模块的导出
3. **跨模块解析**：利用 import 关系，跟踪 `from X import Y`
4. **类方法解析**：`self.method()` → 在本类和父类中查找

```python
class CallGraphBuilder:
    def resolve_call(self, call_name: str, context: ResolveContext) -> Optional[CallableEntity]:
        # 1. Local scope: same file
        if local := self._find_in_module(call_name, context.module):
            return local
        # 2. Imported names: from X import Y
        if imported := self._resolve_imported(call_name, context):
            return imported
        # 3. Self/parent class methods
        if context.parent_class and (method := self._find_method(call_name, context.parent_class)):
            return method
        # 4. Builtins / stdlib — not tracked in call graph
        return None
```

### 2.3 数据结构

```python
@dataclass
class CallGraph:
    """Function-level call graph."""
    
    # Forward: {caller_id -> [callee_ids]}
    forward: dict[str, list[str]]
    # Reverse: {callee_id -> [caller_ids]}  
    reverse: dict[str, list[str]]
    # Entity registry: {entity_id -> CallableEntity}
    entities: dict[str, CallableEntity]
    
    def callers_of(self, entity_id: str) -> list[str]: ...
    def callees_of(self, entity_id: str) -> list[str]: ...
    def transitive_callers(self, entity_id: str) -> set[str]: ...
    def find_call_path(self, from_id: str, to_id: str) -> Optional[list[str]]: ...
    
    def to_mermaid(self, max_depth: int = 3) -> str:
        """Export subgraph centered on a selected entity."""
        ...
```

### 2.4 集成点

- **Wiki 生成**：`prompt_builder.py` 注入调用上下文（"此函数被 X 调用，调用了 Y"）
- **差异分析**：Git diff → 变更函数 → 调用图 → 影响面评估
- **前端可视化**：Wiki 页面内嵌函数调用 Mermaid 图

---

## 3. 代码知识图谱 Code Knowledge Graph

### 3.1 技术原理

知识图谱 = **多类型节点 + 多类型边** 的异构图：

```
节点类型:
  ├── Module     (模块/文件)
  ├── Class      (类)
  ├── Function   (函数/方法)
  ├── Interface  (接口/类型)
  ├── Component  (React 组件)
  └── Variable   (全局变量/常量)

边类型:
  ├── CONTAINS     Module → Class/Function/Interface
  ├── CALLS        Function → Function
  ├── INHERITS     Class → Class
  ├── IMPLEMENTS   Class → Interface
  ├── IMPORTS      Module → Module
  ├── DECORATES    Decorator → Function/Class
  ├── RAISES       Function → Exception
  ├── RETURNS_TYPE Function → Type
  └── USES_HOOK    Component → Hook
```

### 3.2 存储方案

选用 **NetworkX**（轻量，适合中等规模项目 < 10K 节点）：

```python
import networkx as nx

class CodeKnowledgeGraph:
    def __init__(self):
        self.graph = nx.MultiDiGraph()  # 多关系有向图
    
    def add_entity(self, entity_id: str, **attrs):
        self.graph.add_node(entity_id, **attrs)
    
    def add_relation(self, from_id: str, to_id: str, relation: str, **attrs):
        self.graph.add_edge(from_id, to_id, key=relation, **attrs)
    
    # 图查询
    def get_call_chain(self, func_id: str) -> list: ...
    def find_related(self, entity_id: str, depth: int = 2) -> dict: ...
    def page_rank(self) -> dict[str, float]: ...    # 核心度排名
    def detect_communities(self) -> list[set]: ...   # 模块边界检测
    def shortest_path(self, from_id: str, to_id: str) -> list: ...
```

### 3.3 序列化

```python
# 持久化到 JSON 文件（.code-wiki/knowledge_graph.json）
def to_dict(graph: nx.MultiDiGraph) -> dict:
    return {
        "nodes": [{"id": n, **graph.nodes[n]} for n in graph.nodes],
        "edges": [
            {"from": u, "to": v, "relation": k, **graph.edges[u, v, k]}
            for u, v, k in graph.edges(keys=True)
        ],
    }
```

### 3.4 前端集成

- **图谱可视化**：使用 Cytoscape.js 或 vis-network 渲染交互式力图
- **API**：`GET /api/graph/entity/{id}` — 返回子图 JSON
- **搜索**：`GET /api/graph/search?q=func_name&depth=2`

---

## 4. 数据流分析 & 污点分析 Data Flow / Taint Analysis

### 4.1 技术原理

#### 数据流分析 (Data Flow Analysis)
跟踪**值**在程序中的传播路径：

```
x = get_user_input()     ← Source (数据来源)
y = transform(x)          ← 数据流边
z = validate(y)           ← 数据流边
store_to_db(z)            ← Sink (数据终点)
```

#### 污点分析 (Taint Analysis)
数据流分析的特化——标记来自**不可信来源**的数据为"污点"，跟踪其传播：

```
Source (污点源):
  - request.args / request.form (Web输入)
  - os.environ / process.env (环境变量)
  - file.read() (文件读取)
  - database query result (数据库查询)

Sanitizer (净化器):
  - html.escape() / escapeHtml()
  - int() / parseInt() 类型转换
  - re.match() 正则验证

Sink (危险汇):
  - subprocess.run() / exec() (命令执行)
  - eval() / Function() (代码注入)
  - database.execute() → SQL 注入
  - innerHTML → XSS
```

### 4.2 实现方案

#### Step 1: 构建 SSA (Static Single Assignment)
```python
# SSA 形式的中间表示
class SSABuilder:
    def build_ssa(self, func_node: tree_sitter.Node) -> dict:
        """将函数内每个变量赋值转换为唯一版本号:
           x → x_0, x_1, x_2 ..."""
        ...
```

#### Step 2: 构建数据流图
```python
@dataclass
class DataFlowEdge:
    source_var: str       # 源变量 (SSA 版本)
    target_var: str       # 目标变量
    location: SourceAnchor
    operation: str        # "assign" | "call_arg" | "return"

class DataFlowAnalyzer:
    def analyze_function(self, func: FunctionInfo, source: str) -> DataFlowGraph:
        """
        构建函数内的数据流图:
        1. 解析函数 AST → 基本块
        2. 将赋值语句转换为数据流边
        3. SSA 转换以保证精确性
        """
        ...
```

#### Step 3: 污点传播规则
```python
TAINT_SOURCES = {
    "python": [
        "request.args", "request.form", "request.json",
        "os.environ.get", "input(", "sys.argv",
        "open(", "pathlib.Path.read_text",
    ],
    "typescript": [
        "req.body", "req.params", "req.query",
        "process.env", "document.querySelector",
        "localStorage.getItem", "fetch(",
    ],
}

TAINT_SINKS = {
    "python": [
        "subprocess.run", "os.system", "eval(", "exec(",
        "sqlite3.execute", "open(", "pickle.loads",
    ],
    "typescript": [
        "eval(", "Function(", "innerHTML", "dangerouslySetInnerHTML",
        "document.write", "new WebSocket",
    ],
}

TAINT_SANITIZERS = {
    "python": ["html.escape", "int(", "float(", "json.loads", "re.match"],
    "typescript": ["escapeHtml", "parseInt", "JSON.parse", "encodeURIComponent"],
}
```

### 4.3 输出格式

```python
@dataclass
class TaintFlow:
    """A complete taint flow from source to sink."""
    source: SourceAnchor           # 污点产生位置
    sink: SourceAnchor             # 危险使用位置
    path: list[DataFlowEdge]       # 传播路径
    sanitized: bool                # 是否经过净化
    risk_level: str                # "high" | "medium" | "low"

@dataclass 
class DataFlowGraph:
    function_id: str
    edges: list[DataFlowEdge]
    taint_flows: list[TaintFlow]
    # 可用于 LLM 上下文
    def summary(self) -> str:
        """生成人类可读的数据流摘要。"""
        ...
```

---

## 5. 控制流分析 Control Flow Graph (CFG)

### 5.1 技术原理

CFG 将一个函数分解为**基本块 (Basic Block)**：

> 基本块 = 一段不包含跳转的连续指令序列，只有入口在开头、出口在结尾

```
def classify(x: int):
    if x > 0:              ← 条件跳转（分支）
        return "positive"  ← 基本块 B1
    elif x < 0:            ← 基本块 B2 的条件
        return "negative"  ← 基本块 B3
    else:
        return "zero"      ← 基本块 B4

        ┌──────┐
        │ Entry │
        └──┬───┘
           │
      ┌────▼────┐
      │ x > 0?  │ ← Block 0 (条件)
      └─┬───┬───┘
    T   │   │   F
   ┌────▼┐  │  ┌────▼────┐
   │ B1  │  │  │ x < 0?  │ ← Block 1
   │ret  │  │  └─┬───┬───┘
   └──┬──┘  │  T │   │ F
      │     │ ┌──▼─┐┌──▼──┐
      │     │ │ B2 ││ B3  │
      │     │ │ret ││ ret │
      │     │ └──┬─┘└──┬──┘
      ▼     ▼    ▼     ▼
      ┌──────────────┐
      │     Exit     │
      └──────────────┘
```

### 5.2 构建算法

```python
class CFGBuilder:
    def build(self, func_node: tree_sitter.Node, source: str) -> ControlFlowGraph:
        """
        1. 识别 Leader 指令（基本块的第一条指令）:
           - 函数入口
           - 跳转目标 (if/else/for/while/except)
           - 跳转指令的下一条
        2. 划分基本块
        3. 添加控制流边:
           - 顺序流: Block N → Block N+1
           - 条件跳转: Block N → Block T, Block F
           - 循环回边: Block N → Block loop_header
        4. 计算支配树 (Dominator Tree)
        5. 识别循环 (自然循环 = 回边 + 支配关系)
        """
        ...
```

### 5.3 复杂度指标

```python
@dataclass
class ControlFlowGraph:
    blocks: list[BasicBlock]
    edges: list[tuple[int, int, str]]  # (from_block, to_block, edge_type)
    entry_block: int
    exit_block: int
    
    @property
    def cyclomatic_complexity(self) -> int:
        """McCabe 圈复杂度 = E - N + 2P
           E = 边数, N = 节点数, P = 连通分量数 (通常为1)
           经验: 1-10 简单, 11-20 中等, 21-50 复杂, >50 不可测试
        """
        return len(self.edges) - len(self.blocks) + 2
    
    @property
    def max_nesting_depth(self) -> int: ...
    
    @property
    def unreachable_blocks(self) -> list[int]:
        """检测不可达代码 (Dead Code)。"""
        ...

@dataclass
class BasicBlock:
    id: int
    statements: list[SourceAnchor]
    successors: list[int]    # 后继块 ID
    predecessors: list[int]  # 前驱块 ID
    is_loop_header: bool
```

### 5.4 可视化

```python
def to_mermaid(self) -> str:
    """生成 Mermaid flowchart 表示。"""
    # 用不同颜色标记: 入口(绿)、出口(红)、循环头(橙)、死代码(灰)
    ...
```

---

## 6. 语义代码搜索 Semantic Code Search

### 6.1 技术原理

当前方案：`自然语言 query → text embedding → BM25/Cosine RRF → Top-K chunks`

语义代码搜索增强为**多路召回的混合检索**：

```
用户查询 "找到所有读取环境变量的地方"
        │
        ├── ① 自然语言理解 → Embedding → Dense Search (FAISS)
        ├── ② 关键词分词 → BM25 lexical search
        ├── ③ AST 模式匹配 → os.environ / process.env 精确匹配
        └── ④ 代码专用 Embedding (UniXCoder) → Code Similarity
                    │
                    ▼
              RRF 融合 → Reranker → Top-K
```

### 6.2 代码专用 Embedding

```python
class CodeEmbeddingClient:
    """
    当前通用 embedding 模型对代码理解有限。
    升级为代码专用模型:
    
    候选模型:
    - microsoft/unixcoder-base (代码+文本双模态)
    - Salesforce/codet5p-110m-embedding (轻量)
    - BAAI/bge-large-en-v1.5 (通用但代码效果也不错)
    """
    
    async def embed_code(self, code_snippet: str) -> list[float]:
        """Embed code using code-specialized model."""
        ...
    
    async def embed_query(self, natural_language: str) -> list[float]:
        """Embed natural language query (code-aware)."""
        ...
```

### 6.3 AST 模式查询

```python
class ASTPatternSearch:
    """
    允许用户用伪代码模式搜索:
    - "fetch( ).catch( )" → 匹配所有 fetch().catch() 调用
    - "const [state, setState] = useState" → 匹配所有 useState
    """
    
    PATTERNS = {
        "fetch_catch": """
        (call_expression
          function: (member_expression
            object: (call_expression function: (identifier) @callee (#eq? @callee "fetch"))
            property: (property_identifier) @method (#eq? @method "catch")))
        """,
        "env_read": """
        (member_expression
          object: (identifier) @obj (#match? @obj "process|os")
          property: (property_identifier) @prop (#match? @prop "env|environ"))
        """,
    }
```

### 6.4 检索增强的 Wiki 生成

在 `prompt_builder.py` 中增加代码语义上下文：

```python
# 现有: 注入 AST chunk 检索结果
# 新增: 注入相似代码片段
def build_code_context(query: str, code_index: FAISSVectorStore) -> str:
    similar_code = code_index.search_similar_code(query, top_k=3)
    return "\n---\n".join(f"Similar code in {c['source']}:\n{c['code']}" for c in similar_code)
```

---

## 7. 测试覆盖率 & 影响分析

### 7.1 技术原理

#### 影响分析 (Impact Analysis)
基于调用图 + Git diff，计算代码变更的**影响半径**：

```
Git Diff:
  modified: services/auth.py
      ├── changed: login()          ← 变更点
      └── changed: validate_token()
            │
            ▼ 调用图反向查询
      affected callers:
      ├── routes/auth.py → handle_login()
      ├── middleware.py → authenticate()
      └── tests/test_auth.py → test_login()

      → 影响面: 3 files, 2 functional + 1 test
```

#### 测试覆盖率分析
无需运行测试——通过分析测试文件的**调用关系**推断覆盖：

```python
class CoverageAnalyzer:
    def analyze(self, call_graph: CallGraph, test_patterns: list[str]) -> CoverageReport:
        """
        1. 识别测试文件: test_*.py, *.test.ts, spec/ 目录
        2. 提取测试函数调用的生产代码函数
        3. 未覆盖 = 生产函数 - 被测试调用的函数
        """
        test_files = self._find_test_files()
        covered_funcs = set()
        for test_file in test_files:
            for called in call_graph.callees_of(test_file):
                covered_funcs.add(called)
        
        all_funcs = set(call_graph.entities.keys())
        uncovered = all_funcs - covered_funcs
        
        return CoverageReport(
            total_funcs=len(all_funcs),
            covered=len(covered_funcs),
            uncovered=[call_graph.entities[f] for f in uncovered],
            coverage_rate=len(covered_funcs) / max(len(all_funcs), 1),
        )
```

### 7.2 输出

```python
@dataclass
class ImpactReport:
    changed_files: list[str]
    changed_functions: list[str]
    affected_callers: list[ImpactEntry]    # 受影响的生产代码
    affected_tests: list[ImpactEntry]      # 受影响的测试文件
    risk_score: float                      # 0.0 - 1.0
    recommendation: str                    # LLM 生成的影响说明

@dataclass
class ImpactEntry:
    entity_id: str
    distance: int  # 离变更点的距离（调用链深度）
    path: list[str]  # 调用链路径 A → B → C
```

### 7.3 集成到 Watcher

当前 `watcher.py` 监听文件变化后直接触发 re-scan。增强为：

```python
class Watcher:
    async def on_change(self, changed_files: list[str]):
        # 1. 增量 Tree-sitter 解析变更文件
        # 2. 更新调用图
        # 3. 运行影响分析
        impact = self.impact_analyzer.analyze(changed_files, self.call_graph)
        # 4. 发送 SSE 事件（影响面 + 建议）
        await self.emit("impact_analysis", impact.to_dict())
        # 5. 更新 Wiki（仅更新受影响的相关页面）
```

---

## 8. 项目健康度仪表盘

### 8.1 指标定义

```python
@dataclass
class HealthMetrics:
    """Project health dashboard metrics."""
    
    # ---- 规模指标 ----
    total_modules: int
    total_functions: int
    total_classes: int
    total_lines: int
    
    # ---- 复杂度指标 ----
    avg_cyclomatic_complexity: float
    max_cyclomatic_complexity: int
    complex_functions: list[tuple[str, int]]    # top-10 高复杂度函数
    avg_nesting_depth: float
    
    # ---- 耦合/内聚指标 ----
    avg_coupling: float              # 平均每个模块的依赖数
    max_coupling: int                # 最大耦合度
    isolated_modules: int            # 孤岛模块数
    coupling_distribution: dict      # {coupling_level: count}
    
    # ---- 变更热度 ----
    churn_rate: dict[str, int]       # {file: git_changes_in_last_90_days}
    hot_files: list[tuple[str, int, float]]  # (file, churn, complexity) 
    
    # ---- 代码质量 ----
    code_duplication: float          # 克隆检测比率 (0.0 - 1.0)
    dead_code_blocks: int            # 不可达基本块总数
    test_coverage: float             # 估算测试覆盖率
    
    # ---- 风险评分 ----
    overall_health_score: float      # 0-100 综合评分
    risk_hotspots: list[dict]        # 高风险热点
```

### 8.2 热点计算

```python
def compute_hotspots(metrics: HealthMetrics) -> list[dict]:
    """
    Hotspot = 高复杂度 + 高变更频率 + 低测试覆盖
    
    算法:
    1. 对每个模块计算 risk = w1*complexity_norm + w2*churn_norm + w3*(1-coverage)
    2. 排序取 Top-10
    3. 生成 Markdown 报告
    """
    w1, w2, w3 = 0.4, 0.35, 0.25  # 权重可调
    
    hotspots = []
    for module in all_modules:
        complexity_norm = normalize(module.complexity, max_complexity)
        churn_norm = normalize(module.churn, max_churn)
        coverage = module.coverage or 0
        risk = w1 * complexity_norm + w2 * churn_norm + w3 * (1 - coverage)
        hotspots.append({"module": module.path, "risk": risk, ...})
    
    return sorted(hotspots, key=lambda x: -x["risk"])[:10]
```

### 8.3 前端展示

- **指标卡片**（顶行）：总模块数、函数数、覆盖率、健康评分
- **复杂度分布图**：直方图/热力图
- **热点列表**：Top-10 需要关注的模块
- **趋势图**：历史扫描对比（需要持久化历史数据）

---

## 实施路线图

| 阶段 | 内容 | 工作量 | 关键文件 |
|------|------|--------|----------|
| **Phase 1** | Tree-sitter 统一解析器 | ~500 LOC | `services/tree_sitter_parser.py` |
| **Phase 2** | 调用图 | ~400 LOC | `services/call_graph.py` |
| **Phase 3** | 代码知识图谱 | ~350 LOC | `services/knowledge_graph.py` |
| **Phase 4** | 数据流 & 污点分析 | ~600 LOC | `services/data_flow.py` |
| **Phase 5** | 控制流图 CFG | ~400 LOC | `services/control_flow.py` |
| **Phase 6** | 语义代码搜索 | ~300 LOC | `services/code_search.py` (增强现有) |
| **Phase 7** | 测试覆盖率 & 影响分析 | ~350 LOC | `services/impact_analyzer.py` |
| **Phase 8** | 健康度仪表盘 | ~250 LOC | `services/health_metrics.py` |

**总计**: ~3150 LOC，分 8 个 Phase 逐步交付，每个 Phase 独立可测试。

---

## 架构集成总览

```
                          ┌─────────────────────────┐
                          │     FastAPI Backend      │
                          └───────────┬─────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
     ┌────────▼────────┐   ┌─────────▼─────────┐   ┌────────▼────────┐
     │  Scanner        │   │  Analyzer Service  │   │  Wiki Generator │
     │  (scanner.py)   │   │  (analyzer.py)     │   │  (wiki/*.py)    │
     └────────┬────────┘   └─────────┬─────────┘   └────────┬────────┘
              │                      │                      │
              │              ┌───────▼────────┐              │
              │              │ TreeSitterParser│ ← Phase 1   │
              │              │ (new)           │              │
              │              └───────┬────────┘              │
              │                      │                      │
              │         ┌────────────┼────────────┐         │
              │         │            │            │         │
              │  ┌──────▼─────┐ ┌───▼────┐ ┌────▼─────┐    │
              │  │ CallGraph  │ │ CFG    │ │ DataFlow │    │
              │  │ (Phase 2)  │ │(Ph. 5) │ │(Phase 4) │    │
              │  └──────┬─────┘ └───┬────┘ └────┬─────┘    │
              │         │           │           │           │
              │  ┌──────▼───────────▼───────────▼──────┐    │
              │  │      CodeKnowledgeGraph             │    │
              │  │      (Phase 3) — 统一图存储         │    │
              │  └──────────────┬──────────────────────┘    │
              │                 │                           │
              │     ┌───────────┼───────────┐               │
              │     │           │           │               │
              │  ┌──▼───┐  ┌───▼────┐ ┌───▼──────┐         │
              │  │Impact│  │Health  │ │Code      │         │
              │  │Analy.│  │Metrics │ │Search    │         │
              │  │(Ph.7)│  │(Ph. 8) │ │(Phase 6) │         │
              │  └──────┘  └────────┘ └──────────┘         │
              │                                            │
              └────────────────────────────────────────────┘
```

所有新模块向 `models/entities.py` 注册新的实体类型，保持 `ModuleInfo` 作为核心数据载体，增量扩展而不断裂现有 API。
