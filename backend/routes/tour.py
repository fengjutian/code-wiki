"""
Guided Tour — BFS from entry points through dependency graph,
generating a structured learning path for new developers.

Endpoint:
  GET /api/tour  — project learning tour (5-15 steps, BFS-ordered)
"""

import json
import logging
from collections import defaultdict, deque
from pathlib import Path

from fastapi import APIRouter

from config import get_wiki_path

logger = logging.getLogger("code-wiki.tour")

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_analysis() -> dict | None:
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
    if p.startswith(("routes/", "routers/", "controllers/", "views/", "api/", "endpoints/")): return "接口层"
    if p.startswith(("services/", "service/", "use_cases/", "usecases/", "core/", "domain/")): return "服务层"
    if p.startswith(("models/", "model/", "entities/", "schemas/", "domain/", "dal/", "repositories/", "repository/")): return "数据层"
    if p.startswith(("utils/", "util/", "helpers/", "common/", "lib/", "shared/")): return "工具层"
    if p.startswith(("config/", "settings/", "main.", "app.", "index.", "__init__", "manage.", "run.")): return "配置/入口"
    if p.startswith(("tests/", "test/", "spec/", "__tests__/")): return "测试"
    if p.startswith(("migrations/", "alembic/", "db/")): return "数据库迁移"
    if p.startswith(("frontend/", "src/", "components/", "pages/", "app/", "store/", "hooks/")): return "前端"
    if p.startswith((".github/", ".circleci/", "docker", "Dockerfile", "terraform/", "k8s/")): return "基础设施"
    return "其他"


def _find_entry_points(modules: dict, edges: list) -> list[str]:
    """Identify entry-point files via multiple heuristics."""
    scores: dict[str, int] = {}
    has_incoming = set()
    for edge in edges:
        for tgt in edge.get("targets", []):
            has_incoming.add(tgt)

    for path, mod in modules.items():
        p = path.replace("\\", "/").lower()
        score = 0
        if p in ("main.py", "app.py", "index.py", "manage.py", "run.py", "server.py", "__init__.py"):
            score += 5
        if p.endswith("/__init__.py") and not p.startswith(("tests/", "test/")):
            score += 2
        if path not in has_incoming and not p.startswith(("alembic/", "migrations/", "tests/", "test/")):
            score += 1
        ext_imports = str(mod.get("external_imports", [])).lower()
        if any(fw in ext_imports for fw in ("fastapi", "flask", "django", "express", "next")):
            score += 3
        if score >= 2:
            scores[path] = score

    return [p for p, _ in sorted(scores.items(), key=lambda x: -x[1])[:5]]


def _build_adjacency(edges: list) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build forward (A→B) and reverse (B←A) adjacency from dependency edges."""
    forward: dict[str, list[str]] = defaultdict(list)
    reverse: dict[str, list[str]] = defaultdict(list)

    for edge in edges:
        src = edge["source"]
        for tgt in edge.get("targets", []):
            forward[src].append(tgt)
            reverse[tgt].append(src)

    return dict(forward), dict(reverse)


def _build_tour(modules: dict, entry_points: list[str], forward: dict[str, list[str]], reverse: dict[str, list[str]]) -> list[dict]:
    """BFS from entry points, ordered by fan-in, up to 15 steps."""
    visited: set[str] = set()
    queue = deque(entry_points)
    steps: list[dict] = []
    depth_map: dict[str, int] = {}

    for ep in entry_points:
        depth_map[ep] = 0

    while queue and len(steps) < 15:
        current = queue.popleft()
        if current in visited or current not in modules:
            continue
        visited.add(current)
        depth = depth_map.get(current, 0)

        mod = modules[current]
        deps = forward.get(current, [])
        dependents = reverse.get(current, [])

        # Count entities
        classes = len(mod.get("classes", []))
        functions = len(mod.get("functions", []))
        entity_count = classes + functions

        # Generate auto-description
        desc = _auto_describe(current, mod, deps, dependents, depth)

        steps.append({
            "step": len(steps) + 1,
            "depth": depth,
            "path": current,
            "layer": _classify(current),
            "entity_count": entity_count,
            "classes": classes,
            "functions": functions,
            "language": mod.get("language", "python"),
            "dependencies": deps[:8],
            "dependents_count": len(dependents),
            "description": desc,
        })

        # Enqueue children, prioritized by fan-in (most dependents first)
        children = []
        for dep in deps:
            if dep not in visited and dep in modules:
                fan_in = len(reverse.get(dep, []))
                children.append((fan_in, dep))

        children.sort(reverse=True)  # highest fan-in first
        for _, child in children:
            if child not in depth_map:
                depth_map[child] = depth + 1
            queue.append(child)

    return steps


def _auto_describe(path: str, mod: dict, deps: list, dependents: list, depth: int) -> str:
    """Auto-generate a human-readable description for a module."""
    layer = _classify(path)
    classes = mod.get("classes", [])
    functions = mod.get("functions", [])
    external = mod.get("external_imports", [])

    parts = [f"**{Path(path).name}** — {layer}"]

    if classes:
        names = [c["name"] for c in classes[:3]]
        remaining = f" 等{len(classes)}个类" if len(classes) > 3 else ""
        parts.append(f"定义了 {', '.join(names)}{remaining}")

    if functions:
        names = [f["name"] for f in functions[:3]]
        remaining = f" 等{len(functions)}个函数" if len(functions) > 3 else ""
        parts.append(f"包含 {', '.join(names)}{remaining}")

    if depth == 0:
        parts.append("——项目入口文件，从这里开始理解系统。")
    elif dependents:
        count = len(dependents)
        if count >= 10:
            parts.append(f"——被 {count} 个模块依赖，是系统的核心模块。")
        elif count >= 3:
            parts.append(f"——被 {count} 个模块引用。")

    if deps:
        parts.append(f"依赖 {', '.join(deps[:3])}" + ("..." if len(deps) > 3 else ""))

    if external:
        libs = external[:4]
        parts.append(f"使用外部库: {', '.join(libs)}")

    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Tour endpoint
# ---------------------------------------------------------------------------

@router.get("/tour")
async def get_tour():
    """Return a BFS-ordered guided tour (5-15 steps) for the project."""
    analysis = _load_analysis()
    if not analysis:
        return {
            "status": "no_data",
            "message": "尚未运行分析，无法生成导览。请先在「分析」模块配置仓库并运行扫描。",
        }

    modules = analysis.get("modules", {})
    dep_edges = analysis.get("dependency_graph", {}).get("edges", [])

    entry_points = _find_entry_points(modules, dep_edges)
    if not entry_points:
        return {"status": "no_entry", "message": "未找到明确的入口文件，请确认项目结构。", "steps": []}

    forward, reverse = _build_adjacency(dep_edges)
    steps = _build_tour(modules, entry_points, forward, reverse)

    total_entities = sum(s["entity_count"] for s in steps)
    max_depth = max((s["depth"] for s in steps), default=0)

    return {
        "status": "ok",
        "entry_points": entry_points,
        "total_steps": len(steps),
        "total_entities_covered": total_entities,
        "max_depth": max_depth,
        "steps": steps,
    }
