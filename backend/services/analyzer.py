"""
Python AST analyzer — extracts structured information from .py files.
Multi-language dispatch: routes .ts/.tsx/.js/.jsx to TypeScriptAnalyzer.

Parses Python source files and extracts:
- Module-level docstrings
- Classes with methods, bases, decorators
- Functions with signatures, return types, decorators
- Import relationships (internal and external)
- Source anchors (file:line) for every entity
"""

import ast
import os
from typing import List, Dict, Optional, Set, Tuple

from models.entities import (
    ModuleInfo, ClassInfo, FunctionInfo, SourceAnchor, SupportedLanguage
)
from services.ts_analyzer import TypeScriptAnalyzer


class Analyzer:
    """Parses Python source files using the ast module."""

    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    # ---- Public API ----

    def analyze_file(self, rel_path: str) -> ModuleInfo:
        """
        Parse a single source file and return structured info.
        Dispatches to the correct analyzer based on file extension.
        """
        ext = os.path.splitext(rel_path)[1].lower()
        if ext in {".ts", ".tsx", ".js", ".jsx"}:
            ts_analyzer = TypeScriptAnalyzer(self.repo_path)
            return ts_analyzer.analyze_file(rel_path)
        return self._analyze_python_file(rel_path)

    def _analyze_python_file(self, rel_path: str) -> ModuleInfo:
        """Parse a single .py file and return structured info."""
        full_path = os.path.join(self.repo_path, rel_path)
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            # Return a minimal module for files with syntax errors
            return ModuleInfo(
                path=rel_path,
                language=SupportedLanguage.PYTHON,
                docstring=f"[Syntax Error] {e.msg}",
                total_lines=len(source.splitlines()),
            )

        total_lines = len(source.splitlines())
        docstring = ast.get_docstring(tree)

        imports, external_imports = self._extract_imports(tree)
        classes, functions = self._extract_top_level(tree, rel_path)

        return ModuleInfo(
            path=rel_path,
            language=SupportedLanguage.PYTHON,
            docstring=docstring,
            imports=sorted(imports),
            external_imports=sorted(external_imports),
            classes=classes,
            functions=functions,
            total_lines=total_lines,
        )

    def analyze_batch(self, files: List[str]) -> Dict[str, ModuleInfo]:
        """Analyze multiple files, returning {rel_path: ModuleInfo}."""
        result: Dict[str, ModuleInfo] = {}
        for rel_path in files:
            result[rel_path] = self.analyze_file(rel_path)
        return result

    def find_affected_files(
        self, changed_files: List[str], modules: Dict[str, ModuleInfo]
    ) -> List[str]:
        """
        For incremental analysis: find all files that import any of the changed files.
        Returns changed_files + files that depend on them.
        """
        affected: Set[str] = set(changed_files)

        # Build reverse dependency: which files import each module?
        # Map module basename → importing file
        importers: Dict[str, Set[str]] = {}
        for file_path, module in modules.items():
            for imp in module.imports:
                imp_stripped = imp.lstrip(".")
                # Normalize: remove leading dots, match by suffix
                importers.setdefault(imp_stripped, set()).add(file_path)
                # Also try matching with .py stripped
                if imp_stripped.endswith(".py"):
                    importers.setdefault(imp_stripped[:-3], set()).add(file_path)

        for changed in changed_files:
            # Normalize changed path for matching
            key = changed.replace("\\", "/")
            if key.endswith(".py"):
                key_no_ext = key[:-3]

                # Find files importing this module
                for candidate_key in (key, key_no_ext, os.path.basename(key_no_ext)):
                    if candidate_key in importers:
                        affected.update(importers[candidate_key])

                # Also check partial matches (e.g., "services.user" matches "from services.user import X")
                for imp_path, files in importers.items():
                    if imp_path.endswith(key_no_ext) or key_no_ext.endswith(imp_path):
                        affected.update(files)

        return sorted(affected)

    # ---- Private helpers ----

    def _extract_top_level(
        self, tree: ast.Module, rel_path: str
    ) -> Tuple[List[ClassInfo], List[FunctionInfo]]:
        """Extract top-level classes and functions."""
        classes: List[ClassInfo] = []
        functions: List[FunctionInfo] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(self._extract_class(node, rel_path))
            elif isinstance(node, ast.FunctionDef):
                functions.append(self._extract_function(node, rel_path))

        return classes, functions

    def _extract_class(self, node: ast.ClassDef, rel_path: str) -> ClassInfo:
        """Extract a ClassInfo from a ClassDef AST node."""
        bases = [self._name_of(b) for b in node.bases]
        methods = [
            self._extract_function(n, rel_path)
            for n in ast.iter_child_nodes(node)
            if isinstance(n, ast.FunctionDef)
        ]

        return ClassInfo(
            name=node.name,
            docstring=ast.get_docstring(node),
            bases=bases,
            methods=methods,
            anchor=SourceAnchor(file=rel_path, line=node.lineno),
            end_line=node.end_lineno or node.lineno,
            decorators=[self._name_of(d) for d in node.decorator_list],
        )

    def _extract_function(
        self, node: ast.FunctionDef, rel_path: str
    ) -> FunctionInfo:
        """Extract a FunctionInfo from a FunctionDef AST node."""
        args: List[dict] = []
        # Positional args
        for arg in node.args.args:
            args.append(
                {
                    "name": arg.arg,
                    "type_annotation": self._annotation_of(arg.annotation),
                    "default": None,  # Will be filled below
                }
            )

        # Apply defaults (they align with the last N positional args)
        defaults = node.args.defaults
        if defaults:
            offset = len(args) - len(defaults)
            for i, default in enumerate(defaults):
                idx = offset + i
                if 0 <= idx < len(args):
                    args[idx]["default"] = self._value_of(default)

        # kwonly args with defaults
        for arg, default in zip(
            node.args.kwonlyargs, node.args.kw_defaults
        ):
            args.append(
                {
                    "name": arg.arg,
                    "type_annotation": self._annotation_of(arg.annotation),
                    "default": self._value_of(default) if default else None,
                }
            )

        returns = self._annotation_of(node.returns)

        return FunctionInfo(
            name=node.name,
            docstring=ast.get_docstring(node),
            args=args,
            returns=returns,
            anchor=SourceAnchor(file=rel_path, line=node.lineno),
            end_line=node.end_lineno or node.lineno,
            decorators=[self._name_of(d) for d in node.decorator_list],
        )

    def _extract_imports(self, tree: ast.Module) -> Tuple[List[str], List[str]]:
        """
        Extract import statements.
        Returns (internal_imports, external_imports).
        Internal = relative import that can be resolved within the repo.
        External = third-party or stdlib.
        """
        internal: Set[str] = set()
        external: Set[str] = set()

        # Known stdlib modules (abbreviated list)
        stdlib = {
            "os", "sys", "re", "json", "time", "datetime", "collections",
            "typing", "abc", "io", "pathlib", "math", "random", "logging",
            "unittest", "itertools", "functools", "asyncio", "subprocess",
            "hashlib", "uuid", "dataclasses", "enum", "copy", "textwrap",
            "argparse", "traceback", "warnings", "contextlib", "inspect",
            "ast", "threading", "multiprocessing", "queue", "socket",
            "http", "urllib", "xml", "csv", "sqlite3", "pickle", "shutil",
            "tempfile", "glob", "fnmatch", "statistics", "decimal",
            "fractions", "concurrent", "importlib", "pkgutil", "types",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name.split(".")[0]
                    if name in stdlib:
                        external.add(alias.name)
                    else:
                        internal.add(alias.name)

            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                module = node.module
                top = module.split(".")[0]

                if node.level > 0:  # Relative import: from .xxx import y
                    # Resolve relative import to a file path candidate
                    if module:  # Skip empty-string imports ("from . import X")
                        internal.add(module)
                elif top in stdlib:
                    external.add(module)
                else:
                    internal.add(module)

        # Filter: keep only internal imports that look like they could be repo files
        resolved_internal = []
        for imp in internal:
            # Skip obvious external packages
            if imp.split(".")[0] in stdlib:
                external.add(imp)
            else:
                resolved_internal.append(imp)

        return resolved_internal, sorted(external)

    # ---- AST value extractors ----

    def _name_of(self, node: ast.expr) -> str:
        """Get a human-readable name from an AST expression node."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._name_of(node.value)}.{node.attr}"
        if isinstance(node, ast.Subscript):
            return f"{self._name_of(node.value)}[...]"
        if isinstance(node, ast.Call):
            return f"{self._name_of(node.func)}(...)"
        if isinstance(node, ast.Constant):
            return repr(node.value)
        return "..."

    def _annotation_of(self, node: Optional[ast.expr]) -> Optional[str]:
        """Get type annotation as string."""
        if node is None:
            return None
        return self._name_of(node)

    def _value_of(self, node: Optional[ast.expr]) -> Optional[str]:
        """Get a default value as string representation."""
        if node is None:
            return None
        if isinstance(node, ast.Constant):
            if node.value is None:
                return "None"
            if isinstance(node.value, str):
                return repr(node.value)
            return str(node.value)
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return f"-{self._value_of(node.operand)}"
        return self._name_of(node)
