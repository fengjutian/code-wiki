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

    # Code smells (from analysis.json)
    long_functions: int = 0         # functions > 50 lines
    many_params_functions: int = 0  # functions with > 5 parameters
    god_classes: int = 0            # classes with > 10 methods

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
        """Weighted composite health score (0-100, higher = healthier).

        Scoring tiers designed so that a typical well-maintained project scores
        70-85; excellent codebases 90+; and problematic ones < 50.
        """
        score = 100.0

        # ---- Complexity penalty (cyclomatic complexity) ----
        # CC 1-5: excellent, 6-10: good, 11-20: moderate, >20: complex
        if m.avg_cyclomatic_complexity > 0:
            # Base penalty: each point of avg CC above 3 costs 2 points
            excess = max(0, m.avg_cyclomatic_complexity - 3)
            score -= min(25, excess * 2)

        # Max CC: extremely complex functions are a risk
        if m.max_cyclomatic_complexity > 10:
            score -= min(15, (m.max_cyclomatic_complexity - 10) * 0.8)

        # ---- Coupling penalty ----
        # Coupling 0-3: loose, 4-8: moderate, >8: tight
        if m.avg_coupling > 0:
            excess = max(0, m.avg_coupling - 3)
            score -= min(15, excess * 2)

        if m.max_coupling > 5:
            score -= min(10, (m.max_coupling - 5))

        # ---- Isolation penalty ----
        # Many functions with zero callers/callees → poor cohesion
        if m.total_functions > 0 and m.isolated_modules / m.total_functions > 0.2:
            score -= 8

        # ---- Dead code penalty ----
        if m.dead_code_blocks > 0:
            score -= min(10, m.dead_code_blocks * 3)

        # ---- Size penalty (very large projects are harder to maintain) ----
        if m.total_lines > 50000:
            score -= min(5, (m.total_lines / 100000) * 5)

        # ---- Coverage bonus ----
        if m.test_coverage > 0:
            score += min(15, m.test_coverage * 15)

        # ---- Churn penalty ----
        if m.churn_rate:
            high_churn = sum(1 for v in m.churn_rate.values() if v > 10)
            score -= min(10, high_churn * 2)

        # ---- Code smell penalties ----
        # Long functions (> 50 lines): penalty proportional to ratio
        if m.total_functions > 0 and m.long_functions > 0:
            ratio = m.long_functions / m.total_functions
            score -= min(10, ratio * 25)  # 40% long → -10

        # Many-parameter functions (> 5 params)
        if m.total_functions > 0 and m.many_params_functions > 0:
            ratio = m.many_params_functions / m.total_functions
            score -= min(8, ratio * 20)

        # God classes (> 10 methods)
        if m.total_classes > 0 and m.god_classes > 0:
            ratio = m.god_classes / m.total_classes
            score -= min(8, ratio * 16)

        return max(0, min(100, score))

    def _compute_breakdown(self, m: HealthMetrics) -> list[dict]:
        """Return step-by-step score breakdown for transparency."""
        steps: list[dict] = []
        score = 100.0
        steps.append({"factor": "基础分", "detail": "起始分数", "effect": "+100", "score": 100.0})

        # Complexity
        if m.avg_cyclomatic_complexity > 0:
            excess = max(0, m.avg_cyclomatic_complexity - 3)
            penalty = min(25, excess * 2)
            if penalty > 0:
                score -= penalty
                steps.append({
                    "factor": "平均圈复杂度",
                    "detail": f"avg_cc={m.avg_cyclomatic_complexity:.1f}, 阈值 3, 超出 {excess:.1f} × 2",
                    "effect": f"-{penalty:.1f}",
                    "score": round(score, 1),
                })
            else:
                steps.append({
                    "factor": "平均圈复杂度",
                    "detail": f"avg_cc={m.avg_cyclomatic_complexity:.1f} ≤ 阈值 3, 无惩罚",
                    "effect": "0",
                    "score": round(score, 1),
                })

        if m.max_cyclomatic_complexity > 10:
            penalty = min(15, (m.max_cyclomatic_complexity - 10) * 0.8)
            score -= penalty
            steps.append({
                "factor": "最大圈复杂度",
                "detail": f"max_cc={m.max_cyclomatic_complexity}, 阈值 10, 超出 {m.max_cyclomatic_complexity - 10} × 0.8",
                "effect": f"-{penalty:.1f}",
                "score": round(score, 1),
            })

        # Coupling
        if m.avg_coupling > 0:
            excess = max(0, m.avg_coupling - 3)
            penalty = min(15, excess * 2)
            if penalty > 0:
                score -= penalty
                steps.append({
                    "factor": "平均耦合度",
                    "detail": f"avg_coupling={m.avg_coupling:.1f}, 阈值 3, 超出 {excess:.1f} × 2",
                    "effect": f"-{penalty:.1f}",
                    "score": round(score, 1),
                })

        if m.max_coupling > 5:
            penalty = min(10, (m.max_coupling - 5))
            score -= penalty
            steps.append({
                "factor": "最大耦合度",
                "detail": f"max_coupling={m.max_coupling}, 阈值 5, 超出 {m.max_coupling - 5}",
                "effect": f"-{penalty:.1f}",
                "score": round(score, 1),
            })

        # Isolation
        if m.total_functions > 0 and m.isolated_modules / m.total_functions > 0.2:
            score -= 8
            steps.append({
                "factor": "孤岛函数",
                "detail": f"isolated={m.isolated_modules}/{m.total_functions} > 20%",
                "effect": "-8",
                "score": round(score, 1),
            })

        # Dead code
        if m.dead_code_blocks > 0:
            penalty = min(10, m.dead_code_blocks * 3)
            score -= penalty
            steps.append({
                "factor": "死代码",
                "detail": f"dead_code_blocks={m.dead_code_blocks} × 3",
                "effect": f"-{penalty}",
                "score": round(score, 1),
            })

        # Size
        if m.total_lines > 50000:
            penalty = min(5, (m.total_lines / 100000) * 5)
            score -= penalty
            steps.append({
                "factor": "代码规模",
                "detail": f"total_lines={m.total_lines} > 50000",
                "effect": f"-{penalty:.1f}",
                "score": round(score, 1),
            })

        # Coverage bonus
        if m.test_coverage > 0:
            bonus = min(15, m.test_coverage * 15)
            score += bonus
            steps.append({
                "factor": "测试覆盖率",
                "detail": f"coverage={m.test_coverage:.0%} × 15",
                "effect": f"+{bonus:.1f}",
                "score": round(score, 1),
            })

        # Churn
        if m.churn_rate:
            high_churn = sum(1 for v in m.churn_rate.values() if v > 10)
            if high_churn > 0:
                penalty = min(10, high_churn * 2)
                score -= penalty
                steps.append({
                    "factor": "变更热度",
                    "detail": f"high_churn_files={high_churn} × 2",
                    "effect": f"-{penalty}",
                    "score": round(score, 1),
                })

        # ---- Code smell penalties ----
        if m.total_functions > 0 and m.long_functions > 0:
            ratio = m.long_functions / m.total_functions
            penalty = min(10, ratio * 25)
            score -= penalty
            steps.append({
                "factor": "过长函数",
                "detail": f"{m.long_functions}/{m.total_functions} 函数 >50 行 ({ratio:.0%})",
                "effect": f"-{penalty:.1f}",
                "score": round(score, 1),
            })

        if m.total_functions > 0 and m.many_params_functions > 0:
            ratio = m.many_params_functions / m.total_functions
            penalty = min(8, ratio * 20)
            score -= penalty
            steps.append({
                "factor": "过多参数",
                "detail": f"{m.many_params_functions}/{m.total_functions} 函数 >5 参数 ({ratio:.0%})",
                "effect": f"-{penalty:.1f}",
                "score": round(score, 1),
            })

        if m.total_classes > 0 and m.god_classes > 0:
            ratio = m.god_classes / m.total_classes
            penalty = min(8, ratio * 16)
            score -= penalty
            steps.append({
                "factor": "过大类",
                "detail": f"{m.god_classes}/{m.total_classes} 类 >10 方法 ({ratio:.0%})",
                "effect": f"-{penalty:.1f}",
                "score": round(score, 1),
            })

        final = max(0, min(100, score))
        steps.append({"factor": "最终评分", "detail": "", "effect": f"= {final:.0f}", "score": final})
        return steps

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
