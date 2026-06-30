"""
Interactive knowledge graph endpoint — nodes + edges for Cytoscape.js rendering.

Returns dependency-graph data from analysis.json in a format ready for
frontend graph visualization libraries.
"""

import json
import logging
from fastapi import APIRouter

from config import get_wiki_path

logger = logging.getLogger("code-wiki.graph")

router = APIRouter()

# ---- Layout palettes ----
LAYER_COLORS = {
    "routes":     "#0288d1",  # blue
    "services":   "#388e3c",  # green
    "models":     "#f57c00",  # orange
    "frontend":   "#7b1fa2",  # purple
    "config":     "#c62828",  # red
    "other":      "#616161",  # grey
}
LAYER_ORDER = ["routes", "services", "models", "frontend", "config", "other"]


def _classify_layer(path: str) -> str:
    """Map a module path to a conceptual layer for color-coding."""
    norm = path.replace("\\", "/")
    if norm.startswith("routes/"):
        return "routes"
    if norm.startswith("services/"):
        return "services"
    if norm.startswith("models/"):
        return "models"
    if norm.startswith("src/") or "frontend" in norm.lower():
        return "frontend"
    if norm.startswith("config") or norm.startswith("main"):
        return "config"
    return "other"


def _load_analysis() -> dict | None:
    """Load saved analysis.json, or None if unavailable."""
    try:
        path = get_wiki_path() / "analysis.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load analysis.json: {e}")
    return None


@router.get("/graph/data")
async def get_graph_data():
    """
    Return knowledge-graph data for Cytoscape.js.

    Response shape:
        {
          "nodes": [
            {"id": "services/user.py", "label": "services/user.py",
             "layer": "services", "color": "#388e3c",
             "entityCount": 5, "language": "python"},
            ...
          ],
          "edges": [
            {"source": "routes/scan.py", "target": "services/scanner.py",
             "type": "imports"},
            ...
          ]
        }
    """
    data = _load_analysis()
    if not data:
        return {"nodes": [], "edges": []}

    modules = data.get("modules", {})
    dep_graph = data.get("dependency_graph", {})
    edge_list = dep_graph.get("edges", [])

    # Build nodes
    nodes = []
    for path in sorted(modules.keys()):
        mod = modules[path]
        layer = _classify_layer(path)
        nodes.append({
            "id": path,
            "label": path.replace("\\", "/"),
            "layer": layer,
            "color": LAYER_COLORS.get(layer, LAYER_COLORS["other"]),
            "entityCount": (
                len(mod.get("classes", []))
                + len(mod.get("functions", []))
                + len(mod.get("interfaces", []))
                + len(mod.get("components", []))
            ),
            "language": mod.get("language", "python"),
        })

    # Build edges
    edges = []
    seen = set()
    for edge in edge_list:
        src = edge.get("source", "")
        for tgt in edge.get("targets", []):
            key = f"{src}→{tgt}"
            if key not in seen and src in modules and tgt in modules:
                seen.add(key)
                edges.append({
                    "source": src,
                    "target": tgt,
                    "type": "imports",
                })

    return {"nodes": nodes, "edges": edges}
