"""
Project Health Dashboard — metrics aggregation and risk assessment.

Computes quantitative code quality metrics and identifies risk hotspots
by combining cyclomatic complexity, coupling, churn, and coverage data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from models.entities import ModuleInfo, CallGraphData

logger = logging.getLogger("code-wiki.health")


@dataclass
class HealthMetrics:
    """Aggregate project health metrics."""

    # Scale
    total_modules: int = 0
    total_functions: int = 0
    total_classes: int = 0
    total_lines: int = 0

    # Complexity
    avg_cyclomatic_complexity: float = 0.0
    max_cyclomatic_complexity: int = 0
    complex_functions: List[Tuple[str, int]] = field(default_factory=list)

    # Coupling
    avg_coupling: float = 0.0
    max_coupling: int = 0
    isolated_modules: int = 0

    # Churn (populated externally from git)
    churn_rate: Dict[str, int] = field(default_factory=dict)

    # Quality
    dead_code_blocks: int = 0
    test_coverage: float = 0.0

    # Scoring
    overall_health_score: float = 0.0
    risk_hotspots: List[dict] = field(default_factory=list)


class HealthMetricsCalculator:
    """Computes project health metrics from analysis data."""

    def compute(
        self,
        modules: Dict[str, ModuleInfo],
        call_graph: Optional[CallGraphData] = None,
        cfgs: Optional[Dict[str, any]] = None,          # {func_id: ControlFlowGraph}
        coverage: Optional[float] = None,
        churn: Optional[Dict[str, int]] = None,          # {file: change_count}
    ) -> HealthMetrics:
        """Compute all health metrics."""
        metrics = HealthMetrics()

        # Scale
        metrics.total_modules = len(modules)
        metrics.total_lines = sum(m.total_lines for m in modules.values())

        func_count = 0
        class_count = 0
        for m in modules.values():
            func_count += len(m.functions)
            class_count += len(m.classes)
            for cls in m.classes:
                func_count += len(cls.methods)

        metrics.total_functions = func_count
        metrics.total_classes = class_count

        # Complexity (from CFGs if available)
        if cfgs:
            complexities = [cfg.cyclomatic_complexity for cfg in cfgs.values()]
            if complexities:
                metrics.avg_cyclomatic_complexity = sum(complexities) / len(complexities)
                metrics.max_cyclomatic_complexity = max(complexities)
                # Top-10 complex functions
                sorted_cfgs = sorted(cfgs.items(), key=lambda x: x[1].cyclomatic_complexity, reverse=True)
                metrics.complex_functions = [
                    (name, cfg.cyclomatic_complexity) for name, cfg in sorted_cfgs[:10]
                ]

                # Dead code
                metrics.dead_code_blocks = sum(
                    len(cfg.unreachable_blocks) for cfg in cfgs.values()
                )

        # Coupling (from call graph)
        if call_graph:
            degrees = [len(call_graph.forward.get(eid, [])) for eid in call_graph.callables]
            if degrees:
                metrics.avg_coupling = sum(degrees) / len(degrees)
                metrics.max_coupling = max(degrees)

            # Isolated: functions with 0 incoming + 0 outgoing
            isolated = sum(
                1 for eid in call_graph.callables
                if len(call_graph.forward.get(eid, [])) == 0
                and len(call_graph.reverse.get(eid, [])) == 0
            )
            metrics.isolated_modules = isolated

        # Churn
        if churn:
            metrics.churn_rate = churn

        # Coverage
        if coverage is not None:
            metrics.test_coverage = coverage

        # Overall health score (0-100)
        metrics.overall_health_score = self._compute_score(metrics)

        # Hotspots
        metrics.risk_hotspots = self._find_hotspots(metrics, modules, call_graph or CallGraphData({}, {}, {}, []))

        return metrics

    def _compute_score(self, m: HealthMetrics) -> float:
        """Weighted composite health score (0-100, higher = healthier)."""
        score = 100.0

        # Complexity penalty
        if m.avg_cyclomatic_complexity > 10:
            score -= min(20, (m.avg_cyclomatic_complexity - 10) * 2)

        # Max complexity penalty
        if m.max_cyclomatic_complexity > 20:
            score -= min(15, (m.max_cyclomatic_complexity - 20) * 0.5)

        # Coupling penalty
        if m.avg_coupling > 5:
            score -= min(10, (m.avg_coupling - 5))

        # Isolation penalty (many isolated functions = poor design)
        if m.total_functions > 0 and m.isolated_modules / m.total_functions > 0.3:
            score -= 10

        # Dead code penalty
        if m.dead_code_blocks > 0:
            score -= min(10, m.dead_code_blocks * 2)

        # Coverage bonus
        if m.test_coverage > 0:
            score += min(10, m.test_coverage * 10)

        # Churn penalty
        if m.churn_rate:
            high_churn = sum(1 for v in m.churn_rate.values() if v > 10)
            score -= min(10, high_churn * 2)

        return max(0, min(100, score))

    def _find_hotspots(
        self,
        m: HealthMetrics,
        modules: Dict[str, ModuleInfo],
        call_graph: CallGraphData,
    ) -> List[dict]:
        """Identify risk hotspots: high-complexity + high-coupling + high-churn files."""
        hotspots: List[dict] = []

        for rel_path in modules:
            risk = 0.0
            reasons: List[str] = []

            # Complexity factor
            module_cfgs = [
                cfg for eid, cfg in (getattr(self, '_cfgs', {}) or {}).items()
                if eid.startswith(rel_path + "::")
            ]
            if module_cfgs:
                avg_cc = sum(c.cyclomatic_complexity for c in module_cfgs) / len(module_cfgs)
                if avg_cc > 10:
                    risk += 0.3
                    reasons.append(f"avg CC={avg_cc:.1f}")

            # Coupling factor
            if call_graph.callables:
                module_edges = sum(
                    len(call_graph.forward.get(eid, []))
                    for eid in call_graph.callables
                    if eid.startswith(rel_path + "::")
                )
                if module_edges > 5:
                    risk += min(0.4, module_edges * 0.05)
                    reasons.append(f"coupling={module_edges}")

            # Churn factor
            churn_count = m.churn_rate.get(rel_path, 0)
            if churn_count > 5:
                risk += min(0.3, churn_count * 0.03)
                reasons.append(f"churn={churn_count}")

            if risk > 0:
                hotspots.append({
                    "file": rel_path,
                    "risk_score": round(risk, 2),
                    "reasons": reasons,
                })

        hotspots.sort(key=lambda x: -x["risk_score"])
        return hotspots[:10]
