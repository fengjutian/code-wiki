"""Mermaid diagram endpoints — real diagrams from analysis data."""

import json
import logging
import os
import re
from pathlib import Path
from fastapi import APIRouter

from config import _config, get_wiki_path

logger = logging.getLogger("code-wiki.diagrams")

router = APIRouter()


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


def _load_mmd(name: str) -> str | None:
    """Load a pre-generated .mmd file from wiki_path/diagrams/."""
    try:
        path = get_wiki_path() / "diagrams" / name
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to load {name}: {e}")
    return None


def _sanitize_label(text: str) -> str:
    """Escape special chars for Mermaid labels inside quotes.
    Preserves <br/> tags (Mermaid line breaks) during sanitization.
    """
    # Protect Mermaid line break markers
    text = text.replace("<br/>", "\x00BR\x00")
    result = (
        text.replace('"', "'")
        .replace("[", "(")
        .replace("]", ")")
        .replace("{", "(")
        .replace("}", ")")
        .replace("<", "⟨")
        .replace(">", "⟩")
        .replace("&", "＆")
        .replace("#", "＃")
        .replace("\n", " ")
    )
    return result.replace("\x00BR\x00", "<br/>")


def _sanitize_identifier(text: str) -> str:
    """Make a string safe for use as a Mermaid bare identifier (no quotes).
    Strips generic parameters and special chars."""
    # Strip generic type params: Generic[T] → Generic, List[int] → List
    # Also handle Foo<T>, Foo(T), Foo(int)
    text = re.sub(r'[\[\(<].*[\]\)>]$', '', text.strip())
    # Replace remaining dangerous chars with underscores
    return re.sub(r'[^a-zA-Z0-9_À-ÿ]', '_', text)


# ── Architecture diagram ──────────────────────────────────────────────────


def _build_architecture_mermaid(data: dict) -> str:
    """Generate a multi-layer architecture Mermaid diagram from analysis data."""
    modules = data.get("modules", {})
    lines = ["graph TB"]

    # Categorise modules by layer
    layers = {
        "routes": [],
        "services": [],
        "models": [],
        "frontend_src": [],
        "other": [],
    }

    for path in modules:
        norm = path.replace("\\", "/")
        if norm.startswith("routes/"):
            layers["routes"].append(path)
        elif norm.startswith("services/"):
            layers["services"].append(path)
        elif norm.startswith("models/"):
            layers["models"].append(path)
        elif norm.startswith("src/"):
            layers["frontend_src"].append(path)
        else:
            layers["other"].append(path)

    layer_colors = {
        "routes": {"fill": "#e1f5fe", "stroke": "#0288d1"},
        "services": {"fill": "#e8f5e9", "stroke": "#388e3c"},
        "models": {"fill": "#fff3e0", "stroke": "#f57c00"},
        "frontend_src": {"fill": "#f3e5f5", "stroke": "#7b1fa2"},
        "other": {"fill": "#f5f5f5", "stroke": "#616161"},
    }

    node_id_map = {}

    def _node_id(path: str) -> str:
        if path not in node_id_map:
            node_id_map[path] = f"N{len(node_id_map)}"
        return node_id_map[path]

    for layer_name, layer_paths in layers.items():
        if not layer_paths:
            continue
        colors = layer_colors.get(layer_name, layer_colors["other"])
        safe_name = layer_name.replace("-", "_")
        lines.append(f'    subgraph {safe_name}["{layer_name}"]')
        lines.append(
            f'        style {safe_name} fill:{colors["fill"]},stroke:{colors["stroke"]}'
        )
        for path in layer_paths:
            nid = _node_id(path)
            label = path.replace("\\", "/").rsplit(".", 1)[0]
            lines.append(f'        {nid}["{_sanitize_label(label)}"]')
        lines.append("    end")

    # Draw dependency edges between layers
    dep_graph = data.get("dependency_graph", {})
    edges = dep_graph.get("edges", [])
    drawn = set()
    for edge in edges:
        src = edge.get("source", "")
        for tgt in edge.get("targets", []):
            if src in node_id_map and tgt in node_id_map:
                key = f"{src}->{tgt}"
                if key not in drawn:
                    drawn.add(key)
                    lines.append(f"    {_node_id(src)} --> {_node_id(tgt)}")

    return "\n".join(lines)


# ── Class diagram ─────────────────────────────────────────────────────────


def _build_class_mermaid(data: dict) -> str:
    """Generate a Mermaid classDiagram from analyzed classes (truncated for readability)."""
    modules = data.get("modules", {})
    dep_graph = data.get("dependency_graph", {})
    edge_list = dep_graph.get("edges", [])

    # Rank modules by total dependency count (imports + imported-by)
    deps_of: dict[str, int] = {}
    for edge in edge_list:
        src = edge.get("source", "")
        targets = edge.get("targets", [])
        deps_of[src] = deps_of.get(src, 0) + len(targets)
        for tgt in targets:
            deps_of[tgt] = deps_of.get(tgt, 0) + 1

    # Sort modules by dependency rank, take top N
    MAX_MODULES = 30
    ranked = sorted(deps_of.items(), key=lambda x: -x[1])
    top_paths = set(p for p, _ in ranked[:MAX_MODULES])

    # Also include modules that directly connect to the top set
    for edge in edge_list:
        src = edge.get("source", "")
        for tgt in edge.get("targets", []):
            if src in top_paths and tgt not in top_paths:
                if len(top_paths) < MAX_MODULES + 20:
                    top_paths.add(tgt)
            if tgt in top_paths and src not in top_paths:
                if len(top_paths) < MAX_MODULES + 20:
                    top_paths.add(src)

    lines = ["classDiagram"]
    lines.append(f'    note "Showing {min(len(top_paths), MAX_MODULES + 20)} of {len(modules)} modules (ranked by dependency weight)"')

    # Collect classes from top modules
    all_classes: dict[str, dict] = {}
    MAX_CLASSES_PER_MODULE = 8
    MAX_METHODS_PER_CLASS = 6

    for path in sorted(top_paths):
        mod = modules.get(path)
        if not mod:
            continue
        for cls in mod.get("classes", [])[:MAX_CLASSES_PER_MODULE]:
            name = cls.get("name", "Unknown")
            if name in all_classes:
                prefix = path.replace("/", ".").replace("\\", ".")
                name = f"{prefix}.{name}"
            all_classes[name] = {
                "module": path,
                "bases": cls.get("bases", []),
                "methods": cls.get("methods", [])[:MAX_METHODS_PER_CLASS],
                "docstring": (cls.get("docstring", "") or "")[:80],
            }

    # Render classes
    for cls_name, cls_data in all_classes.items():
        safe_name = _sanitize_identifier(cls_name.replace(".", "_").replace("/", "_"))
        lines.append(f"    class {safe_name} {{")
        if cls_data["docstring"]:
            doc_first_line = _sanitize_label(cls_data["docstring"].split("\n")[0])
            lines.append(f"        +『{doc_first_line}』")
        for method in cls_data.get("methods", []):
            sig = method.get("signature", method.get("name", "?"))
            if not sig.endswith(")"):
                sig += "()"
            lines.append(f"        +{_sanitize_label(sig)}")
        lines.append("    }")

        # Inheritance
        for base in cls_data["bases"]:
            safe_base = _sanitize_identifier(base)
            if safe_base and safe_base != "_":
                lines.append(f"    {safe_name} --|> {safe_base}")

    # Cross-module edges (only between visible classes)
    for path in sorted(top_paths):
        mod = modules.get(path)
        if not mod:
            continue
        source_class_names = [c.get("name", "") for c in mod.get("classes", [])[:MAX_CLASSES_PER_MODULE]]
        for imp in mod.get("imports", []):
            imp_norm = imp.replace(".", "/")
            for imp_path in top_paths:
                if imp_path == path:
                    continue
                if imp_norm in imp_path.replace("\\", "/") or imp_path.replace("\\", "/").startswith(imp_norm.replace(".", "/")):
                    imp_mod = modules.get(imp_path, {})
                    for target_cls in imp_mod.get("classes", [])[:MAX_CLASSES_PER_MODULE]:
                        tname = target_cls.get("name", "")
                        for sname in source_class_names:
                            if sname and tname:
                                s_safe = _sanitize_identifier(sname)
                                t_safe = _sanitize_identifier(tname)
                                if s_safe and t_safe and s_safe != "_" and t_safe != "_":
                                    lines.append(f"    {s_safe} --> {t_safe} : uses")
                    break  # One edge per import path

    return "\n".join(lines)


# ── Sequence diagram ──────────────────────────────────────────────────────


def _build_sequence_mermaid(data: dict, fqn: str) -> str:
    """Generate a sequence diagram for a given fully-qualified name.

    Shows how the analysis pipeline processes this module/file.
    """
    modules = data.get("modules", {})
    target_module = None

    # Try to find the module by FQN
    norm_fqn = fqn.replace(".", "/")
    for path in modules:
        if norm_fqn in path.replace("\\", "/") or fqn in path:
            target_module = path
            break

    lines = ["sequenceDiagram"]
    lines.append("    participant Client as Client")
    lines.append("    participant Scanner as Scanner")
    lines.append("    participant Analyzer as Analyzer")
    lines.append("    participant DepGraph as DependencyGraph")
    lines.append("    participant WikiGen as WikiGenerator")
    lines.append("    participant Embedder as Embedder")

    # Full pipeline flow
    lines.append("")
    lines.append("    Client->>Scanner: POST /api/scan")
    lines.append("    Scanner->>Scanner: scan filesystem")
    lines.append("    Scanner-->>Client: scan results")

    if target_module:
        label = target_module.replace("\\", "/")
        lines.append("")
        lines.append(f"    Note over Scanner,Analyzer: Processing: {label}")
        lines.append(f"    Scanner->>Analyzer: analyze_file({label})")

        mod = modules[target_module]
        for cls in mod.get("classes", []):
            cname = cls.get("name", "")
            lines.append(f"    Analyzer->>Analyzer: parse class {cname}")
            for method in cls.get("methods", []):
                mname = method.get("name", "?")
                lines.append(f"    Analyzer->>Analyzer:   method {mname}()")

        lines.append(f"    Analyzer-->>Scanner: ModuleInfo for {label}")
    else:
        lines.append("")
        lines.append(f"    Note over Scanner,Analyzer: Target: {fqn}")
        lines.append("    Scanner->>Analyzer: analyze files")

    lines.append("")
    lines.append("    Scanner->>DepGraph: build dependency graph")
    lines.append("    DepGraph-->>Scanner: dependency edges")

    lines.append("")
    lines.append("    Scanner->>WikiGen: generate wiki pages")
    lines.append("    WikiGen->>WikiGen: call LLM API")
    lines.append("    WikiGen-->>Scanner: wiki markdown")

    lines.append("")
    lines.append("    Scanner->>Embedder: rebuild vector index")
    lines.append("    Embedder-->>Scanner: index done")

    lines.append("")
    lines.append("    Scanner-->>Client: analysis complete")

    return "\n".join(lines)


# ── Placeholder fallback ──────────────────────────────────────────────────


def _placeholder_mermaid(diagram_type: str) -> str:
    """Return a friendly placeholder when no analysis data exists."""
    messages = {
        "architecture": (
            "graph TB\n"
            '    A["🏗 项目架构图"] --> B["暂无分析数据"]\n'
            '    B --> C["请先在设置中配置仓库路径"]\n'
            '    C --> D["然后点击扫描分析代码"]\n'
        ),
        "classes": (
            "classDiagram\n"
            "    class 暂无数据 {\n"
            "        +请先分析代码\n"
            "    }\n"
        ),
        "sequence": (
            "sequenceDiagram\n"
            '    participant You as 你\n'
            '    participant Code as 代码\n'
            '    You->>Code: 请先配置仓库并扫描分析\n'
            '    Code-->>You: 分析完成后将自动生成时序图\n'
        ),
    }
    return messages.get(diagram_type, "graph TD\n    A[待生成]\n")


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/diagrams/architecture")
async def get_architecture():
    """Return architecture Mermaid diagram."""
    # Try pre-generated .mmd first
    mmd = _load_mmd("architecture.mmd")
    if mmd:
        return {"mermaid": mmd}

    # Try building from analysis.json
    data = _load_analysis()
    if data:
        mmd = _build_architecture_mermaid(data)
        if mmd:
            return {"mermaid": mmd}

    return {"mermaid": _placeholder_mermaid("architecture")}


@router.get("/diagrams/classes")
async def get_classes():
    """Return class diagram Mermaid diagram."""
    data = _load_analysis()
    if data:
        mmd = _build_class_mermaid(data)
        if mmd:
            return {"mermaid": mmd}

    return {"mermaid": _placeholder_mermaid("classes")}


@router.get("/diagrams/sequence/{fqn:path}")
async def get_sequence(fqn: str):
    """Return sequence diagram for the analysis pipeline involving *fqn*."""
    data = _load_analysis()
    if data:
        mmd = _build_sequence_mermaid(data, fqn)
        if mmd:
            return {"mermaid": mmd}

    return {"mermaid": _placeholder_mermaid("sequence")}
