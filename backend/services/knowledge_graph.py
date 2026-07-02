"""
Code Knowledge Graph — multi-type entity-relation graph.

Integrates ModuleInfo + CallGraph + DependencyGraph into a unified
NetworkX digraph for advanced queries and visualization.

Node types: Module, Class, Function, Interface, Component
Edge types: CONTAINS, CALLS, INHERITS, IMPLEMENTS, IMPORTS, DECORATES
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from models.entities import (
    ModuleInfo, ClassInfo, FunctionInfo, CallGraphData, CallableEntity,
)

logger = logging.getLogger("code-wiki.knowledge_graph")


class CodeKnowledgeGraph:
    """Unified knowledge graph combining module, class, and function relations.

    Uses Python dicts for lightweight in-memory storage (no NetworkX dependency
    required at runtime — NetworkX is optional for advanced graph algorithms).
    """

    def __init__(self):
        # Node storage: {node_id: {attr...}}
        self.nodes: Dict[str, dict] = {}
        # Edge storage: {(src, tgt): {"relation": rel_type, ...}}
        self.edges: Dict[Tuple[str, str], dict] = {}
        # Adjacency: {src_id: {tgt_id: [relations]}}
        self._adj: Dict[str, Dict[str, List[str]]] = {}
        # Reverse adjacency
        self._rev_adj: Dict[str, Dict[str, List[str]]] = {}

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(
        self,
        modules: Dict[str, ModuleInfo],
        call_graph: Optional[CallGraphData] = None,
        dep_graph=None,  # DependencyGraph instance
    ):
        """Build the knowledge graph from analyzed modules."""
        self._reset()

        # 1. Add module nodes + CONTAINS edges
        for rel_path, module in modules.items():
            self._add_node("module", rel_path, {
                "path": rel_path,
                "language": module.language.value,
                "total_lines": module.total_lines,
                "entity_count": module.total_entities,
            })

            # Module → Class
            for cls in module.classes:
                cls_id = f"{rel_path}::{cls.name}"
                self._add_node("class", cls_id, {
                    "name": cls.name,
                    "module": rel_path,
                    "line": cls.anchor.line if cls.anchor else 0,
                    "bases": cls.bases,
                    "method_count": len(cls.methods),
                })
                self._add_edge(rel_path, cls_id, "CONTAINS")

                # Class → Method
                for method in cls.methods:
                    meth_id = f"{rel_path}::{cls.name}.{method.name}"
                    self._add_node("function", meth_id, {
                        "name": method.name,
                        "module": rel_path,
                        "parent_class": cls.name,
                        "line": method.anchor.line if method.anchor else 0,
                        "kind": "method",
                    })
                    self._add_edge(cls_id, meth_id, "CONTAINS")

            # Module → Function
            for fn in module.functions:
                fn_id = f"{rel_path}::{fn.name}"
                self._add_node("function", fn_id, {
                    "name": fn.name,
                    "module": rel_path,
                    "line": fn.anchor.line if fn.anchor else 0,
                    "kind": "function",
                })
                self._add_edge(rel_path, fn_id, "CONTAINS")

            # Module → Interface (TS)
            for iface in getattr(module, 'interfaces', []) or []:
                iface_id = f"{rel_path}::{iface.name}"
                self._add_node("interface", iface_id, {
                    "name": iface.name,
                    "module": rel_path,
                    "member_count": len(iface.members),
                })
                self._add_edge(rel_path, iface_id, "CONTAINS")

            # Module → Component (React)
            for comp in getattr(module, 'components', []) or []:
                comp_id = f"{rel_path}::{comp.name}"
                self._add_node("component", comp_id, {
                    "name": comp.name,
                    "module": rel_path,
                    "hooks": comp.hooks,
                })
                self._add_edge(rel_path, comp_id, "CONTAINS")

        # 2. INHERITS edges
        for rel_path, module in modules.items():
            for cls in module.classes:
                cls_id = f"{rel_path}::{cls.name}"
                for base in cls.bases:
                    # Try to find base class in the graph
                    base_candidates = [
                        nid for nid, attrs in self.nodes.items()
                        if attrs.get("name") == base and attrs.get("type") == "class"
                    ]
                    if base_candidates:
                        self._add_edge(cls_id, base_candidates[0], "INHERITS")

        # 3. IMPLEMENTS edges (TS)
        for rel_path, module in modules.items():
            for iface in getattr(module, 'interfaces', []) or []:
                iface_id = f"{rel_path}::{iface.name}"
                for cls in module.classes:
                    cls_id = f"{rel_path}::{cls.name}"
                    if iface.name in cls.bases:
                        self._add_edge(cls_id, iface_id, "IMPLEMENTS")

        # 4. IMPORTS edges (from DependencyGraph)
        if dep_graph is not None:
            for src, targets in dep_graph.get_topology():
                src_norm = src.replace("\\", "/")
                for tgt in targets:
                    tgt_norm = tgt.replace("\\", "/")
                    if src_norm in self.nodes and tgt_norm in self.nodes:
                        self._add_edge(src_norm, tgt_norm, "IMPORTS")

        # 5. CALLS edges (from CallGraph)
        if call_graph is not None:
            for caller_id, callee_ids in call_graph.forward.items():
                # Normalize IDs for consistency
                caller_norm = caller_id.replace("\\", "/")
                for callee_id in callee_ids:
                    callee_norm = callee_id.replace("\\", "/")
                    if caller_norm in self.nodes and callee_norm in self.nodes:
                        self._add_edge(caller_norm, callee_norm, "CALLS")

        logger.info(
            "Knowledge graph built: %d nodes, %d edges",
            len(self.nodes), len(self.edges),
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_neighbors(self, node_id: str, depth: int = 1) -> Dict[str, List[str]]:
        """Get neighboring nodes grouped by relation type."""
        visited: Set[str] = {node_id}
        frontier = {node_id}
        relations: Dict[str, List[str]] = {}
        for _ in range(depth):
            next_frontier: Set[str] = set()
            for nid in frontier:
                for tgt, rels in self._adj.get(nid, {}).items():
                    if tgt not in visited:
                        visited.add(tgt)
                        next_frontier.add(tgt)
                        for rel in rels:
                            relations.setdefault(rel, []).append(tgt)
                # Also check reverse
                for tgt, rels in self._rev_adj.get(nid, {}).items():
                    if tgt not in visited:
                        visited.add(tgt)
                        next_frontier.add(tgt)
                        rev_rel = f"REV_{rels[0]}" if rels else "RELATED"
                        relations.setdefault(rev_rel, []).append(tgt)
            frontier = next_frontier
        return relations

    def find_call_chain(self, from_id: str, to_id: str, max_depth: int = 8) -> Optional[List[dict]]:
        """BFS-based call chain with relation annotations."""
        if from_id not in self.nodes or to_id not in self.nodes:
            return None
        if from_id == to_id:
            return [{"id": from_id, "relation": "self"}]

        visited = {from_id}
        queue: List[Tuple[str, List[dict]]] = [(from_id, [{"id": from_id, "relation": "start"}])]

        while queue:
            current, path = queue.pop(0)
            if len(path) > max_depth:
                continue
            for tgt, rels in self._adj.get(current, {}).items():
                if tgt == to_id:
                    return path + [{"id": tgt, "relation": rels[0]}]
                if tgt not in visited:
                    visited.add(tgt)
                    queue.append((tgt, path + [{"id": tgt, "relation": rels[0]}]))
        return None

    def page_rank(self, damping: float = 0.85, iterations: int = 50) -> Dict[str, float]:
        """Simple PageRank over the knowledge graph."""
        if not self.nodes:
            return {}

        scores = {nid: 1.0 / len(self.nodes) for nid in self.nodes}

        for _ in range(iterations):
            new_scores: Dict[str, float] = {}
            for nid in self.nodes:
                rank = (1 - damping) / len(self.nodes)
                for pred in self._rev_adj.get(nid, {}):
                    out_deg = len(self._adj.get(pred, {}))
                    if out_deg > 0:
                        rank += damping * scores[pred] / out_deg
                new_scores[nid] = rank
            scores = new_scores

        return scores

    def find_related(self, node_id: str, depth: int = 2) -> dict:
        """Return all nodes within 'depth' hops with their metadata."""
        related: dict = {"nodes": {}, "edges": []}
        visited = {node_id}
        frontier = {node_id}

        for _ in range(depth):
            next_frontier: Set[str] = set()
            for nid in frontier:
                for tgt, rels in self._adj.get(nid, {}).items():
                    if tgt not in visited:
                        visited.add(tgt)
                        next_frontier.add(tgt)
                    related["edges"].append({"from": nid, "to": tgt, "relation": rels[0]})
                for tgt in self._rev_adj.get(nid, {}):
                    if tgt not in visited:
                        visited.add(tgt)
                        next_frontier.add(tgt)
            frontier = next_frontier

        for nid in visited:
            related["nodes"][nid] = self.nodes.get(nid, {})

        return related

    def detect_communities(self) -> List[Set[str]]:
        """Simple community detection by connected components (ignoring edge direction)."""
        visited: Set[str] = set()
        communities: List[Set[str]] = []

        for nid in self.nodes:
            if nid in visited:
                continue
            community: Set[str] = set()
            stack = [nid]
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                community.add(current)
                for tgt in self._adj.get(current, {}):
                    if tgt not in visited:
                        stack.append(tgt)
                for tgt in self._rev_adj.get(current, {}):
                    if tgt not in visited:
                        stack.append(tgt)
            communities.append(community)

        return communities

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "nodes": {nid: attrs for nid, attrs in self.nodes.items()},
            "edges": [
                {"from": src, "to": tgt, **attrs}
                for (src, tgt), attrs in self.edges.items()
            ],
        }

    def save(self, path: str | Path):
        """Save to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Knowledge graph saved to %s (%d nodes, %d edges)",
                     path, len(self.nodes), len(self.edges))

    def load(self, path: str | Path) -> bool:
        """Load from JSON file."""
        path = Path(path)
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._reset()
            for nid, attrs in data.get("nodes", {}).items():
                self.nodes[nid] = attrs
            for edge in data.get("edges", []):
                src, tgt = edge.pop("from"), edge.pop("to")
                self._add_edge(src, tgt, edge.pop("relation", "RELATED"), **edge)
            logger.info("Knowledge graph loaded: %d nodes, %d edges",
                         len(self.nodes), len(self.edges))
            return True
        except Exception as e:
            logger.warning("Failed to load knowledge graph: %s", e)
            return False

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict:
        """Summary statistics."""
        node_types = {}
        for attrs in self.nodes.values():
            t = attrs.get("type", "unknown")
            node_types[t] = node_types.get(t, 0) + 1

        edge_types = {}
        for attrs in self.edges.values():
            rel = attrs.get("relation", "unknown")
            edge_types[rel] = edge_types.get(rel, 0) + 1

        return {
            "total_nodes": len(self.nodes),
            "node_types": node_types,
            "total_edges": len(self.edges),
            "edge_types": edge_types,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _reset(self):
        self.nodes.clear()
        self.edges.clear()
        self._adj.clear()
        self._rev_adj.clear()

    def _add_node(self, node_type: str, node_id: str, attrs: dict):
        attrs["type"] = node_type
        if "id" not in attrs:
            attrs["id"] = node_id
        self.nodes[node_id] = attrs

    def _add_edge(self, src: str, tgt: str, relation: str, **extra):
        key = (src, tgt)
        if key in self.edges:
            existing = self.edges[key].get("relation", "")
            if relation not in existing:
                self.edges[key]["relation"] = f"{existing}+{relation}"
        else:
            self.edges[key] = {"relation": relation, **extra}

        self._adj.setdefault(src, {}).setdefault(tgt, []).append(relation)
        self._rev_adj.setdefault(tgt, {}).setdefault(src, []).append(relation)
