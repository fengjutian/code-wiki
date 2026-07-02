"""
Onboarding Guide — auto-generated newcomer guide from analysis data.

Endpoint:
  GET /api/guide  — project overview, entry points, architecture summary
"""

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Optional

from fastapi import APIRouter

from config import get_wiki_path, get_config

logger = logging.getLogger("code-wiki.guide")

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_analysis() -> dict | None:
    """Load analysis.json (check .code-wiki/ and parent dir)."""
    try:
        wiki = get_wiki_path()
        path = wiki / "analysis.json"
        if not path.exists():
            parent_path = wiki.parent / "analysis.json"
            if parent_path.exists():
                path = parent_path
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("Failed to load analysis.json: %s", e)
    return None


def _classify(path: str) -> str:
    """Classify a module path into an architectural layer."""
    p = path.replace("\\", "/").lower()
    if p.startswith(("routes/", "routers/", "controllers/", "views/")): return "接口层"
    if p.startswith(("services/", "service/", "use_cases/", "usecases/")): return "服务层"
    if p.startswith(("models/", "model/", "entities/", "schemas/", "domain/")): return "数据层"
    if p.startswith(("utils/", "utils/", "helpers/", "common/", "lib/")): return "工具层"
    if p.startswith(("config/", "settings/", "main.", "app.", "index.", "__init__")): return "配置/入口"
    if p.startswith(("tests/", "test/")): return "测试"
    if p.startswith(("migrations/", "alembic/")): return "数据库迁移"
    if p.startswith(("frontend/", "src/", "components/", "pages/")): return "前端"
    return "其他"


def _find_entry_points(modules: dict, dep_edges: list) -> list[dict]:
    """Find likely entry-point files."""
    entries = []
    # Files with incoming deps
    has_incoming = set()
    for edge in dep_edges:
        for tgt in edge.get("targets", []):
            has_incoming.add(tgt)

    for path, mod in modules.items():
        p = path.replace("\\", "/").lower()
        score = 0
        reasons = []
        # Heuristics
        if p in ("main.py", "app.py", "index.py", "manage.py", "run.py", "server.py"):
            score += 3
            reasons.append("标准入口文件名")
        if p.endswith(("/__init__.py", "/__main__.py")):
            score += 1
            reasons.append("包入口")
        if not has_incoming or path not in has_incoming:
            # No other module imports this — likely top-level
            if not p.startswith(("alembic/", "migrations/", "tests/", "test/")):
                score += 1
                reasons.append("无其他模块依赖此文件")
        if "fastapi" in str(mod.get("external_imports", [])).lower() or \
           "flask" in str(mod.get("external_imports", [])).lower():
            score += 2
            reasons.append("Web 框架入口")
        if p.startswith(("backend/", "src/")) and p.endswith(("/__init__.py", "/main.py", "/app.py")):
            score += 1

        if score >= 2:
            entries.append({
                "path": path,
                "score": score,
                "reasons": reasons,
                "language": mod.get("language", "python"),
                "entity_count": (len(mod.get("classes", [])) + len(mod.get("functions", []))),
            })

    entries.sort(key=lambda e: e["score"], reverse=True)
    return entries[:8]


def _directory_tree(modules: dict) -> list[dict]:
    """Build a simplified directory tree from module paths."""
    dirs: dict[str, dict] = {}
    for path in modules:
        parts = Path(path).parts
        current = dirs
        for part in parts:
            if part not in current:
                current[part] = {}
            current = current[part]

    def _to_list(node: dict, prefix: str = "") -> list[dict]:
        result = []
        for name, children in sorted(node.items()):
            full = f"{prefix}/{name}" if prefix else name
            result.append({
                "name": name,
                "path": full,
                "is_dir": bool(children),
                "children": _to_list(children, full) if children else [],
            })
        return result

    return _to_list(dirs)


# ---------------------------------------------------------------------------
# Guide endpoint
# ---------------------------------------------------------------------------

@router.get("/guide")
async def get_guide():
    """Return an auto-generated onboarding guide for the current project."""
    analysis = _load_analysis()
    if not analysis:
        return {
            "status": "no_data",
            "message": "尚未运行分析，无法生成上手指南。请先在「分析」模块配置仓库并运行扫描。",
        }

    modules = analysis.get("modules", {})
    dep_graph = analysis.get("dependency_graph", {})
    dep_edges = dep_graph.get("edges", [])
    dep_stats = dep_graph.get("stats", {})

    # 1. Project overview
    languages = Counter(m.get("language", "python") for m in modules.values())
    total_classes = sum(len(m.get("classes", [])) for m in modules.values())
    total_functions = sum(len(m.get("functions", [])) for m in modules.values())
    total_interfaces = sum(len(m.get("interfaces", [])) for m in modules.values())
    total_components = sum(len(m.get("components", [])) for m in modules.values())

    overview = {
        "analyzed_at": analysis.get("analyzed_at", ""),
        "total_files": len(modules),
        "total_classes": total_classes,
        "total_functions": total_functions,
        "total_interfaces": total_interfaces,
        "total_components": total_components,
        "total_entities": total_classes + total_functions + total_interfaces + total_components,
        "languages": {k: v for k, v in languages.most_common()},
        "dependency_edges": dep_stats.get("total_edges", 0),
        "max_dependency_depth": dep_stats.get("max_depth", 0),
    }

    # 2. Entry points
    entry_points = _find_entry_points(modules, dep_edges)

    # 3. Architecture layers
    layer_counts = Counter()
    layer_modules: dict[str, list[str]] = {}
    for path in modules:
        layer = _classify(path)
        layer_counts[layer] += 1
        layer_modules.setdefault(layer, []).append(path)

    architecture = {
        "layers": [
            {"name": name, "file_count": count, "top_modules": layer_modules[name][:5]}
            for name, count in layer_counts.most_common()
        ],
    }

    # 4. Core modules (most depended-on)
    incoming_count = Counter()
    for edge in dep_edges:
        for tgt in edge.get("targets", []):
            incoming_count[tgt] += 1
    core_modules = [
        {"path": path, "dependents": count, "layer": _classify(path)}
        for path, count in incoming_count.most_common(10)
    ]

    # 5. Directory structure (top 2 levels)
    tree = _directory_tree(modules)
    # Truncate to top-level dirs with counts
    dir_summary = []
    for d in tree:
        if d["is_dir"]:
            total = sum(1 for m in modules if m.startswith(d["path"] + "/") or m.startswith(d["path"] + "\\"))
            dir_summary.append({"name": d["name"], "path": d["path"], "file_count": total})
    dir_summary.sort(key=lambda x: x["file_count"], reverse=True)

    return {
        "status": "ok",
        "overview": overview,
        "entry_points": entry_points,
        "architecture": architecture,
        "core_modules": core_modules,
        "directory_summary": dir_summary[:20],
    }
