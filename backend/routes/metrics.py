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

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict

from fastapi import APIRouter, Query

from config import get_wiki_path, get_config, load_config_from_disk
from models.entities import SupportedLanguage, SourceAnchor

logger = logging.getLogger("code-wiki.metrics")

router = APIRouter()
metrics_router = APIRouter()     # /api/metrics/*
search_router = APIRouter()       # /api/search/*


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_analysis() -> dict | None:
    """Load saved analysis.json from .code-wiki directory (or parent as fallback)."""
    try:
        wiki = get_wiki_path()
        path = wiki / "analysis.json"
        if not path.exists():
            # Fallback: check parent directory (legacy analysis.json location)
            parent_path = wiki.parent / "analysis.json"
            if parent_path.exists():
                path = parent_path
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("Failed to load analysis.json: %s", e)
    return None


def _load_json(filename: str) -> Optional[dict]:
    """Load a JSON file from .code-wiki directory."""
    try:
        path = get_wiki_path() / filename
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _save_json(filename: str, data: dict):
    """Save a JSON file to .code-wiki directory."""
    path = get_wiki_path() / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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

@metrics_router.get("/health")
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
            "health_score": 100, "hotspots": [],
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


@metrics_router.get("/callers")
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

@metrics_router.get("/taint")
async def get_taint_analysis():
    """Return taint analysis results (source→sink flows)."""
    taint_data = _load_json("taint_analysis.json")
    if not taint_data:
        return {"flows": [], "note": "Run analysis first to detect taint flows."}
    return taint_data


# ---------------------------------------------------------------------------
# Impact Analysis
# ---------------------------------------------------------------------------

@metrics_router.get("/impact")
async def get_impact_analysis(
    changed_files: Optional[str] = Query(None, description="Comma-separated file paths"),
):
    """
    Estimate impact of changes on given files.
    If changed_files is omitted, returns impact for the most recent scan diff.
    """
    files = [f.strip() for f in (changed_files or "").split(",") if f.strip()]

    cg_data = _load_json("call_graph.json")
    if not cg_data or not files:
        return {
            "risk_score": 0.0,
            "affected_production": [],
            "affected_tests": [],
            "summary": "No call graph data or no changed files specified.",
        }

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

@search_router.get("/pattern")
async def search_pattern(
    pattern: str = Query(..., description="Pattern name (see list) or custom regex"),
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
        return {"results": [], "note": "No analysis data available."}

    try:
        from services.code_search import CodePatternSearch
        cs = CodePatternSearch()

        if query:
            results = cs.search_custom(
                modules={},  # ModuleInfo not available from JSON
                query=query,
            )
            return {"results": results, "query": query, "count": len(results)}

        results = cs.search(modules={}, pattern_name=pattern)
        return {"results": results, "pattern": pattern, "count": len(results)}
    except ImportError:
        return {"results": [], "error": "code_search module not available"}
