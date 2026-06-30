"""
Module dependency graph builder.

Constructs a directed graph of internal module dependencies from import statements.
Used for:
- Architecture diagram generation
- Incremental analysis (find affected files on change)
- Wiki cross-references
"""

import os
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict

from models.entities import ModuleInfo
from services.mermaid_utils import sanitize_label


class DependencyGraph:
    """
    Directed graph of module dependencies.

    Edges: A → B means module A imports module B.
    """

    def __init__(self):
        # Forward edges: {module_path: [imported_module_paths]}
        self._forward: Dict[str, List[str]] = defaultdict(list)
        # Reverse edges: {module_path: [dependents]}
        self._reverse: Dict[str, List[str]] = defaultdict(list)
        # All known module paths
        self._modules: Set[str] = set()

    # ---- Build ----

    def build(self, modules: Dict[str, ModuleInfo]) -> "DependencyGraph":
        """Build the dependency graph from analyzed modules."""
        self._forward.clear()
        self._reverse.clear()
        self._modules = set(modules.keys())

        # Index: filename (without path and extension) → full path, for resolving imports
        name_index: Dict[str, List[str]] = defaultdict(list)
        for path in modules:
            # Strip extension and path, keep module-ish name
            key = path.replace("\\", "/").replace("/", ".")
            # Remove file extension (.py, .ts, .tsx, .js, .jsx)
            for ext in [".py", ".ts", ".tsx", ".js", ".jsx"]:
                key = key.removesuffix(ext)
            name_index[key].append(path)
            # Also index by just the filename (without extension)
            basename = os.path.splitext(os.path.basename(path))[0]
            name_index[basename].append(path)

        for src_path, module in modules.items():
            for imp in module.imports:
                resolved = self._resolve_import(imp, src_path, name_index)
                if resolved:
                    self._forward[src_path].append(resolved)
                    self._reverse[resolved].append(src_path)

        # Deduplicate
        for k in self._forward:
            self._forward[k] = sorted(set(self._forward[k]))
        for k in self._reverse:
            self._reverse[k] = sorted(set(self._reverse[k]))

        return self

    # ---- Query ----

    def dependencies_of(self, module_path: str) -> List[str]:
        """What does this module import?"""
        return self._forward.get(module_path, [])

    def dependents_of(self, module_path: str) -> List[str]:
        """Which modules import this one?"""
        return self._reverse.get(module_path, [])

    def find_affected(self, changed_files: List[str]) -> List[str]:
        """
        Given a list of changed files, find all files that need re-analysis.
        Includes:
        - The changed files themselves
        - Any file that imports one of the changed files (recursively)
        """
        affected: Set[str] = set(changed_files)
        queue: List[str] = list(changed_files)

        while queue:
            current = queue.pop(0)
            for dependent in self.dependents_of(current):
                if dependent not in affected:
                    affected.add(dependent)
                    queue.append(dependent)

        return sorted(affected)

    def get_topology(self) -> List[Tuple[str, List[str]]]:
        """Return all edges as (source, [targets]) for Mermaid generation."""
        return sorted(self._forward.items())

    def get_isolated_modules(self) -> List[str]:
        """Modules with no incoming or outgoing internal dependencies."""
        isolated = []
        for path in sorted(self._modules):
            has_deps = bool(self._forward.get(path))
            has_dependents = bool(self._reverse.get(path))
            if not has_deps and not has_dependents:
                isolated.append(path)
        return isolated

    def get_core_modules(self, top_n: int = 10) -> List[Tuple[str, int]]:
        """
        Return modules ranked by total dependency count
        (imports + dependents), useful for architecture overview.
        """
        scores = []
        for path in sorted(self._modules):
            score = len(self._forward.get(path, [])) + len(
                self._reverse.get(path, [])
            )
            scores.append((path, score))
        scores.sort(key=lambda x: -x[1])
        return scores[:top_n]

    # ---- Mermaid export ----

    def to_mermaid(self, title: str = "Module Dependency Graph") -> str:
        """Export as Mermaid graph TD diagram."""
        lines = [f"graph TD", f'    title["{sanitize_label(title)}"]']

        # Assign short IDs to modules
        ids: Dict[str, str] = {}
        for i, path in enumerate(sorted(self._modules)):
            ids[path] = f"M{i}"

        # Style nodes
        for path, node_id in ids.items():
            label = path.replace("\\", "/")
            for ext in [".py", ".ts", ".tsx", ".js", ".jsx"]:
                label = label.removesuffix(ext)
            label = label.replace("/", "/<br/>")
            lines.append(f'    {node_id}["{sanitize_label(label)}"]')

        # Draw edges
        for src, targets in sorted(self._forward.items()):
            if src not in ids:
                continue
            for tgt in targets:
                if tgt not in ids:
                    continue
                lines.append(f"    {ids[src]} --> {ids[tgt]}")

        return "\n".join(lines)

    def to_architecture_mermaid(self) -> str:
        """Generate an architecture overview Mermaid diagram."""
        lines = ["graph LR"]

        # Group modules by top-level directory
        groups: Dict[str, List[str]] = defaultdict(list)
        for path in sorted(self._modules):
            parts = path.replace("\\", "/").split("/")
            group = parts[0] if len(parts) > 1 else "root"
            groups[group].append(path)

        # Create subgraphs
        for group, paths in sorted(groups.items()):
            safe_group = group.replace("-", "_").replace(".", "_")
            lines.append(f'    subgraph {safe_group}["{sanitize_label(group)}"]')
            for i, path in enumerate(paths):
                node_id = f"{safe_group}_{i}"
                label = path.replace("\\", "/")
                for ext in [".py", ".ts", ".tsx", ".js", ".jsx"]:
                    label = label.removesuffix(ext)
                label = sanitize_label(label)
                label = label.replace("/", "/<br/>")
                lines.append(f'        {node_id}["{label}"]')
            lines.append("    end")

        return "\n".join(lines)

    # ---- Stats ----

    @property
    def stats(self) -> dict:
        """Summary statistics about the dependency graph."""
        return {
            "total_modules": len(self._modules),
            "total_edges": sum(len(v) for v in self._forward.values()),
            "isolated_modules": len(self.get_isolated_modules()),
            "most_dependents": max(
                self._reverse.items(), key=lambda x: len(x[1]), default=("", [])
            )[0],
            "max_depth": self._compute_max_depth(),
        }

    # ---- Private ----

    def _resolve_import(
        self,
        imp: str,
        from_path: str,
        name_index: Dict[str, List[str]],
    ) -> Optional[str]:
        """Resolve an import string to a known module path."""
        # Normalize the import string: keep dots for relative path counting, 
        # but convert internal dots (module separators) to slashes
        from_dir = (
            "/".join(from_path.replace("\\", "/").split("/")[:-1])
            if "/" in from_path
            else ""
        )

        # Supported file extensions
        extensions = [".py", ".ts", ".tsx", ".js", ".jsx"]

        # Resolve relative imports (../../foo)
        resolved_imp = imp
        dot_count = 0
        if imp.startswith("."):
            # Count the dots and strip them
            while resolved_imp.startswith("."):
                resolved_imp = resolved_imp[1:]
                dot_count += 1
            # Go up (dot_count - 1) directories from from_dir
            parts = from_dir.split("/") if from_dir else []
            if parts and dot_count > 1:
                parts = parts[:-(dot_count - 1)]
            from_dir = "/".join(parts) if parts else ""

        # Normalize remaining path: convert '.' to '/' for module path resolution
        resolved_imp = resolved_imp.replace(".", "/")

        # Candidates to try
        candidates = []
        for ext in extensions:
            candidates.append(resolved_imp + ext)                     # Exact match
            candidates.append(resolved_imp + "/index" + ext)         # index file
            if from_dir:
                candidates.append(from_dir + "/" + resolved_imp + ext)
                candidates.append(from_dir + "/" + resolved_imp + "/index" + ext)

        for cand in candidates:
            if not cand:
                continue
            # Check direct match
            if cand in self._modules:
                return cand
            # Check name_index
            # Normalize: convert path to dotted module name for index check
            norm_cand = cand.replace("/", ".")
            for ext in extensions:
                norm_cand = norm_cand.removesuffix(ext)
            if norm_cand in name_index:
                # Return the best match (prefer same directory)
                matches = name_index[norm_cand]
                for m in matches:
                    if "/".join(m.split("/")[:-1]) == from_dir:
                        return m
                return matches[0]

        # Fuzzy: try matching just the last component
        last = resolved_imp.rsplit("/", 1)[-1] if "/" in resolved_imp else resolved_imp
        if last in name_index:
            matches = name_index[last]
            for m in matches:
                if "/".join(m.split("/")[:-1]) == from_dir:
                    return m
            return matches[0]

        return None

    def _compute_max_depth(self) -> int:
        """Compute the longest dependency chain depth (memoized DFS)."""
        cache: Dict[str, int] = {}
        visiting: Set[str] = set()

        def dfs(path: str) -> int:
            if path in cache:
                return cache[path]
            if path in visiting:  # cycle detected
                return 0
            visiting.add(path)
            max_sub = 0
            for dep in self._forward.get(path, []):
                max_sub = max(max_sub, dfs(dep))
            visiting.discard(path)
            depth = 1 + max_sub if self._forward.get(path) else 0
            cache[path] = depth
            return depth

        for module in self._modules:
            dfs(module)

        return max(cache.values()) if cache else 0
