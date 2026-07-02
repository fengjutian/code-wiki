"""
Domain entities for code analysis results.

These dataclasses represent the structured output of the AST analyzer
and flow through the pipeline: Analyzer → WikiGenerator → Embedder.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime
from enum import Enum


class SupportedLanguage(str, Enum):
    """Languages supported by the analysis pipeline."""
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    INFRA = "infra"

    @classmethod
    def from_extension(cls, ext: str) -> Optional["SupportedLanguage"]:
        mapping = {
            ".py": cls.PYTHON,
            ".ts": cls.TYPESCRIPT,
            ".tsx": cls.TYPESCRIPT,
            ".js": cls.JAVASCRIPT,
            ".jsx": cls.JAVASCRIPT,
        }
        return mapping.get(ext.lower())

    @classmethod
    def extensions(cls) -> dict:
        """Return {language: [extensions]} mapping."""
        return {
            cls.PYTHON: [".py"],
            cls.TYPESCRIPT: [".ts", ".tsx"],
            cls.JAVASCRIPT: [".js", ".jsx"],
        }

    @classmethod
    def all_extensions(cls) -> list:
        """Return all supported file extensions."""
        result = []
        for exts in cls.extensions().values():
            result.extend(exts)
        return result


@dataclass
class SourceAnchor:
    """Pinpoints a source location in the repository."""
    file: str       # Relative path, e.g. "services/user.py"
    line: int       # 1-based line number


@dataclass
class FunctionInfo:
    """Extracted function/method information."""
    name: str
    docstring: Optional[str] = None
    args: List[dict] = field(default_factory=list)
    # args: [{"name": "user_id", "type_annotation": "int", "default": None}, ...]
    returns: Optional[str] = None          # Return type annotation
    anchor: Optional[SourceAnchor] = None  # def line
    end_line: int = 0
    decorators: List[str] = field(default_factory=list)

    @property
    def signature(self) -> str:
        args_str = ", ".join(
            f"{a['name']}: {a.get('type_annotation', 'Any')}"
            + (f" = {a['default']}" if a.get("default") is not None else "")
            for a in self.args
        )
        ret = f" -> {self.returns}" if self.returns else ""
        return f"{self.name}({args_str}){ret}"


@dataclass
class ClassInfo:
    """Extracted class information."""
    name: str
    docstring: Optional[str] = None
    bases: List[str] = field(default_factory=list)      # Parent class names
    methods: List[FunctionInfo] = field(default_factory=list)
    anchor: Optional[SourceAnchor] = None               # class line
    end_line: int = 0
    decorators: List[str] = field(default_factory=list)


@dataclass
class InterfaceInfo:
    """Extracted TypeScript interface/type information."""
    name: str
    members: List[dict] = field(default_factory=list)   # [{"name": "id", "type": "string"}, ...]
    docstring: Optional[str] = None
    anchor: Optional[SourceAnchor] = None
    end_line: int = 0


@dataclass
class ReactComponentInfo:
    """Extracted React component information (PascalCase function returning JSX)."""
    name: str
    props_type: Optional[str] = None
    hooks: List[str] = field(default_factory=list)      # useState, useEffect, etc.
    anchor: Optional[SourceAnchor] = None
    end_line: int = 0


@dataclass
class ModuleInfo:
    """Extracted module information (multi-language)."""
    path: str                                       # Relative path, e.g. "services/user.py"
    language: SupportedLanguage = SupportedLanguage.PYTHON
    docstring: Optional[str] = None                 # Module-level docstring / file header
    imports: List[str] = field(default_factory=list) # Internal imports (relative paths)
    external_imports: List[str] = field(default_factory=list) # External libs
    classes: List[ClassInfo] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    interfaces: List[InterfaceInfo] = field(default_factory=list)  # TS interfaces/types
    components: List[ReactComponentInfo] = field(default_factory=list)  # React components
    exports: List[str] = field(default_factory=list)  # Named exports
    total_lines: int = 0

    @property
    def total_entities(self) -> int:
        """Count of all extractable entities."""
        return (len(self.classes) + len(self.functions)
                + len(self.interfaces) + len(self.components))

    @property
    def all_methods(self) -> List[tuple]:
        """Return all methods with their parent class name."""
        result = []
        for cls in self.classes:
            for m in cls.methods:
                result.append((cls.name, m))
        return result


@dataclass
class WikiPage:
    """Generated Wiki page."""
    path: str               # e.g. "services/user.md"
    source_path: str        # e.g. "services/user.py"
    markdown: str           # Full Markdown content
    anchors_count: int = 0
    generated_at: Optional[datetime] = None
    model: str = ""


@dataclass
class AnalysisState:
    """Tracking state for an analysis run."""
    status: str = "idle"    # idle | scanning | analyzing | generating | done | error
    progress: float = 0.0   # 0.0 - 1.0
    current_step: str = ""
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    total_modules: int = 0
    processed_modules: int = 0
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Phase 2: Call Graph entities
# ---------------------------------------------------------------------------

@dataclass
class CallableEntity:
    """A callable node in the call graph: function or method."""
    id: str                    # unique ID: "file_path::ClassName.method_name" or "file_path::func_name"
    name: str                  # simple name, e.g. "get_user"
    module: str                # relative file path
    parent_class: Optional[str] = None  # class name for methods
    anchor: Optional[SourceAnchor] = None
    end_line: int = 0          # end line of the definition
    kind: str = "function"     # "function" | "method" | "constructor"


@dataclass
class CallEdge:
    """A directed call edge: caller → callee."""
    caller_id: str
    callee_id: str
    call_site: Optional[SourceAnchor] = None  # where the call happens
    resolved: bool = True     # True if callee was resolved to a known entity


@dataclass
class CallGraphData:
    """The complete call graph for a repository."""
    callables: Dict[str, CallableEntity]   # entity_id → entity
    forward: Dict[str, List[str]]           # caller_id → [callee_ids]
    reverse: Dict[str, List[str]]           # callee_id → [caller_ids]
    unresolved_calls: List[CallEdge]        # call edges not resolved to known entities

    @property
    def total_edges(self) -> int:
        return sum(len(v) for v in self.forward.values())

    @property
    def total_callables(self) -> int:
        return len(self.callables)
