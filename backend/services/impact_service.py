"""Impact Analysis Service — estimates change impact using call/dependency graphs."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from models.entities import CallGraphData, CallableEntity
from repositories.analysis_repo import AnalysisRepository

logger = logging.getLogger("code-wiki.impact_service")

# Tunables
MAX_CALL_DEPTH = 5
DEFAULT_RISK_FACTOR = 0.08
MAX_RESULTS = 20


class ImpactService:
    """Computes change impact analysis from call graph data."""

    def __init__(self, repo: AnalysisRepository):
        self._repo = repo

    def analyze(self, changed_files: List[str]) -> dict:
        """Analyze impact of changing the given files.

        Returns a dict suitable for JSON response:
        {risk_score, changed_functions, affected_production, affected_tests, summary}
        """
        if not changed_files:
            return _empty_result("No files specified.")

        cg_data = self._repo.load_call_graph()
        if cg_data:
            return self._analyze_with_call_graph(cg_data, changed_files)

        return _empty_result("需要调用图数据。请先运行完整的代码分析。")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _analyze_with_call_graph(self, cg_data: dict, files: List[str]) -> dict:
        """Use call graph for precise impact analysis."""
        callables, forward, reverse = _parse_call_graph(cg_data)
        if not callables:
            return _empty_result("未在变更文件中找到函数调用关系。")

        changed_fns = [
            eid for eid, e in callables.items() if e.module in files
        ]
        if not changed_fns:
            return _empty_result("未在变更文件中找到函数调用关系。")

        # BFS to find transitive callers (use deque for O(1) popleft)
        from collections import deque
        all_affected: set = set()
        for fn_id in changed_fns:
            queue: deque[str] = deque([fn_id])
            depth = 0
            visited = {fn_id}
            while queue and depth < MAX_CALL_DEPTH:
                cur = queue.popleft()
                for caller in reverse.get(cur, []):
                    if caller not in visited and caller not in changed_fns:
                        visited.add(caller)
                        all_affected.add(caller)
                        queue.append(caller)
                depth += 1

        prod, tests = [], []
        for eid in all_affected:
            e = callables.get(eid)
            if e:
                entry = {"name": e.name, "module": e.module, "distance": 1}
                if _is_test_file(e.module):
                    tests.append(entry)
                else:
                    prod.append(entry)

        risk = min(1.0, len(all_affected) * DEFAULT_RISK_FACTOR)
        return {
            "risk_score": round(risk, 2),
            "changed_functions": [
                c.split("::")[-1] for c in changed_fns[:MAX_RESULTS]
            ],
            "affected_production": prod[:MAX_RESULTS],
            "affected_tests": tests[:MAX_RESULTS],
            "summary": (
                f"变更 {len(files)} 个文件({len(changed_fns)} 个函数)，"
                f"影响 {len(prod)} 个生产函数 + {len(tests)} 个测试。"
            ),
        }


def _parse_call_graph(cg_data: dict):
    """Reconstruct callables + forward/reverse from JSON dict."""
    callables: Dict[str, CallableEntity] = {}
    for eid, info in cg_data.get("callables", {}).items():
        callables[eid] = CallableEntity(
            id=eid,
            name=info.get("name", ""),
            module=info.get("module", ""),
            parent_class=info.get("parent_class"),
            kind=info.get("kind", "function"),
        )
    return callables, cg_data.get("forward", {}), cg_data.get("reverse", {})


def _is_test_file(path: str) -> bool:
    """Check if a file path matches test file patterns."""
    norm = path.replace("\\", "/").lower()
    for pattern in ("test_", "_test", "spec_", "_spec", "tests/", "test/",
                     "spec/", "__tests__/", ".test.", ".spec."):
        if pattern in norm:
            return True
    return False


def _empty_result(summary: str) -> dict:
    return {
        "risk_score": 0.0,
        "changed_functions": [],
        "affected_production": [],
        "affected_tests": [],
        "summary": summary,
    }
