"""
Call Graph Builder — function-level call relationships.

Builds a directed graph of function/method calls extracted via tree-sitter.
Integrates with existing DependencyGraph (module-level) to resolve cross-module calls.

Architecture:
  ModuleInfo (from Analyzer) → CallGraphBuilder → CallGraphData
                                     ↑
                              Tree-sitter queries
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from tree_sitter import Language, Node, QueryCursor, Query

from models.entities import (
    CallableEntity, CallEdge, CallGraphData, ModuleInfo, SourceAnchor,
    SupportedLanguage,
)

logger = logging.getLogger("code-wiki.call_graph")


# ---------------------------------------------------------------------------
# Tree-sitter call queries per language
# ---------------------------------------------------------------------------

_CALL_QUERIES = {
    "python": """
    ;; Direct function call: foo(x)
    (call
      function: (identifier) @call.name
    ) @call.expr

    ;; Method call: obj.foo(x) or self.foo(x)
    (call
      function: (attribute
        object: (identifier) @call.receiver
        attribute: (identifier) @call.method)
    ) @call.expr

    ;; Chained method: obj.foo().bar()
    (call
      function: (attribute
        object: (call) @call.chained
        attribute: (identifier) @call.method)
    ) @call.expr
    """,

    "typescript": """
    ;; Direct function call: foo(x)
    (call_expression
      function: (identifier) @call.name
    ) @call.expr

    ;; Method call: obj.foo(x)
    (call_expression
      function: (member_expression
        object: (identifier) @call.receiver
        property: (property_identifier) @call.method)
    ) @call.expr

    ;; Chained method: obj.foo().bar()
    (call_expression
      function: (member_expression
        object: (call_expression) @call.chained
        property: (property_identifier) @call.method)
    ) @call.expr
    """,
}

# JavaScript uses same grammar as TypeScript
_CALL_QUERIES["javascript"] = _CALL_QUERIES["typescript"]


# Built-in / stdlib function names to skip (not repo entities)
_SKIP_NAMES: Set[str] = {
    "print", "len", "range", "type", "int", "str", "float", "bool", "list",
    "dict", "set", "tuple", "enumerate", "zip", "map", "filter", "sorted",
    "reversed", "min", "max", "sum", "abs", "round", "isinstance",
    "hasattr", "getattr", "setattr", "delattr", "super", "iter", "next",
    "open", "input", "isinstance", "issubclass", "staticmethod",
    "classmethod", "property", "repr", "format",
    "console.log", "console.error", "console.warn", "console.info",
}


class CallGraphBuilder:
    """Extracts call relationships from source code using tree-sitter.

    Usage::

        builder = CallGraphBuilder(repo_path, ts_parser)
        graph = builder.build(modules)    # modules: {rel_path: ModuleInfo}
        print(graph.forward["path/to/file.py::my_func"])
    """

    def __init__(self, repo_path: str, ts_parser):
        self.repo_path = Path(repo_path)
        self._ts_parser = ts_parser  # TreeSitterParser instance

    # ------------------------------------------------------------------
    # Main build entry point
    # ------------------------------------------------------------------

    def build(self, modules: Dict[str, ModuleInfo]) -> CallGraphData:
        """Build complete call graph from all analyzed modules.

        Steps:
        1. Collect all callable entities (functions, methods) from ModuleInfo
        2. For each function/method body, run tree-sitter call queries
        3. Resolve call targets to collected entities
        """
        # Step 1: Collect all callable entities
        callables: Dict[str, CallableEntity] = {}
        self._collect_callables(modules, callables)

        # Step 2 & 3: Extract calls and resolve
        forward: Dict[str, List[str]] = defaultdict(list)
        reverse: Dict[str, List[str]] = defaultdict(list)
        unresolved: List[CallEdge] = []

        # Build a name index for resolution
        name_index = self._build_name_index(callables)

        logger.info("Building call graph: %d callables across %d modules",
                    len(callables), len(modules))

        for rel_path, module_info in modules.items():
            self._extract_calls(
                rel_path, module_info, callables, name_index,
                forward, reverse, unresolved,
            )

        # Deduplicate edges
        for k in forward:
            forward[k] = sorted(set(forward[k]))
        for k in reverse:
            reverse[k] = sorted(set(reverse[k]))

        logger.info(
            "Call graph built: %d callables, %d edges, %d unresolved",
            len(callables),
            sum(len(v) for v in forward.values()),
            len(unresolved),
        )

        return CallGraphData(
            callables=callables,
            forward=dict(forward),
            reverse=dict(reverse),
            unresolved_calls=unresolved,
        )

    # ------------------------------------------------------------------
    # Entity collection
    # ------------------------------------------------------------------

    def _collect_callables(
        self,
        modules: Dict[str, ModuleInfo],
        callables: Dict[str, CallableEntity],
    ):
        """Walk all ModuleInfo nodes and register every function/method."""
        for rel_path, module in modules.items():
            # Top-level functions
            for fn in module.functions:
                eid = self._make_id(rel_path, fn.name)
                callables[eid] = CallableEntity(
                    id=eid,
                    name=fn.name,
                    module=rel_path,
                    anchor=fn.anchor,
                    end_line=fn.end_line,
                    kind="function",
                )

            # Class methods
            for cls in module.classes:
                for method in cls.methods:
                    eid = self._make_id(rel_path, method.name, cls.name)
                    kind = "constructor" if method.name == "__init__" else "method"
                    callables[eid] = CallableEntity(
                        id=eid,
                        name=method.name,
                        module=rel_path,
                        parent_class=cls.name,
                        anchor=method.anchor,
                        end_line=method.end_line,
                        kind=kind,
                    )

    # ------------------------------------------------------------------
    # Call extraction per module
    # ------------------------------------------------------------------

    def _extract_calls(
        self,
        rel_path: str,
        module_info: ModuleInfo,
        callables: Dict[str, CallableEntity],
        name_index: Dict[str, List[str]],
        forward: Dict[str, List[str]],
        reverse: Dict[str, List[str]],
        unresolved: List[CallEdge],
    ):
        """Extract calls from one module and add edges to the graph."""
        lang = module_info.language
        query_src = _CALL_QUERIES.get(lang.value)
        if not query_src:
            return

        ts_lang = self._ts_parser._languages.get(lang)
        if ts_lang is None:
            return

        # Read source
        full_path = self.repo_path / rel_path
        try:
            source = full_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            return

        # Parse
        tree = self._ts_parser._try_parse(source, lang)
        if tree is None:
            return

        # Find all call sites
        calls = self._find_calls(tree.root_node, source, ts_lang, query_src)

        # For each call scope (which function/method contains this call),
        # determine caller and resolve callee
        for call_info in calls:
            caller_id = self._find_caller_for(rel_path, call_info["line"], source, lang, callables)
            if caller_id is None:
                continue

            callee_id = self._resolve_call(
                call_info, rel_path, source, lang, callables, name_index
            )

            callee_anchor = SourceAnchor(file=rel_path, line=call_info["line"])
            edge = CallEdge(
                caller_id=caller_id,
                callee_id=callee_id or call_info.get("full_name", "?"),
                call_site=callee_anchor,
                resolved=callee_id is not None,
            )

            if callee_id:
                forward[caller_id].append(callee_id)
                reverse[callee_id].append(caller_id)
            else:
                unresolved.append(edge)

    def _find_calls(
        self,
        root: Node,
        source: str,
        lang: Language,
        query_src: str,
    ) -> List[dict]:
        """Run the call query and return structured call information."""
        calls: List[dict] = []
        q = Query(lang, query_src)
        cursor = QueryCursor(q)

        try:
            for _, caps in cursor.matches(root):
                name_nodes = caps.get("call.name", [])
                receiver_nodes = caps.get("call.receiver", [])
                method_nodes = caps.get("call.method", [])
                expr_nodes = caps.get("call.expr", [])

                recv_name = None
                if receiver_nodes:
                    recv_name = receiver_nodes[0].text.decode()

                fn_name = None
                if name_nodes:
                    fn_name = name_nodes[0].text.decode()
                elif method_nodes and recv_name:
                    fn_name = f"{recv_name}.{method_nodes[0].text.decode()}"
                elif method_nodes:
                    fn_name = method_nodes[0].text.decode()

                if not fn_name:
                    continue

                line = expr_nodes[0].start_point[0] + 1 if expr_nodes else 0

                calls.append({
                    "name": fn_name.split(".")[-1] if "." in fn_name else fn_name,
                    "full_name": fn_name,
                    "receiver": recv_name,
                    "line": line,
                })
        except Exception as e:
            logger.warning("_find_calls error: %s", e, exc_info=True)

        return calls

    # ------------------------------------------------------------------
    # Call resolution
    # ------------------------------------------------------------------

    def _find_caller_for(
        self,
        rel_path: str,
        call_line: int,
        source: str,
        lang: SupportedLanguage,
        callables: Dict[str, CallableEntity],
    ) -> Optional[str]:
        """Find which function/method contains the call at the given line.

        Uses the entity's anchor line and end_line to determine containment.
        """
        # Find all callables in this module that span across call_line
        candidates = [
            e for e in callables.values()
            if e.module == rel_path
            and e.anchor
            and e.anchor.line <= call_line
            and e.end_line >= call_line
        ]
        if not candidates:
            return None

        # Pick the innermost one (smallest span = most specific)
        candidates.sort(key=lambda e: e.end_line - e.anchor.line)
        return candidates[0].id

    def _resolve_call(
        self,
        call_info: dict,
        rel_path: str,
        source: str,
        lang: SupportedLanguage,
        callables: Dict[str, CallableEntity],
        name_index: Dict[str, List[str]],
    ) -> Optional[str]:
        """Resolve a call to a specific callable entity ID."""
        fn_name = call_info["name"]
        receiver = call_info.get("receiver")

        if fn_name in _SKIP_NAMES:
            return None

        if receiver == "self":
            # self.method() → same module, any class
            # Find the enclosing class by looking at call site context
            candidates = [
                eid for eid in name_index.get(fn_name, [])
                if eid.startswith(rel_path + "::")
            ]
            if candidates:
                return candidates[0]
            return None

        elif receiver and receiver != "self":
            # obj.method() → harder; could be a local variable referencing an instance
            # For now, try matching just the method name
            all_candidates = name_index.get(fn_name, [])
            # Prefer same-module candidates
            same_module = [c for c in all_candidates if c.startswith(rel_path + "::")]
            if same_module:
                return same_module[0]
            if all_candidates:
                return all_candidates[0]
            return None

        else:
            # Plain function call
            # 1. Same module
            candidates = [
                eid for eid in name_index.get(fn_name, [])
                if eid.startswith(rel_path + "::")
            ]
            if len(candidates) == 1:
                return candidates[0]

            # 2. Imported from other modules (check module imports)
            module_candidates = [
                eid for eid in name_index.get(fn_name, [])
                if not eid.startswith(rel_path + "::")
            ]
            if module_candidates:
                return module_candidates[0]

            # 3. Any match
            any_match = name_index.get(fn_name, [])
            if any_match:
                return any_match[0]

            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_id(rel_path: str, func_name: str, parent_class: Optional[str] = None) -> str:
        """Build a unique entity ID.

        Format: "relative/path/file.py::ClassName.method_name" or
                "relative/path/file.py::func_name"
        """
        base = rel_path.replace("\\", "/")
        if parent_class:
            return f"{base}::{parent_class}.{func_name}"
        return f"{base}::{func_name}"

    @staticmethod
    def _build_name_index(callables: Dict[str, CallableEntity]) -> Dict[str, List[str]]:
        """Build index: simple_name → [entity_ids]."""
        idx: Dict[str, List[str]] = defaultdict(list)
        for eid, entity in callables.items():
            idx[entity.name].append(eid)
        return dict(idx)

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def callers_of(self, entity_id: str, graph: CallGraphData) -> List[str]:
        """Return list of entity IDs that call the given entity."""
        return graph.reverse.get(entity_id, [])

    def callees_of(self, entity_id: str, graph: CallGraphData) -> List[str]:
        """Return list of entity IDs called by the given entity."""
        return graph.forward.get(entity_id, [])

    def transitive_callers(
        self, entity_id: str, graph: CallGraphData, max_depth: int = 10
    ) -> Set[str]:
        """All transitive callers (BFS up to max_depth)."""
        visited: Set[str] = set()
        queue = [entity_id]
        while queue and max_depth > 0:
            current = queue.pop(0)
            for caller in graph.reverse.get(current, []):
                if caller not in visited:
                    visited.add(caller)
                    queue.append(caller)
            max_depth -= 1
        return visited

    def find_call_path(
        self, from_id: str, to_id: str, graph: CallGraphData, max_depth: int = 8
    ) -> Optional[List[str]]:
        """BFS shortest path from one entity to another via calls."""
        if from_id == to_id:
            return [from_id]

        visited = {from_id}
        queue = [(from_id, [from_id])]

        while queue:
            current, path = queue.pop(0)
            if len(path) > max_depth:
                continue
            for callee in graph.forward.get(current, []):
                if callee == to_id:
                    return path + [callee]
                if callee not in visited:
                    visited.add(callee)
                    queue.append((callee, path + [callee]))
        return None

    # ------------------------------------------------------------------
    # Mermaid export
    # ------------------------------------------------------------------

    def to_mermaid(
        self,
        graph: CallGraphData,
        entity_ids: Optional[List[str]] = None,
        max_depth: int = 2,
        title: str = "Call Graph",
    ) -> str:
        """Export a subset of the call graph as Mermaid.

        If entity_ids is given, renders a subgraph centered on those entities.
        Otherwise, renders the top-level call graph (excluding low-level helpers).
        """
        lines = ["graph TD"]
        lines.append(f'    title["{title}"]')

        # Collect nodes to render
        if entity_ids:
            node_set: Set[str] = set(entity_ids)
            edge_set: Set[Tuple[str, str]] = set()
            for _ in range(max_depth):
                new_ids: Set[str] = set()
                for nid in list(node_set):
                    for callee in graph.forward.get(nid, []):
                        new_ids.add(callee)
                        edge_set.add((nid, callee))
                    for caller in graph.reverse.get(nid, []):
                        new_ids.add(caller)
                        edge_set.add((caller, nid))
                node_set |= new_ids
        else:
            node_set = set(graph.callables.keys())
            edge_set = {
                (src, tgt)
                for src, targets in graph.forward.items()
                for tgt in targets
            }
            if len(node_set) > 50:
                # Too large — only show edges with ≥ 2 calls
                node_set = set()
                edge_set = set()

        # Assign short labels
        id_map: Dict[str, str] = {}
        for i, eid in enumerate(sorted(node_set)):
            id_map[eid] = f"CG{i}"

        # Render nodes
        for eid, node_id in id_map.items():
            entity = graph.callables.get(eid)
            if entity:
                label = entity.name[:30]
                if entity.parent_class:
                    label = f"{entity.parent_class}.{label}"
                # Replace special chars in label for Mermaid
                label = label.replace('"', "'")
                lines.append(f'    {node_id}["{label}"]')

        # Render edges
        for src, tgt in sorted(edge_set):
            if src in id_map and tgt in id_map:
                lines.append(f"    {id_map[src]} --> {id_map[tgt]}")

        return "\n".join(lines)
