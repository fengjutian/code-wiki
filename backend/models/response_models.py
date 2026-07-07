"""Pydantic Response Models — typed API responses for all metrics endpoints.

Replaces bare dict returns with validated, documented response schemas
that show up in Swagger UI and provide IDE autocompletion.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HotspotItem(BaseModel):
    file: str
    risk_score: float
    reasons: List[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    total_modules: int = 0
    total_functions: int = 0
    total_classes: int = 0
    total_lines: int = 0
    avg_cyclomatic_complexity: float = 0.0
    max_cyclomatic_complexity: int = 0
    avg_coupling: float = 0.0
    max_coupling: int = 0
    isolated_modules: int = 0
    test_coverage: float = 0.0
    health_score: Optional[float] = None
    hotspots: List[HotspotItem] = Field(default_factory=list)
    complex_functions: List = Field(default_factory=list)  # [(name, cc), ...]
    # Additional metrics from analysis.json
    language_breakdown: dict[str, int] = Field(default_factory=dict)
    docstring_coverage: float = 0.0           # 0.0-1.0, functions with docstrings / total
    external_deps: int = 0                     # unique external packages imported
    total_imports: int = 0                     # internal import edges
    score_breakdown: list[dict] = Field(default_factory=list)  # scoring formula steps
    # Code smell counts
    long_functions: int = 0
    many_params_functions: int = 0
    god_classes: int = 0
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Call Graph
# ---------------------------------------------------------------------------

class CallableItem(BaseModel):
    id: str
    name: str
    module: str
    parent_class: Optional[str] = None
    kind: str = "function"


class CallGraphEdge(BaseModel):
    source: str
    target: str


class CallGraphResponse(BaseModel):
    callables: dict[str, CallableItem] = Field(default_factory=dict)
    edges: List[CallGraphEdge] = Field(default_factory=list)
    unresolved: list = Field(default_factory=list)
    note: Optional[str] = None


class CallersResponse(BaseModel):
    entity_id: Optional[str] = None
    callers: List[str] = Field(default_factory=list)
    count: int = 0
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Taint
# ---------------------------------------------------------------------------

class TaintFlowItem(BaseModel):
    source: str
    sink: str
    risk_level: str = "medium"


class TaintResponse(BaseModel):
    flows: List[TaintFlowItem] = Field(default_factory=list)
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Impact
# ---------------------------------------------------------------------------

class AffectedItem(BaseModel):
    name: str
    module: str
    distance: int = 1


class ImpactResponse(BaseModel):
    risk_score: float = 0.0
    changed_functions: List[str] = Field(default_factory=list)
    affected_production: List[AffectedItem] = Field(default_factory=list)
    affected_tests: List[AffectedItem] = Field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# CFG
# ---------------------------------------------------------------------------

class CFGResponse(BaseModel):
    function_name: str = ""
    cyclomatic_complexity: int = 0
    nesting_depth: int = 0
    blocks_count: int = 0
    unreachable_blocks: list = Field(default_factory=list)
    mermaid: str = ""
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class SearchPattern(BaseModel):
    name: str
    label: str
    description: str
    languages: List[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    file: str
    line: int
    match: str
    language: Optional[str] = None


class SearchResponse(BaseModel):
    results: List[SearchResult] = Field(default_factory=list)
    pattern: Optional[str] = None
    query: Optional[str] = None
    count: int = 0
    note: Optional[str] = None
    error: Optional[str] = None


class PatternListResponse(BaseModel):
    patterns: List[SearchPattern] = Field(default_factory=list)
