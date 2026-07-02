"""Analysis Repository — centralized JSON persistence for analysis data.

All file IO for analysis/call_graph/health_metrics/etc. goes through this module.
No other module (routes, services) should directly read/write .code-wiki/ JSON files.

Usage:
    repo = AnalysisRepository()
    modules = repo.load_analysis()       # returns dict or None
    cg = repo.load_call_graph()          # returns dict or None
    repo.save_call_graph(call_graph_data)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from models.entities import (
    ModuleInfo, ClassInfo, FunctionInfo, InterfaceInfo, ReactComponentInfo,
    SourceAnchor, SupportedLanguage, CallableEntity, CallGraphData,
)

logger = logging.getLogger("code-wiki.repository")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class AnalysisRepository:
    """Centralized access to .code-wiki persisted data."""

    def __init__(self, wiki_path: str | Path):
        self._wiki = Path(wiki_path)

    # ---- Analysis (modules + dependency graph) ----

    def load_analysis(self) -> Optional[dict]:
        """Load analysis.json as raw dict. Returns None if not available."""
        path = self._wiki / "analysis.json"
        return self._read_json(path)

    def save_analysis(self, modules: dict, dep_graph, call_graph_data, mode: str):
        """Persist full analysis output (called from scan pipeline)."""
        self._wiki.mkdir(parents=True, exist_ok=True)

        data = {
            "mode": mode,
            "analyzed_at": datetime.now().isoformat(),
            "modules": {},
        }

        # Serialize dependency graph
        try:
            data["dependency_graph"] = {
                "edges": [
                    {"source": src, "targets": tgts}
                    for src, tgts in dep_graph.get_topology()
                ],
                "stats": dep_graph.stats,
            }
        except Exception:
            data["dependency_graph"] = {"edges": [], "stats": {}}

        # Serialize modules
        for path, module in modules.items():
            data["modules"][path] = _module_to_dict(module)

        self._write_json(self._wiki / "analysis.json", data)

        # Save call graph separately
        if call_graph_data is not None:
            self.save_call_graph(call_graph_data)

        # Save Mermaid diagrams
        mermaid_dir = self._wiki / "diagrams"
        mermaid_dir.mkdir(exist_ok=True)
        try:
            (mermaid_dir / "architecture.mmd").write_text(
                dep_graph.to_architecture_mermaid(), encoding="utf-8")
            (mermaid_dir / "dependencies.mmd").write_text(
                dep_graph.to_mermaid(), encoding="utf-8")
        except Exception:
            pass

    # ---- Call Graph ----

    def load_call_graph(self) -> Optional[dict]:
        """Load call_graph.json. Returns None if not available."""
        return self._read_json(self._wiki / "call_graph.json")

    def save_call_graph(self, call_graph_data) -> None:
        """Persist CallGraphData to call_graph.json."""
        cg_dict = _call_graph_to_dict(call_graph_data)
        self._write_json(self._wiki / "call_graph.json", cg_dict)

    def call_graph_exists(self) -> bool:
        """Check if call_graph.json exists."""
        return (self._wiki / "call_graph.json").exists()

    # ---- Health Metrics ----

    def load_health_metrics(self) -> Optional[dict]:
        """Load cached health metrics."""
        return self._read_json(self._wiki / "health_metrics.json")

    def save_health_metrics(self, metrics: dict) -> None:
        """Cache health metrics to avoid recomputation."""
        self._write_json(self._wiki / "health_metrics.json", metrics)

    # ---- Taint ----

    def load_taint(self) -> Optional[dict]:
        """Load taint analysis results."""
        return self._read_json(self._wiki / "taint_analysis.json")

    def save_taint(self, data: dict) -> None:
        """Save taint analysis results."""
        self._write_json(self._wiki / "taint_analysis.json", data)

    # ---- Schema ----

    def load_schema(self) -> Optional[dict]:
        """Load cached schema data."""
        return self._read_json(self._wiki / "schema.json")

    def save_schema(self, data: dict) -> None:
        """Cache schema analysis to avoid recomputation."""
        self._write_json(self._wiki / "schema.json", data)

    def schema_exists(self) -> bool:
        return (self._wiki / "schema.json").exists()

    # ---- Generic helpers ----

    def analysis_exists(self) -> bool:
        """Check if analysis.json exists."""
        return (self._wiki / "analysis.json").exists()

    # ------------------------------------------------------------------
    # Internal IO
    # ------------------------------------------------------------------

    @staticmethod
    def _read_json(path: Path) -> Optional[dict]:
        """Read a JSON file. Returns None on any error (missing, corrupt, etc.)."""
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError as e:
            logger.warning("JSON decode error in %s: %s", path.name, e)
            return None
        except PermissionError as e:
            logger.warning("Permission denied reading %s: %s", path.name, e)
            return None
        except Exception as e:
            logger.warning("Unexpected error reading %s: %s", path.name, e)
            return None

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        """Write a JSON file. Logs on error, never raises."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("Failed to write %s: %s", path.name, e)


# ---------------------------------------------------------------------------
# Serialization helpers (extracted from routes/scan.py)
# ---------------------------------------------------------------------------

def _module_to_dict(module: ModuleInfo) -> dict:
    """Serialize a ModuleInfo to a JSON-safe dict."""
    return {
        "path": module.path,
        "language": module.language.value,
        "docstring": module.docstring,
        "total_lines": module.total_lines,
        "imports": module.imports,
        "external_imports": module.external_imports,
        "exports": getattr(module, "exports", []),
        "functions": [
            {
                "name": f.name,
                "signature": f.signature,
                "docstring": f.docstring,
                "anchor": _anchor_to_dict(f.anchor),
                "end_line": f.end_line,
                "decorators": f.decorators,
                "args": f.args,
                "returns": f.returns,
            }
            for f in module.functions
        ],
        "classes": [
            {
                "name": c.name,
                "docstring": c.docstring,
                "bases": c.bases,
                "anchor": _anchor_to_dict(c.anchor),
                "end_line": c.end_line,
                "decorators": c.decorators,
                "methods": [
                    {
                        "name": m.name,
                        "signature": m.signature,
                        "docstring": m.docstring,
                        "anchor": _anchor_to_dict(m.anchor),
                        "end_line": m.end_line,
                        "decorators": m.decorators,
                        "args": m.args,
                        "returns": m.returns,
                    }
                    for m in c.methods
                ],
            }
            for c in module.classes
        ],
        "interfaces": [
            {
                "name": i.name,
                "docstring": i.docstring,
                "anchor": _anchor_to_dict(i.anchor),
                "end_line": i.end_line,
                "members": i.members,
            }
            for i in getattr(module, "interfaces", [])
        ],
        "components": [
            {
                "name": c.name,
                "props_type": c.props_type,
                "hooks": c.hooks,
                "anchor": _anchor_to_dict(c.anchor),
                "end_line": c.end_line,
            }
            for c in getattr(module, "components", [])
        ],
    }


def _anchor_to_dict(anchor) -> Optional[dict]:
    if anchor is None:
        return None
    return {"file": anchor.file, "line": anchor.line}


def _call_graph_to_dict(cg) -> dict:
    """Serialize CallGraphData to a JSON-safe dict."""
    callables = {}
    for eid, entity in cg.callables.items():
        callables[eid] = {
            "id": entity.id,
            "name": entity.name,
            "module": entity.module,
            "parent_class": entity.parent_class,
            "kind": entity.kind,
            "anchor": _anchor_to_dict(entity.anchor) if entity.anchor else None,
            "end_line": entity.end_line,
        }
    return {
        "callables": callables,
        "forward": cg.forward,
        "reverse": cg.reverse,
        "unresolved": [
            {
                "caller_id": e.caller_id,
                "callee_id": e.callee_id,
                "resolved": e.resolved,
            }
            for e in cg.unresolved_calls
        ],
    }
