"""
Test Coverage & Impact Analysis.

Analyzes:
1. Impact of code changes via call graph traversal
2. Estimated test coverage by matching test files to production code calls
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from models.entities import CallGraphData, CallableEntity
from services.call_graph import CallGraphBuilder

logger = logging.getLogger("code-wiki.impact")


@dataclass
class ImpactEntry:
    """An entity affected by a change."""
    entity_id: str
    name: str
    module: str
    distance: int           # hops from change point
    path: List[str] = field(default_factory=list)  # call chain


@dataclass
class ImpactReport:
    """Impact analysis report for a set of changed files."""
    changed_files: List[str]
    changed_functions: List[str]
    affected_production: List[ImpactEntry]
    affected_tests: List[ImpactEntry]
    risk_score: float       # 0.0 - 1.0
    summary: str = ""


@dataclass
class CoverageReport:
    """Estimated test coverage report."""
    total_functions: int
    covered_functions: int
    uncovered_functions: List[str]
    coverage_rate: float
    test_files: List[str]


class ImpactAnalyzer:
    """Analyzes impact of code changes using call graph."""

    # Common test file patterns
    TEST_PATTERNS = [
        "test_", "_test", "spec_", "_spec",
        "tests/", "test/", "spec/", "__tests__/",
        ".test.", ".spec.",
    ]

    def __init__(self, call_graph_builder: CallGraphBuilder):
        self._builder = call_graph_builder

    def analyze(
        self,
        changed_files: List[str],
        call_graph: CallGraphData,
    ) -> ImpactReport:
        """Compute impact of changes in changed_files.

        Args:
            changed_files: Files that changed (from git diff or watcher).
            call_graph: Pre-built call graph.
        """
        # Find which callables are in the changed files
        changed_callables: List[str] = []
        for eid, entity in call_graph.callables.items():
            if entity.module in changed_files:
                changed_callables.append(eid)

        if not changed_callables:
            return ImpactReport(
                changed_files=changed_files,
                changed_functions=[],
                affected_production=[],
                affected_tests=[],
                risk_score=0.0,
                summary="No callable entities found in changed files.",
            )

        # Find all callers (production + test)
        all_affected: List[ImpactEntry] = []
        for callee_id in changed_callables:
            transit = self._builder.transitive_callers(callee_id, call_graph, max_depth=5)
            for caller_id in sorted(transit):
                entity = call_graph.callables.get(caller_id)
                if entity is None:
                    continue
                # Find shortest path
                path = self._builder.find_call_path(caller_id, callee_id, call_graph) or []
                all_affected.append(ImpactEntry(
                    entity_id=caller_id,
                    name=entity.name,
                    module=entity.module,
                    distance=len(path) - 1,
                    path=path,
                ))

        # Split into production and test
        test_entries = [e for e in all_affected if self._is_test_file(e.module)]
        production_entries = [e for e in all_affected if not self._is_test_file(e.module)]

        # Risk score: based on number of affected callers and max distance
        total_affected = len(production_entries) + len(test_entries)
        max_distance = max((e.distance for e in all_affected), default=0)
        risk = min(1.0, (total_affected * 0.05 + max_distance * 0.15))

        # Generate summary
        summary = (
            f"Changed {len(changed_files)} file(s), "
            f"{len(changed_callables)} function(s). "
            f"Affected {len(production_entries)} production caller(s), "
            f"{len(test_entries)} test(s). "
            f"Risk: {risk:.0%}"
        )

        return ImpactReport(
            changed_files=changed_files,
            changed_functions=changed_callables,
            affected_production=production_entries,
            affected_tests=test_entries,
            risk_score=round(risk, 2),
            summary=summary,
        )

    def estimate_coverage(
        self,
        call_graph: CallGraphData,
        modules: Dict[str, any],
    ) -> CoverageReport:
        """Estimate test coverage by matching test → production calls."""
        all_functions: List[str] = []
        production_functions: Set[str] = set()
        test_functions: Set[str] = set()
        test_files: Set[str] = set()

        for eid, entity in call_graph.callables.items():
            all_functions.append(eid)
            if self._is_test_file(entity.module):
                test_functions.add(eid)
                test_files.add(entity.module)
            else:
                production_functions.add(eid)

        if not production_functions:
            return CoverageReport(
                total_functions=0, covered_functions=0,
                uncovered_functions=[], coverage_rate=0.0,
                test_files=list(test_files),
            )

        # A production function is "covered" if any test calls it
        covered: Set[str] = set()
        for test_id in test_functions:
            # Get all callees of this test
            for callee in call_graph.forward.get(test_id, []):
                if callee in production_functions:
                    covered.add(callee)
            # Also check transitive (depth 2)
            for callee in call_graph.forward.get(test_id, []):
                if callee in production_functions:
                    covered.add(callee)
                    for deeper in call_graph.forward.get(callee, []):
                        if deeper in production_functions:
                            covered.add(deeper)

        uncovered = sorted(production_functions - covered)
        rate = len(covered) / max(len(production_functions), 1)

        return CoverageReport(
            total_functions=len(production_functions),
            covered_functions=len(covered),
            uncovered_functions=uncovered,
            coverage_rate=round(rate, 3),
            test_files=sorted(test_files),
        )

    @classmethod
    def _is_test_file(cls, path: str) -> bool:
        """Check if a file path matches test file patterns."""
        norm = path.replace("\\", "/").lower()
        for pattern in cls.TEST_PATTERNS:
            if pattern in norm:
                return True
        return False
