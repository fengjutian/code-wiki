"""Mermaid diagram endpoints — real diagrams from analysis data."""

import json
import logging
import os
from pathlib import Path
from fastapi import APIRouter

from config import _config, get_wiki_path
from services.mermaid_utils import sanitize_label, sanitize_identifier

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
            lines.append(f'        {nid}["{sanitize_label(label)}"]')
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
        safe_name = sanitize_identifier(cls_name.replace(".", "_").replace("/", "_"))
        lines.append(f"    class {safe_name} {{")
        if cls_data["docstring"]:
            doc_first_line = sanitize_label(cls_data["docstring"].split("\n")[0])
            lines.append(f"        +『{doc_first_line}』")
        for method in cls_data.get("methods", []):
            sig = method.get("signature", method.get("name", "?"))
            if not sig.endswith(")"):
                sig += "()"
            lines.append(f"        +{sanitize_label(sig)}")
        lines.append("    }")

        # Inheritance
        for base in cls_data["bases"]:
            safe_base = sanitize_identifier(base)
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
                                s_safe = sanitize_identifier(sname)
                                t_safe = sanitize_identifier(tname)
                                if s_safe and t_safe and s_safe != "_" and t_safe != "_":
                                    lines.append(f"    {s_safe} --> {t_safe} : uses")
                    break  # One edge per import path

    return "\n".join(lines)


# ── Sequence diagram ──────────────────────────────────────────────────────


def _build_sequence_mermaid(data: dict, fqn: str) -> str:
    """Generate a sequence diagram for a given fully-qualified name.

    Shows the actual call/dependency chain from the analyzed code:
    who calls this module → what this module does → what it calls downstream.
    """
    modules = data.get("modules", {})
    dep_graph = data.get("dependency_graph", {})
    edge_list = dep_graph.get("edges", [])

    # Normalize FQN: convert dots to path separators
    norm_fqn = fqn.replace(".", "/")

    # Find the target module(s)
    target_paths = []
    for path in modules:
        if norm_fqn in path.replace("\\", "/"):
            target_paths.append(path)

    if not target_paths:
        # Fallback: show overall pipeline
        return _build_pipeline_sequence(data)

    target = target_paths[0]
    target_label = target.replace("\\", "/")

    # Build adjacency: who imports whom
    # "A → B" means A imports B
    calls: dict[str, list[str]] = {}          # who_calls[caller] = [callees]
    called_by: dict[str, list[str]] = {}       # called_by[callee] = [callers]
    for edge in edge_list:
        src = edge.get("source", "")
        for tgt in edge.get("targets", []):
            calls.setdefault(src, []).append(tgt)
            called_by.setdefault(tgt, []).append(src)

    lines = ["sequenceDiagram"]
    participants: dict[str, str] = {}
    _ensure_participant("Client", "Client", participants)
    _ensure_participant("Target", "Module", participants)

    # Write participant declarations
    # Collect: callers (up to 3), target, callees (up to 5)
    callers = called_by.get(target, [])[:3]
    callees = calls.get(target, [])[:5]

    for cp in callers:
        alias = _module_alias(cp)
        _ensure_participant(alias, cp.replace("\\", "/"), participants)

    _ensure_participant("Target", target_label, participants)

    for cp in callees:
        alias = _module_alias(cp)
        _ensure_participant(alias, cp.replace("\\", "/"), participants)

    # Add participant lines
    for alias, label in participants.items():
        lines.append(f"    participant {alias} as {sanitize_label(label)}")

    lines.append("")

    # ── Call chain ──
    # Upstream: callers call target
    for i, cp in enumerate(callers):
        calias = _module_alias(cp)
        cp_mod = modules.get(cp, {})
        # Pick a representative class or function
        cp_entities = _pick_call_entities(cp_mod)
        if cp_entities:
            for ent_name in cp_entities[:2]:
                lines.append(f"    {calias}->>+Target: {ent_name}()")
        else:
            lines.append(f"    {calias}->>+Target: 调用")
        if i == len(callers) - 1:
            lines.append(f"    Note over Target: {target_label}")

    # Target's internal processing
    target_mod = modules.get(target, {})
    for cls in target_mod.get("classes", [])[:3]:
        cname = cls.get("name", "")
        pub_methods = [
            m.get("name", "?")
            for m in cls.get("methods", [])
            if not m.get("name", "").startswith("_")
        ][:3]
        if pub_methods:
            for mn in pub_methods:
                lines.append(f"    Target->>Target: {cname}.{mn}()")
        else:
            lines.append(f"    Target->>Target: {cname} processing")

    # Public functions (not methods)
    for fn in target_mod.get("functions", [])[:3]:
        fname = fn.get("name", "?")
        if not fname.startswith("_"):
            lines.append(f"    Target->>Target: {fname}()")

    # Downstream: target calls callees
    for i, cp in enumerate(callees):
        calias = _module_alias(cp)
        cp_mod = modules.get(cp, {})
        cp_entities = _pick_call_entities(cp_mod)
        if cp_entities:
            lines.append(f"    Target->>+{calias}: {cp_entities[0]}()")
            for ent_name in cp_entities[1:3]:
                lines.append(f"    {calias}->>{calias}: {ent_name}()")
            lines.append(f"    {calias}-->>-Target: return")
        else:
            lines.append(f"    Target->>{calias}: 调用")
            lines.append(f"    {calias}-->>Target: return")

    # Return to callers
    for cp in reversed(callers):
        calias = _module_alias(cp)
        lines.append(f"    Target-->>-{calias}: return")

    lines.append(f"    Note over Client,Target: 关注模块: {target_label}")

    return "\n".join(lines)


def _build_pipeline_sequence(data: dict) -> str:
    """Build a high-level Code Wiki analysis pipeline sequence (fallback)."""
    modules_count = len(data.get("modules", {}))
    dep_graph = data.get("dependency_graph", {})
    edges_count = dep_graph.get("stats", {}).get("total_edges", 0)

    lines = [
        "sequenceDiagram",
        "    participant User as User",
        "    participant Code as Code Wiki Backend",
        "    participant LLM as LLM API",
        "",
        f"    Note over User,LLM: Analyzed {modules_count} modules, {edges_count} dependency edges",
        "    User->>+Code: 触发分析",
        "    Code->>Code: 扫描文件系统",
        "    Code->>Code: AST 解析 & 构建依赖图",
        "    Code->>+LLM: 生成 Wiki 文档",
        "    LLM-->>-Code: Markdown Wiki",
        "    Code->>Code: 构建向量索引",
        "    Code-->>-User: 分析完成",
        "",
        "    Note over User,LLM: 选择具体模块查看详细调用链时序图",
    ]
    return "\n".join(lines)


def _module_alias(path: str) -> str:
    """Create a short Mermaid-safe alias from a module path."""
    norm = path.replace("\\", "/")
    parts = norm.split("/")
    if len(parts) >= 2:
        return parts[-2][:4] + "_" + parts[-1].rsplit(".", 1)[0].replace("-", "_")
    return norm.rsplit(".", 1)[0].replace("/", "_").replace("-", "_")[:12]


def _ensure_participant(
    alias: str, label: str, participants: dict
) -> None:
    """Add participant if alias is unique."""
    if alias not in participants:
        participants[alias] = label


def _pick_call_entities(mod: dict) -> list:
    """Pick representative public entities for call-chain display."""
    entities = []
    for cls in mod.get("classes", []):
        for m in cls.get("methods", []):
            name = m.get("name", "")
            if not name.startswith("_") and name not in entities:
                entities.append(f"{cls.get('name', '?')}.{name}")
    for fn in mod.get("functions", []):
        name = fn.get("name", "")
        if not name.startswith("_") and name not in entities:
            entities.append(name)
    return entities[:5]


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
