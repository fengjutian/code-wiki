"""
Metrics & Analysis API routes — exposes new analysis capabilities to the frontend.

Endpoints:
  GET  /api/metrics/health       — project health dashboard
  GET  /api/metrics/call-graph   — function-level call graph data
  GET  /api/metrics/callers      — find callers of a specific function
  GET  /api/metrics/taint        — taint analysis results
  GET  /api/metrics/impact       — impact analysis for changed files
  GET  /api/search/pattern       — semantic code pattern search
"""

import logging
import os
from typing import Optional, List

from fastapi import APIRouter, Query

from config import get_wiki_path, get_config
from repositories.analysis_repo import AnalysisRepository
from models.response_models import (
    HealthResponse, ImpactResponse, SearchResponse, PatternListResponse,
    CFGResponse, TaintResponse, CallersResponse,
)

logger = logging.getLogger("code-wiki.metrics")

router = APIRouter()
metrics_router = APIRouter()     # /api/metrics/*
search_router = APIRouter()       # /api/search/*

# ---------------------------------------------------------------------------
# Repository — lazy singleton
# ---------------------------------------------------------------------------

# Lazy-loaded repositories: always use get_wiki_path() for current path.
_repo = None  # kept for backward compat in other routes


def _get_repo() -> AnalysisRepository:
    """Return a repository pointing to the *current* wiki path (not cached)."""
    return AnalysisRepository(get_wiki_path())


# ---------------------------------------------------------------------------
# Helpers (delegating to repository)
# ---------------------------------------------------------------------------

def _load_analysis() -> Optional[dict]:
    """Load saved analysis.json."""
    return _get_repo().load_analysis()


def _load_json(filename: str) -> Optional[dict]:
    """Load a JSON file from .code-wiki directory via repository."""
    repo = _get_repo()
    mapping = {
        "call_graph.json": repo.load_call_graph,
        "health_metrics.json": repo.load_health_metrics,
        "taint_analysis.json": repo.load_taint,
    }
    loader = mapping.get(filename)
    if loader:
        return loader()
    return repo._read_json(repo._wiki / filename)


def _save_json(filename: str, data: dict):
    """Save a JSON file to .code-wiki directory via repository."""
    repo = _get_repo()
    mapping = {
        "health_metrics.json": lambda: repo.save_health_metrics(data),
        "taint_analysis.json": lambda: repo.save_taint(data),
    }
    saver = mapping.get(filename)
    if saver:
        saver()
    else:
        repo._write_json(repo._wiki / filename, data)


def _build_call_graph_on_demand() -> dict | None:
    """Build call_graph.json from existing analysis.json if it's missing.

    This handles the case where analysis was run before the call graph builder
    was wired into the scan pipeline.
    """
    analysis = _load_analysis()
    if not analysis:
        return None

    modules_raw = analysis.get("modules", {})
    if not modules_raw:
        return None

    config = get_config()
    repo_path = config.get("repo_path", "")
    if not repo_path:
        return None

    # Get tree-sitter parser (lazy, same as analyzer)
    try:
        from services.tree_sitter_parser import TreeSitterParser
        ts_parser = TreeSitterParser()
    except Exception as e:
        logger.warning("Cannot build call graph on demand: tree_sitter unavailable (%s)", e)
        return None

    # Reconstruct minimal ModuleInfo objects from analysis.json
    # Only the fields CallGraphBuilder needs: path, language, functions, classes, imports
    from models.entities import (
        FunctionInfo, ClassInfo, ModuleInfo,
    )

    modules: Dict[str, "ModuleInfo"] = {}
    _HUGE_END = 10**9  # fallback end_line when not in analysis.json

    for rel_path, mod_data in modules_raw.items():
        lang_str = mod_data.get("language", "python")
        try:
            language = SupportedLanguage(lang_str)
        except ValueError:
            language = SupportedLanguage.PYTHON

        # Reconstruct functions
        functions = []
        for fd in mod_data.get("functions", []):
            anchor = None
            if fd.get("anchor"):
                anchor = SourceAnchor(
                    file=fd["anchor"].get("file", rel_path),
                    line=fd["anchor"].get("line", 1),
                )
            functions.append(FunctionInfo(
                name=fd.get("name", "unknown"),
                anchor=anchor,
                end_line=fd.get("end_line", _HUGE_END),
                docstring=fd.get("docstring"),
            ))

        # Reconstruct classes with methods
        classes = []
        for cd in mod_data.get("classes", []):
            methods = []
            for md in cd.get("methods", []):
                m_anchor = None
                if md.get("anchor"):
                    m_anchor = SourceAnchor(
                        file=md["anchor"].get("file", rel_path),
                        line=md["anchor"].get("line", 1),
                    )
                methods.append(FunctionInfo(
                    name=md.get("name", "unknown"),
                    anchor=m_anchor,
                    end_line=md.get("end_line", _HUGE_END),
                    docstring=md.get("docstring"),
                ))
            c_anchor = None
            if cd.get("anchor"):
                c_anchor = SourceAnchor(
                    file=cd["anchor"].get("file", rel_path),
                    line=cd["anchor"].get("line", 1),
                )
            classes.append(ClassInfo(
                name=cd.get("name", "unknown"),
                anchor=c_anchor,
                end_line=cd.get("end_line", _HUGE_END),
                methods=methods,
                docstring=cd.get("docstring"),
                bases=cd.get("bases", []),
            ))

        modules[rel_path] = ModuleInfo(
            path=rel_path,
            language=language,
            functions=functions,
            classes=classes,
            imports=mod_data.get("imports", []),
            external_imports=mod_data.get("external_imports", []),
        )

    # Build call graph
    try:
        from services.call_graph import CallGraphBuilder
        builder = CallGraphBuilder(repo_path, ts_parser)
        cg = builder.build(modules)

        # Serialize
        from routes.scan import _call_graph_to_dict
        cg_dict = _call_graph_to_dict(cg)

        # Save for future requests
        _save_json("call_graph.json", cg_dict)

        logger.info("Call graph built on demand: %d callables, %d edges",
                     cg.total_callables, cg.total_edges)
        return cg_dict
    except Exception as e:
        logger.warning("On-demand call graph build failed: %s", e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Health Metrics
# ---------------------------------------------------------------------------

@metrics_router.get("/health", response_model=HealthResponse)
async def get_health_metrics():
    """
    Return project health dashboard metrics.

    Computes metrics from cached analysis results or triggers
    a lightweight on-demand computation.
    """
    # Try to load pre-computed metrics
    cached = _load_json("health_metrics.json")
    if cached:
        return cached

    # Fallback: compute from analysis.json
    analysis = _load_analysis()
    if not analysis:
        return {
            "total_modules": 0, "total_functions": 0, "total_classes": 0,
            "total_lines": 0, "avg_cyclomatic_complexity": 0,
            "health_score": None, "hotspots": [],
            "note": "尚未运行代码分析。请先在「分析」页面扫描仓库。",
        }

    try:
        from services.health_metrics import HealthMetricsCalculator
        modules_info = analysis.get("modules", {})

        # Build simplified module dict
        modules = {}
        dep_graph_data = analysis.get("dependency_graph", {})

        calc = HealthMetricsCalculator()
        health = calc.compute(
            modules={},  # ModuleInfo objects not available from JSON cache
            call_graph=None,
        )
        # Override with what we have from analysis.json
        health.total_modules = len(modules_info)
        health.total_lines = sum(
            m.get("total_lines", 0) for m in modules_info.values()
        )
        func_count = sum(
            len(m.get("functions", [])) + sum(
                len(c.get("methods", [])) for c in m.get("classes", [])
            )
            for m in modules_info.values()
        )
        class_count = sum(
            len(m.get("classes", [])) for m in modules_info.values()
        )
        health.total_functions = func_count
        health.total_classes = class_count

        # ---- Compute coupling from dependency graph ----
        dep_graph = analysis.get("dependency_graph", {})
        edges_list = dep_graph.get("edges", [])
        total_edges = sum(len(e.get("targets", [])) for e in edges_list)
        if func_count > 0:
            health.avg_coupling = round(total_edges / max(func_count, 1), 1)
        else:
            health.avg_coupling = 0
        health.max_coupling = max(
            (len(e.get("targets", [])) for e in edges_list), default=0
        )

        # ---- Estimate complexity from available data ----
        # Note: analysis.json may not include end_line for all functions.
        # Use signature-based heuristics as a more robust fallback.
        complexities = []
        for mod in modules_info.values():
            for fn in mod.get("functions", []):
                cc = 1.0
                if fn.get("docstring"):
                    cc += 1
                sig = fn.get("signature", "")
                if sig:
                    paren_start = sig.find("(")
                    paren_end = sig.find(")")
                    if paren_start >= 0 and paren_end > paren_start:
                        params_str = sig[paren_start + 1:paren_end].strip()
                        if params_str and params_str != "self":
                            cc += params_str.count(",") * 0.5 + 0.5
                complexities.append(cc)
            for cls in mod.get("classes", []):
                for method in cls.get("methods", []):
                    cc = 2.0
                    if method.get("docstring"):
                        cc += 1
                    sig = method.get("signature", "")
                    if sig:
                        paren_start = sig.find("(")
                        paren_end = sig.find(")")
                        if paren_start >= 0 and paren_end > paren_start:
                            params_str = sig[paren_start + 1:paren_end].strip()
                            if params_str and params_str not in ("self", "cls"):
                                real_params = [p for p in params_str.split(",") if p.strip() not in ("self", "cls")]
                                cc += len(real_params) * 0.5
                    complexities.append(cc)

        if complexities:
            health.avg_cyclomatic_complexity = round(
                sum(complexities) / len(complexities), 1
            )
            health.max_cyclomatic_complexity = int(max(complexities))

        # ---- Code smell detection ----
        long_funcs = 0
        many_params = 0
        god_classes = 0
        for m in modules_info.values():
            for fn in m.get("functions", []):
                end = fn.get("end_line", 0)
                line = (fn.get("anchor") or {}).get("line", 0)
                if end > 0 and line > 0 and (end - line) > 50:
                    long_funcs += 1
                if len(fn.get("args", [])) > 5:
                    many_params += 1
            for cls in m.get("classes", []):
                if len(cls.get("methods", [])) > 10:
                    god_classes += 1
                for method in cls.get("methods", []):
                    end = method.get("end_line", 0)
                    line = (method.get("anchor") or {}).get("line", 0)
                    if end > 0 and line > 0 and (end - line) > 50:
                        long_funcs += 1
                    if len(method.get("args", [])) > 5:
                        many_params += 1
        health.long_functions = long_funcs
        health.many_params_functions = many_params
        health.god_classes = god_classes

        # ---- Recompute health score with actual data ----
        health.overall_health_score = calc._compute_score(health)
        score_breakdown = calc._compute_breakdown(health)

        # ---- Additional metrics from analysis.json ----
        # Language breakdown
        language_breakdown: dict[str, int] = {}
        for m in modules_info.values():
            lang = m.get("language", "python")
            language_breakdown[lang] = language_breakdown.get(lang, 0) + 1

        # Docstring coverage (% of functions+methods that have a docstring)
        total_funcs_methods = 0
        docstring_count = 0
        for m in modules_info.values():
            for fn in m.get("functions", []):
                total_funcs_methods += 1
                if fn.get("docstring"):
                    docstring_count += 1
            for cls in m.get("classes", []):
                for method in cls.get("methods", []):
                    total_funcs_methods += 1
                    if method.get("docstring"):
                        docstring_count += 1
        docstring_coverage = round(docstring_count / max(total_funcs_methods, 1), 2)

        # External dependencies (unique)
        external_deps_set: set[str] = set()
        total_imports = 0
        for m in modules_info.values():
            for ext in m.get("external_imports", []):
                external_deps_set.add(ext)
            total_imports += len(m.get("imports", []))
        external_deps = len(external_deps_set)

        result = {
            "total_modules": health.total_modules,
            "total_functions": health.total_functions,
            "total_classes": health.total_classes,
            "total_lines": health.total_lines,
            "avg_cyclomatic_complexity": health.avg_cyclomatic_complexity,
            "max_cyclomatic_complexity": health.max_cyclomatic_complexity,
            "avg_coupling": health.avg_coupling,
            "max_coupling": health.max_coupling,
            "isolated_modules": health.isolated_modules,
            "test_coverage": health.test_coverage,
            "health_score": health.overall_health_score,
            "hotspots": health.risk_hotspots,
            "complex_functions": health.complex_functions,
            "language_breakdown": language_breakdown,
            "docstring_coverage": docstring_coverage,
            "external_deps": external_deps,
            "total_imports": total_imports,
            "score_breakdown": score_breakdown,
            "long_functions": health.long_functions,
            "many_params_functions": health.many_params_functions,
            "god_classes": health.god_classes,
        }
        return result
    except ImportError:
        return {
            "total_modules": len(analysis.get("modules", {})),
            "total_functions": 0, "total_classes": 0,
            "total_lines": 0, "health_score": 100,
            "note": "Install health_metrics module for full metrics",
        }


# ---------------------------------------------------------------------------
# Call Graph
# ---------------------------------------------------------------------------

@metrics_router.get("/call-graph")
async def get_call_graph(
    entity_id: Optional[str] = Query(None, description="Focus on this entity's subgraph"),
    max_depth: int = Query(2, ge=1, le=5, description="Maximum call depth"),
):
    """
    Return function-level call graph data for visualization.

    If entity_id is provided, returns a subgraph centered on that entity.
    Otherwise returns the full call graph summaries.
    """
    analysis = _load_analysis()
    if not analysis:
        return {"callables": {}, "edges": [], "unresolved": []}

    # Try to load call graph; build on demand if missing
    cg_data = _load_json("call_graph.json")
    if not cg_data:
        cg_data = _build_call_graph_on_demand()
    if not cg_data:
        return {
            "callables": {}, "edges": [],
            "note": "Call graph not yet built. Run a full scan first.",
        }

    if entity_id:
        # Filter to subgraph
        entity_ids = {entity_id}
        edge_list: list = []
        all_ids = set(cg_data.get("callables", {}).keys())

        for _ in range(max_depth):
            new_ids = set()
            for src, targets in cg_data.get("forward", {}).items():
                if src in entity_ids:
                    for tgt in targets:
                        edge_list.append({"source": src, "target": tgt})
                        new_ids.add(tgt)
            for src, targets in cg_data.get("reverse", {}).items():
                for tgt in targets:
                    if tgt in entity_ids:
                        edge_list.append({"source": src, "target": tgt})
                        new_ids.add(src)
            entity_ids |= new_ids

        return {
            "callables": {
                eid: cg_data["callables"][eid]
                for eid in entity_ids if eid in cg_data["callables"]
            },
            "edges": edge_list,
        }

    return cg_data


@metrics_router.get("/callers", response_model=CallersResponse)
async def get_callers(
    entity_id: str = Query(..., description="Entity ID: 'path/to/file.py::func_name'"),
    max_depth: int = Query(3, ge=1, le=10),
):
    """Return callers of a specific function (transitive)."""
    cg_data = _load_json("call_graph.json")
    if not cg_data:
        return {"callers": [], "note": "Call graph not yet built."}

    visited = set()
    queue = [entity_id]
    for _ in range(max_depth):
        current = queue.pop(0) if queue else None
        if current is None:
            break
        for caller in cg_data.get("reverse", {}).get(current, []):
            if caller not in visited:
                visited.add(caller)
                queue.append(caller)

    return {
        "entity_id": entity_id,
        "callers": sorted(visited),
        "count": len(visited),
    }


# ---------------------------------------------------------------------------
# Taint Analysis
# ---------------------------------------------------------------------------

@metrics_router.get("/taint", response_model=TaintResponse)
async def get_taint_analysis():
    """Return taint analysis results (source→sink flows)."""
    taint_data = _load_json("taint_analysis.json")
    if not taint_data:
        return {"flows": [], "note": "Run analysis first to detect taint flows."}
    return taint_data


# ---------------------------------------------------------------------------
# Impact Analysis
# ---------------------------------------------------------------------------

@metrics_router.get("/impact", response_model=ImpactResponse)
async def get_impact_analysis(
    changed_files: Optional[str] = Query(None, description="Comma-separated file paths"),
):
    """
    Estimate impact of changes on given files.
    Uses call graph if available.
    """
    files = [f.strip() for f in (changed_files or "").split(",") if f.strip()]
    if not files:
        return {
            "risk_score": 0.0, "changed_functions": [],
            "affected_production": [], "affected_tests": [],
            "summary": "请输入要分析的文件路径。",
        }

    from services.impact_service import ImpactService
    svc = ImpactService(_get_repo())
    return svc.analyze(files)

    try:
        from services.impact_analyzer import ImpactAnalyzer
        from services.call_graph import CallGraphBuilder
        from models.entities import CallGraphData, CallableEntity, SourceAnchor

        # Reconstruct CallGraphData from JSON
        callables = {
            eid: CallableEntity(
                id=eid, name=info.get("name", ""),
                module=info.get("module", ""),
                parent_class=info.get("parent_class"),
                kind=info.get("kind", "function"),
            )
            for eid, info in cg_data.get("callables", {}).items()
        }
        call_graph = CallGraphData(
            callables=callables,
            forward=cg_data.get("forward", {}),
            reverse=cg_data.get("reverse", {}),
            unresolved_calls=[],
        )

        # ImpactAnalyzer needs a CallGraphBuilder for helper methods
        class DummyBuilder:
            def transitive_callers(self, eid, cg, max_depth=5):
                visited = set()
                queue = [eid]
                for _ in range(max_depth):
                    if not queue:
                        break
                    cur = queue.pop(0)
                    for caller in cg.reverse.get(cur, []):
                        if caller not in visited:
                            visited.add(caller)
                            queue.append(caller)
                return visited

            def find_call_path(self, from_id, to_id, cg, max_depth=8):
                if from_id == to_id:
                    return [from_id]
                visited = {from_id}
                q = [(from_id, [from_id])]
                while q:
                    cur, path = q.pop(0)
                    if len(path) > max_depth:
                        continue
                    for callee in cg.forward.get(cur, []):
                        if callee == to_id:
                            return path + [callee]
                        if callee not in visited:
                            visited.add(callee)
                            q.append((callee, path + [callee]))
                return None

        analyzer = ImpactAnalyzer(DummyBuilder())
        report = analyzer.analyze(files, call_graph)
        return {
            "changed_files": report.changed_files,
            "changed_functions": report.changed_functions,
            "affected_production": [
                {"name": e.name, "module": e.module, "distance": e.distance}
                for e in report.affected_production
            ],
            "affected_tests": [
                {"name": e.name, "module": e.module, "distance": e.distance}
                for e in report.affected_tests
            ],
            "risk_score": report.risk_score,
            "summary": report.summary,
        }
    except ImportError as e:
        return {"risk_score": 0.0, "error": str(e)}


# ---------------------------------------------------------------------------
# Semantic Code Search
# ---------------------------------------------------------------------------

@search_router.get("/pattern", response_model=SearchResponse)
async def search_pattern(
    pattern: str = Query("", description="Pattern name (see list) or custom regex"),
    list_patterns: bool = Query(False, description="List available patterns"),
    query: Optional[str] = Query(None, description="Custom regex query (overrides pattern)"),
):
    """
    Search code using pre-defined patterns or custom regex.

    Available patterns: env_read_py, env_read_ts, sql_query, http_request,
    file_write, exception_handling, async_pattern, use_state, decorator_pattern
    """
    if list_patterns:
        try:
            from services.code_search import CodePatternSearch
            cs = CodePatternSearch()
            return {"patterns": cs.list_patterns()}
        except ImportError:
            return {"patterns": []}

    analysis = _load_analysis()
    if not analysis:
        return {"results": [], "note": "尚未运行代码分析。请先在「分析」页面扫描仓库。"}

    repo_path = get_config().get("repo_path", "")
    if not repo_path or not os.path.isdir(repo_path):
        return {"results": [], "note": f"仓库路径不可访问: {repo_path}"}

    try:
        from services.code_search import CodePatternSearch

        cs = CodePatternSearch()
        file_paths = list(analysis.get("modules", {}).keys())
        if not file_paths:
            return {"results": [], "note": "分析数据中没有模块信息。"}

        if query:
            results = cs.search_custom_by_paths(repo_path, file_paths, query)
            return {"results": results, "query": query, "count": len(results)}

        results = cs.search_by_paths(repo_path, file_paths, pattern)
        return {"results": results, "pattern": pattern, "count": len(results)}
    except ImportError:
        return {"results": [], "error": "code_search module not available"}


# ---------------------------------------------------------------------------
# CFG (Control Flow Graph)
# ---------------------------------------------------------------------------

@metrics_router.get("/cfg", response_model=CFGResponse)
async def get_cfg(
    file: str = Query(..., description="Relative file path, e.g. services/auth.py"),
    function: str = Query(..., description="Function name to generate CFG for"),
):
    """
    Return Control Flow Graph for a specific function as JSON + Mermaid.
    """
    from services.cfg_service import CFGService
    cfg_config = get_config()
    repo_path = cfg_config.get("repo_path", "")
    if not repo_path:
        return {"error": "No repository configured. Please set repo_path in settings."}

    svc = CFGService()
    return svc.generate(repo_path, file, function)


@metrics_router.get("/icfg", response_model=dict)
async def get_icfg(
    function: str = Query(..., description="Function name to generate ICFG for"),
    file: str = Query("", description="Optional relative file path to disambiguate"),
):
    """Return Interprocedural CFG using call graph data."""
    from services.cfg_service import ICFGService
    cfg_config = get_config()
    repo_path = cfg_config.get("repo_path", "")
    if not repo_path:
        return {"error": "No repository configured. Please set repo_path in settings."}

    svc = ICFGService()
    return svc.generate(repo_path, function, file)


# ---------------------------------------------------------------------------
# Impact helpers
# ---------------------------------------------------------------------------

def _impact_from_call_graph(cg_data: dict, files: List[str]) -> dict:
    """Use full call graph for impact analysis."""
    try:
        from models.entities import CallGraphData, CallableEntity

        callables = {
            eid: CallableEntity(
                id=eid, name=info.get("name", ""),
                module=info.get("module", ""),
                parent_class=info.get("parent_class"),
                kind=info.get("kind", "function"),
            )
            for eid, info in cg_data.get("callables", {}).items()
        }
        cg = CallGraphData(
            callables=callables,
            forward=cg_data.get("forward", {}),
            reverse=cg_data.get("reverse", {}),
            unresolved_calls=[],
        )

        changed_fns = [
            eid for eid, e in callables.items()
            if e.module in files
        ]

        if not changed_fns:
            return {
                "risk_score": 0.0,
                "changed_functions": [],
                "affected_production": [],
                "affected_tests": [],
                "summary": "未在变更文件中找到函数调用关系。",
            }

        # Find transitive callers
        all_affected = set()
        for fn_id in changed_fns:
            queue = [fn_id]
            depth = 0
            while queue and depth < 5:
                cur = queue.pop(0)
                for caller in cg.reverse.get(cur, []):
                    if caller not in all_affected and caller not in changed_fns:
                        all_affected.add(caller)
                        queue.append(caller)
                depth += 1

        prod = []
        tests = []
        for eid in all_affected:
            e = callables.get(eid)
            if e:
                entry = {"name": e.name, "module": e.module, "distance": 1}
                if "test" in e.module.lower() or e.module.startswith("test"):
                    tests.append(entry)
                else:
                    prod.append(entry)

        risk = min(1.0, len(all_affected) * 0.08)
        return {
            "risk_score": round(risk, 2),
            "changed_functions": [c.split("::")[-1] for c in changed_fns[:10]],
            "affected_production": prod[:20],
            "affected_tests": tests[:10],
            "summary": f"变更 {len(files)} 个文件({len(changed_fns)} 个函数)，影响 {len(prod)} 个生产函数 + {len(tests)} 个测试。",
        }
    except Exception as e:
        return {"risk_score": 0.0, "summary": f"分析出错: {e}"}


def _impact_from_dep_graph(analysis: dict, files: List[str]) -> dict:
    """Use dependency graph as fallback for impact analysis."""
    modules = analysis.get("modules", {})
    dep = analysis.get("dependency_graph", {})
    edges = dep.get("edges", [])

    # Find which files import the changed files
    changed_set = set(files)
    affected_modules = set()
    for edge in edges:
        src = edge.get("source", "")
        targets = edge.get("targets", [])
        for tgt in targets:
            if tgt in changed_set:
                affected_modules.add(src)

    # Count functions in changed + affected modules
    changed_funcs = []
    for f in files:
        mod = modules.get(f, {})
        for fn in mod.get("functions", []):
            changed_funcs.append(fn.get("name", "?"))
        for cls in mod.get("classes", []):
            for m in cls.get("methods", []):
                changed_funcs.append(f"{cls.get('name', '?')}.{m.get('name', '?')}")

    affected_prod = []
    for m in affected_modules:
        affected_prod.append({"name": m, "module": m, "distance": 1})

    risk = min(1.0, len(affected_modules) * 0.1)
    return {
        "risk_score": round(risk, 2),
        "changed_functions": changed_funcs[:10],
        "affected_production": [{"name": m, "module": m, "distance": 1} for m in sorted(affected_modules)[:20]],
        "affected_tests": [],
        "summary": f"变更 {len(files)} 文件，影响 {len(affected_modules)} 个依赖模块 (基于依赖图分析)。",
    }
