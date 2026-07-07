"""CFG Service — generates Control Flow Graphs for individual functions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("code-wiki.cfg_service")


class CFGService:
    """Generates CFG Mermaid diagrams for source code functions."""

    def generate(self, repo_path: str, file: str, function: str) -> dict:
        """Generate CFG for a function. Returns {function_name, cyclomatic_complexity,
        nesting_depth, blocks_count, unreachable_blocks, mermaid} or {error: ...}."""
        full_path = Path(repo_path) / file
        if not full_path.exists():
            repo_name = Path(repo_path).name
            alt = file.removeprefix(repo_name + "\\").removeprefix(repo_name + "/").removeprefix("\\").removeprefix("/")
            alt_path = Path(repo_path) / alt
            if alt != file and alt_path.exists():
                full_path = alt_path
            else:
                return {"error": f"File not found: {file}"}

        source = full_path.read_text(encoding="utf-8", errors="replace")

        try:
            from services.data_flow import CFGBuilder
            from tree_sitter import Language, Parser
            from tree_sitter_python import language as python_lang

            lang = Language(python_lang())
            parser = Parser(lang)
            tree = parser.parse(source.encode("utf-8"))

            fn_node = _find_function_node(tree.root_node, source, function)
            if fn_node is None:
                return {"error": f"Function '{function}' not found in {file}"}

            builder = CFGBuilder()
            cfg = builder.build(fn_node, source, function)

            return {
                "function_name": cfg.function_name,
                "cyclomatic_complexity": cfg.cyclomatic_complexity,
                "nesting_depth": cfg.max_nesting_depth,
                "blocks_count": len(cfg.blocks),
                "unreachable_blocks": cfg.unreachable_blocks,
                "mermaid": cfg.to_mermaid(f"CFG: {function}"),
            }
        except ImportError as e:
            return {"error": f"CFG module not available: {e}"}
        except Exception as e:
            return {"error": str(e)}


class ICFGService:
    """Generates Interprocedural CFG by combining call graph + per-function CFGs."""

    def generate(self, repo_path: str, function: str, file: str = "") -> dict:
        """Generate an ICFG Mermaid diagram showing callers/callees of a function.
        
        Loads call_graph.json to find interprocedural edges, then generates
        a combined Mermaid graph with the target function at the center."""
        from pathlib import Path
        import json

        wiki_dir = Path(repo_path) / ".code-wiki"
        cg_path = wiki_dir / "call_graph.json"
        if not cg_path.exists():
            return {"error": "Call graph not built yet. Please run a full scan first."}

        try:
            cg = json.loads(cg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as e:
            return {"error": f"Failed to load call graph: {e}"}

        # Find the target function in the call graph
        callables = cg.get("callables", {})
        forward = cg.get("forward", {})
        reverse = cg.get("reverse", {})

        # Search by function name across all entities
        target_id = None
        target_info = None
        for eid, info in callables.items():
            name = info.get("name", "")
            # Match by exact name or qualified name
            if name == function or name.endswith(f".{function}") or name.endswith(f":{function}"):
                if file:
                    fpath = info.get("file", "").replace("\\", "/")
                    if fpath.endswith(file.replace("\\", "/")) or file.replace("\\", "/").endswith(fpath):
                        target_id = eid
                        target_info = info
                        break
                else:
                    # First match wins if no file specified
                    if target_id is None:
                        target_id = eid
                        target_info = info

        if target_id is None:
            return {"error": f"Function '{function}' not found in call graph. Run a full scan first."}

        # Collect callers (up to 10) and callees (up to 10)
        callers = reverse.get(target_id, [])[:10]
        callees = forward.get(target_id, [])[:10]

        # Build mermaid graph
        lines = ["graph TD"]
        node_ids = set()

        def safe_id(name: str) -> str:
            """Make a safe mermaid node id from a function name."""
            return name.replace(".", "_").replace(":", "_").replace("<", "_").replace(">", "_").replace(" ", "_")

        def add_node(entity_id: str, label: str, style: str = ""):
            nid = safe_id(entity_id)
            if nid not in node_ids:
                node_ids.add(nid)
                suffix = f":::{style}" if style else ""
                lines.append(f"    {nid}[&quot;{label}&quot;]{suffix}")

        # Target node at center
        tgt_label = target_info.get("name", function)
        add_node(target_id, tgt_label, "target")

        # Callers (pointing to target)
        for cid in callers[:10]:
            info = callables.get(cid, {})
            label = info.get("name", cid)
            add_node(cid, label)
            lines.append(f"    {safe_id(cid)} --> {safe_id(target_id)}")

        # Callees (target points to)
        for cid in callees[:10]:
            info = callables.get(cid, {})
            label = info.get("name", cid)
            add_node(cid, label)
            lines.append(f"    {safe_id(target_id)} --> {safe_id(cid)}")

        mermaid = "\n".join(lines)

        return {
            "function_name": function,
            "file": target_info.get("file", ""),
            "callers_count": len(callers),
            "callees_count": len(callees),
            "total_callables": len(callables),
            "total_edges": sum(len(v) for v in forward.values()),
            "callers": [callables.get(c, {}).get("name", c) for c in callers[:10]],
            "callees": [callables.get(c, {}).get("name", c) for c in callees[:10]],
            "mermaid": mermaid,
        }


def _find_function_node(root, source: str, name: str):
    """Find a function definition node by name in a tree-sitter AST.
    Recursively searches into class bodies and nested structures."""
    # Check direct function definitions
    for child in root.children:
        if child.type == "function_definition":
            for c in child.children:
                if c.type == "identifier":
                    if source[c.start_byte:c.end_byte] == name:
                        return child
        elif child.type == "decorated_definition":
            for sub in child.children:
                if sub.type == "function_definition":
                    for c in sub.children:
                        if c.type == "identifier":
                            if source[c.start_byte:c.end_byte] == name:
                                return sub
    # Recurse into class bodies and other scopes
    for child in root.children:
        if child.type in ("class_definition", "block", "if_statement",
                          "for_statement", "while_statement", "with_statement",
                          "try_statement", "except_clause", "else_clause",
                          "finally_clause", "elif_clause", "match_statement"):
            result = _find_function_node(child, source, name)
            if result is not None:
                return result
    return None
