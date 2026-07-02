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


def _find_function_node(root, source: str, name: str):
    """Find a function definition node by name in a tree-sitter AST."""
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
    return None
