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
            # Try stripping the repo dirname prefix (e.g. "order\backend\..." → "backend\...")
            repo_name = Path(repo_path).name  # e.g. "order"
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
