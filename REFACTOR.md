# Code Wiki Backend — 重构计划 v1.0

> 基于 metrics.py 审查报告（12 问题，评分 8.0/10）制定。
> 目标：从单体 Router 重构为分层架构，提升可维护性和可扩展性。

---

## 现状架构

```
routes/metrics.py  (800 行)
  ├── JSON IO (_load_analysis, _load_json, _save_json)
  ├── Health 计算逻辑
  ├── Call Graph 查询 + 构建
  ├── Impact 分析
  ├── CFG 生成
  ├── Pattern Search
  ├── 数据恢复 (dict → Entity)
  └── 各种 Helper

routes/scan.py
  ├── _call_graph_to_dict()     ← 序列化逻辑放在 Router 里
  └── _save_analysis_results()  ← JSON 持久化放在 Router 里
```

### 主要问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | Router 太胖（800行），混合 IO/业务/序列化 | 不可测试，不可复用 |
| 2 | `analysis.json` 字段变更需改所有地方 | 维护成本高 |
| 3 | JSON 文件零散管理（5+ .json 文件） | 一致性差 |
| 4 | `except Exception: pass` 吞掉所有错误 | 排查困难 |
| 5 | 同步 IO 阻塞 async endpoint | 大项目时 Worker 卡死 |
| 6 | `queue.pop(0)` O(n) | 批量查询性能差 |
| 7 | Router 间循环依赖（routes.metrics ↔ routes.scan） | 循环导入风险 |
| 8 | 返回裸 dict 无类型校验 | Swagger 不完整 |

---

## 目标架构

```
┌─────────────────────────────────────────────────────┐
│  routes/           (每文件 ≤ 50 行)                  │
│  metrics.py  search.py  impact.py  cfg.py  graph.py │
│     │                                                 │
│     ▼                                                 │
├─────────────────────────────────────────────────────┤
│  services/         (纯业务逻辑)                       │
│  health_service.py  impact_service.py                 │
│  cfg_service.py  search_service.py                   │
│     │                                                 │
│     ▼                                                 │
├─────────────────────────────────────────────────────┤
│  repositories/     (数据访问层)                       │
│  analysis_repo.py  call_graph_repo.py                │
│  metrics_repo.py                                     │
│     │                                                 │
│     ▼                                                 │
├─────────────────────────────────────────────────────┤
│  serializers/      (实体 ↔ JSON)                     │
│  module_serializer.py  call_graph_serializer.py      │
│  response_serializer.py                               │
│     │                                                 │
│     ▼                                                 │
├─────────────────────────────────────────────────────┤
│  models/                                            │
│  entities.py  (已有)  response_models.py (新增)      │
└─────────────────────────────────────────────────────┘
```

### Router 瘦身示例

重构前（120 行）：
```python
@metrics_router.get("/impact")
async def get_impact(...):
    cg_data = _load_json("call_graph.json")     # IO
    callables = {eid: CallableEntity(...)}       # 序列化
    cg = CallGraphData(...)                      # 对象恢复
    # ... 60 行业务逻辑 ...
    return {"risk_score": ..., ...}              # 裸 dict
```

重构后（15 行）：
```python
@router.get("/impact", response_model=ImpactResponse)
async def get_impact(changed_files: str, service: ImpactService = Depends()):
    return service.analyze(changed_files)
```

---

## 分阶段实施

### Phase 1: 抽取 Repository 层（1.5h）

**目标**: 所有 JSON 读写集中到 Repository，Router 不再直接操作文件。

| 新建文件 | 职责 |
|----------|------|
| `repositories/__init__.py` | |
| `repositories/analysis_repo.py` | `load_analysis()` / `save_analysis()` / `load_modules()` |
| `repositories/call_graph_repo.py` | `load_call_graph()` / `save_call_graph()` / `build_on_demand()` |
| `repositories/metrics_repo.py` | `load_health_metrics()` / `save_health_metrics()` |

**关键接口**:
```python
class AnalysisRepository:
    def load_analysis(self) -> Optional[dict]: ...
    def load_modules(self) -> Dict[str, ModuleInfo]: ...  # dict → Entity 集中
    def save_analysis(self, modules, dep_graph, call_graph): ...
    def exists(self) -> bool: ...
```

**影响文件**: `routes/metrics.py`（减少 ~150 行）、`routes/scan.py`（减少 ~50 行）

---

### Phase 2: 提取 Service 层（2h）

**目标**: 业务逻辑从 Router 移到 Service，Router 只做参数校验和响应返回。

| 新建文件 | 职责 |
|----------|------|
| `services/health_service.py` | `compute()` → HealthMetrics |
| `services/impact_service.py` | `analyze(files)` → ImpactReport |
| `services/cfg_service.py` | `generate(file, func)` → CFGResponse |
| `services/search_service.py` | `search(pattern)` / `list_patterns()` |

**关键接口**:
```python
class ImpactService:
    def __init__(self, repo: AnalysisRepository, cg_repo: CallGraphRepository):
        self.repo = repo
        self.cg_repo = cg_repo

    def analyze(self, changed_files: List[str]) -> ImpactReport:
        cg = self.cg_repo.load_call_graph()
        if not cg:
            raise CallGraphNotAvailable()
        return self._compute_impact(cg, changed_files)

    def _compute_impact(self, cg: CallGraphData, files: List[str]) -> ImpactReport:
        # 所有风险计算逻辑在这里，不在 Router
        ...
```

**影响文件**: `routes/metrics.py`（减少 ~300 行）

---

### Phase 3: Pydantic Response Model（1h）

**目标**: 所有 API 返回类型化的 Response，自动生成 Swagger 文档。

| 新建文件 | 内容 |
|----------|------|
| `models/response_models.py` | HealthResponse, ImpactResponse, CFGResponse, CallGraphResponse, SearchResponse, TaintResponse |

**示例**:
```python
class HealthResponse(BaseModel):
    total_modules: int = 0
    total_functions: int = 0
    health_score: Optional[float] = None
    hotspots: List[HotspotItem] = []
    note: Optional[str] = None

class HotspotItem(BaseModel):
    file: str
    risk_score: float
    reasons: List[str]

class ImpactResponse(BaseModel):
    risk_score: float = 0.0
    changed_functions: List[str] = []
    affected_production: List[AffectedItem] = []
    affected_tests: List[AffectedItem] = []
    summary: str = ""
```

**影响文件**: `routes/metrics.py`（每个 endpoint 的 `return {...}` → `return response_model`）

---

### Phase 4: 性能 + 健壮性（1h）

| 问题 | 修复 |
|------|------|
| `queue.pop(0)` O(n) | → `collections.deque.popleft()` O(1) |
| `except Exception: pass` | → `except (FileNotFoundError, JSONDecodeError)` 分类处理 |
| 同步 IO 阻塞 | → `_load_json` 加 `lru_cache` 避免重复读 |
| Magic Number | → 常量提取: `MAX_CALL_DEPTH = 5`, `DEFAULT_RISK_FACTOR = 0.08` |

---

## 文件变更总览

| 阶段 | 新建 | 删除 | 修改 |
|------|------|------|------|
| Phase 1 | `repositories/*.py` (3) | — | `routes/metrics.py`, `routes/scan.py` |
| Phase 2 | `services/health_service.py`, `impact_service.py`, `cfg_service.py`, `search_service.py` (4) | — | `routes/metrics.py` |
| Phase 3 | `models/response_models.py` (1) | — | `routes/metrics.py` |
| Phase 4 | — | — | `services/impact_service.py`, `repositories/*.py`, `routes/metrics.py` |

---

## 不影响的功能

以下模块不参与本次重构（独立、稳定）：

- `services/tree_sitter_parser.py` — 已有自己的缓存和模块边界
- `services/call_graph.py` — 纯算法，无 IO
- `services/data_flow.py` — 纯算法，无 IO
- `services/knowledge_graph.py` — 有独立序列化
- `services/code_search.py` — 纯算法
- `services/health_metrics.py` — 纯计算（`_compute_score` 需改为 public）
- `services/impact_analyzer.py` — 纯计算

---

## 验收标准

重构后：
- `routes/metrics.py` ≤ 150 行（当前 ~800 行）
- 每个 Router 函数 ≤ 20 行
- 所有 API 有 Pydantic Response Model
- 无 `except Exception: pass`
- 无 `queue.pop(0)`
- 无 Router 间交叉 import
- Swagger `/api/docs` 可展示完整 Response Schema
