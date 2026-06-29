"""
TypeScript/JavaScript analyzer — extracts structure from frontend source files.

Uses regex-based parsing (no external dependencies) to extract:
- ES module imports/exports
- Function declarations (regular + arrow functions)
- Class declarations
- TypeScript interfaces and type aliases
- React components (PascalCase functions returning JSX)
- Hook usage tracking

Limitations (regex-based):
- Does not fully parse nested JSX expressions
- May miss some complex generic type patterns
- Arrow function parameter detection is best-effort
"""

import os
import re
from typing import List, Optional, Tuple

from models.entities import (
    ModuleInfo,
    FunctionInfo,
    ClassInfo,
    InterfaceInfo,
    ReactComponentInfo,
    SourceAnchor,
    SupportedLanguage,
)


class TypeScriptAnalyzer:
    """Parses TypeScript/JavaScript files using regex patterns."""

    # Regex patterns
    _IMPORT_PATTERN = re.compile(
        r"""
        (?:import\s+[\s\S]*?\s+from\s+['"]([^'"]+)['"]\s*;?)     # import X from '...'
        |
        (?:import\s+['"]([^'"]+)['"]\s*;?)                        # import '...'
        |
        (?:import\s*\(\s*['"]([^'"]+)['"]\s*\))                   # dynamic import()
        """,
        re.VERBOSE | re.MULTILINE,
    )

    _EXPORT_PATTERN = re.compile(
        r"""
        ^\s*export\s+(?:default\s+)?(?:const|let|var|function|class|interface|type|enum)\s+(\w+)
        |
        ^\s*export\s*\{\s*([^}]+)\s*\}\s*;?                        # export { ... }
        """,
        re.VERBOSE | re.MULTILINE,
    )

    _FUNCTION_DECL_PATTERN = re.compile(
        r"""
        (?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(
        """,
        re.VERBOSE | re.MULTILINE,
    )

    _ARROW_FN_PATTERN = re.compile(
        r"""
        (?:export\s+)?(?:default\s+)?(?:const|let|var)\s+(\w+)\s*=\s*
        (?:(?:async\s+)?\(([^)]*)\)\s*:\s*([^=]+))?\s*=>           # (params) => or (params): Type =>
        """,
        re.VERBOSE | re.MULTILINE,
    )

    _CLASS_PATTERN = re.compile(
        r"""
        (?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)
        (?:\s+extends\s+(\w+))?                                      # extends ParentClass
        (?:\s+implements\s+([\w,\s<>,]+))?                           # implements IFoo, IBar
        """,
        re.VERBOSE | re.MULTILINE,
    )

    _INTERFACE_PATTERN = re.compile(
        r"""
        (?:export\s+)?(?:interface|type)\s+(\w+)
        (?:\s*<\s*[\w,\s]+\s*>)?                                     # generic params <T>
        (?:\s+extends\s+([\w,\s<>,]+))?                              # extends
        """,
        re.VERBOSE | re.MULTILINE,
    )

    _JSX_RETURN_PATTERN = re.compile(
        r"""
        (?:return\s*\(?\s*<|return\s*<)
        """,
        re.VERBOSE,
    )

    _TSX_EXTENSIONS = {".tsx", ".jsx"}

    # Hook names (React built-in)
    _REACT_HOOKS = {
        "useState", "useEffect", "useContext", "useReducer",
        "useCallback", "useMemo", "useRef", "useImperativeHandle",
        "useLayoutEffect", "useDebugValue", "useTransition",
        "useDeferredValue", "useId", "useSyncExternalStore",
        "useInsertionEffect",
    }

    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def analyze_file(self, rel_path: str) -> ModuleInfo:
        """Parse a single .ts/.tsx/.js/.jsx file and return structured info."""
        full_path = os.path.join(self.repo_path, rel_path)
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()

        ext = os.path.splitext(rel_path)[1].lower()
        language = (
            SupportedLanguage.TYPESCRIPT
            if ext in {".ts", ".tsx"}
            else SupportedLanguage.JAVASCRIPT
        )

        lines = source.splitlines()
        total_lines = len(lines)

        # Extract file header comment as docstring
        docstring = self._extract_file_header(source)

        # Extraction passes
        imports = self._extract_imports(source)
        external_imports = self._classify_external_imports(imports)
        exports = self._extract_exports(source)
        functions = self._extract_functions(source, rel_path)
        classes = self._extract_classes(source, rel_path)
        interfaces = self._extract_interfaces(source, rel_path)
        components = self._extract_components(source, rel_path, lines)

        return ModuleInfo(
            path=rel_path,
            language=language,
            docstring=docstring,
            imports=imports,
            external_imports=external_imports,
            classes=classes,
            functions=functions,
            interfaces=interfaces,
            components=components,
            exports=exports,
            total_lines=total_lines,
        )

    def analyze_batch(self, files: List[str]) -> dict:
        """Analyze multiple files, returning {rel_path: ModuleInfo}."""
        result = {}
        for rel_path in files:
            result[rel_path] = self.analyze_file(rel_path)
        return result

    # ---- Extraction Methods ----

    def _extract_file_header(self, source: str) -> Optional[str]:
        """Extract file-level JSDoc or header comment."""
        # JSDoc /** ... */ at top of file
        jsdoc_match = re.match(r'^\s*/\*\*([\s\S]*?)\*/', source)
        if jsdoc_match:
            text = jsdoc_match.group(1)
            # Strip leading * from each line
            lines = []
            for line in text.split("\n"):
                cleaned = re.sub(r'^\s*\*\s?', '', line).strip()
                if cleaned:
                    lines.append(cleaned)
            return "\n".join(lines[:10]) if lines else None
        # Single-line comment at top
        single_match = re.match(r'^\s*//\s*(.+)', source)
        if single_match:
            return single_match.group(1)
        return None

    def _extract_imports(self, source: str) -> List[str]:
        """Extract import paths from ES module import statements."""
        imports = []
        # Match: import X from 'module' and import 'module'
        for match in self._IMPORT_PATTERN.finditer(source):
            # Group 1: import X from '...', Group 2: import '...', Group 3: import()
            path = match.group(1) or match.group(2) or match.group(3)
            if path:
                imports.append(path)
        # Match: require('...') and require("...")
        for match in re.finditer(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", source):
            imports.append(match.group(1))
        return sorted(set(imports))

    def _classify_external_imports(self, imports: List[str]) -> List[str]:
        """Classify imports as external (npm packages) vs internal."""
        external = []
        for imp in imports:
            # npm package: starts with a letter and doesn't start with . or / or @/
            # e.g. 'react', 'lodash', '@angular/core', '@tauri-apps/api'
            # '@/' style path aliases are internal (Vite/webpack alias)
            if imp.startswith("@/") or imp.startswith("~/"):
                continue
            if not imp.startswith(".") and not imp.startswith("/"):
                # Get the package name (handle scoped packages @scope/pkg)
                parts = imp.split("/")
                if imp.startswith("@"):
                    pkg = "/".join(parts[:2]) if len(parts) >= 2 else imp
                else:
                    pkg = parts[0]
                external.append(pkg)
        return sorted(set(external))

    def _extract_exports(self, source: str) -> List[str]:
        """Extract named exports."""
        exports = []
        for match in self._EXPORT_PATTERN.finditer(source):
            # Named export
            if match.group(1):
                exports.append(match.group(1))
            # Export destructuring: export { foo, bar }
            if match.group(2):
                names = [n.strip() for n in match.group(2).split(",")]
                for name in names:
                    # Handle 'as' renames: foo as bar
                    clean = name.split(" as ")[0].split(" as ")[0].strip()
                    if clean and not clean.startswith("type"):
                        exports.append(clean)
        return sorted(set(exports))

    def _extract_functions(
        self, source: str, rel_path: str
    ) -> List[FunctionInfo]:
        """Extract function declarations and arrow functions."""
        functions = []
        seen = set()

        # Regular function declarations
        for match in self._FUNCTION_DECL_PATTERN.finditer(source):
            name = match.group(1)
            if name and name not in seen:
                seen.add(name)
                line_num = source[: match.start()].count("\n") + 1
                functions.append(
                    FunctionInfo(
                        name=name,
                        docstring=self._extract_jsdoc(source, match.start()),
                        anchor=SourceAnchor(file=rel_path, line=line_num),
                    )
                )

        # Arrow function assignments (const X = (...) => ...)
        # We iterate line by line for reliability
        lines = source.split("\n")
        for i, line in enumerate(lines):
            # Match: const|let|var Name = (params) => or : Type => 
            arrow_match = re.match(
                r"""^\s*(?:export\s+)?(?:default\s+)?(?:const|let|var)\s+(\w+)\s*=\s*""",
                line,
            )
            if not arrow_match:
                continue
            name = arrow_match.group(1)
            if name in seen:
                continue

            # Check if the rest of the line or next lines contain =>
            rest = line[arrow_match.end():]
            combined = rest
            if "=>" not in combined:
                # Look ahead a few lines
                for j in range(1, 5):
                    if i + j < len(lines):
                        combined += "\n" + lines[i + j]
                        if "=>" in combined:
                            break

            if "=>" in combined or re.match(r'^use[A-Z]', name):
                seen.add(name)
                functions.append(
                    FunctionInfo(
                        name=name,
                        docstring=self._extract_jsdoc(source, arrow_match.start()),
                        anchor=SourceAnchor(file=rel_path, line=i + 1),
                    )
                )

        return functions

    def _extract_classes(
        self, source: str, rel_path: str
    ) -> List[ClassInfo]:
        """Extract class declarations."""
        classes = []
        for match in self._CLASS_PATTERN.finditer(source):
            name = match.group(1)
            bases_str = match.group(2)
            implements_str = match.group(3)
            bases = []
            if bases_str:
                bases.append(bases_str)
            if implements_str:
                bases.extend(
                    [b.strip() for b in implements_str.split(",") if b.strip()]
                )

            line_num = source[: match.start()].count("\n") + 1

            # Try to extract methods (simple heuristic)
            methods = self._extract_class_methods(
                source, match.start(), name, rel_path
            )

            classes.append(
                ClassInfo(
                    name=name,
                    docstring=self._extract_jsdoc(source, match.start()),
                    bases=bases,
                    methods=methods,
                    anchor=SourceAnchor(file=rel_path, line=line_num),
                )
            )

        return classes

    def _extract_class_methods(
        self, source: str, class_start: int, class_name: str, rel_path: str
    ) -> List[FunctionInfo]:
        """Extract method signatures from a class body."""
        # Find the class body boundaries
        body_start = source.find("{", class_start)
        if body_start == -1:
            return []

        # Track brace depth to find closing
        depth = 0
        body_end = len(source)
        for i in range(body_start, len(source)):
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    body_end = i + 1
                    break

        body = source[body_start:body_end]

        methods = []
        # Match method signatures in the class body
        method_pattern = re.compile(
            r"""
            (?:public|private|protected|static|readonly|async)\s+(\w+)\s*\(
            |
            ^\s*(\w+)\s*\(                                        # simple method()
            """,
            re.MULTILINE | re.VERBOSE,
        )

        for match in method_pattern.finditer(body):
            name = match.group(1) or match.group(2)
            if not name:
                continue
            # Skip constructor
            if name == "constructor":
                continue
            # Skip if it's not actually a method (e.g., property assignment)
            actual_line_num = source[: class_start + match.start()].count("\n") + 1
            methods.append(
                FunctionInfo(
                    name=name,
                    anchor=SourceAnchor(
                        file=rel_path, line=actual_line_num
                    ),
                )
            )

        return methods

    def _extract_interfaces(
        self, source: str, rel_path: str
    ) -> List[InterfaceInfo]:
        """Extract TypeScript interface and type declarations."""
        interfaces = []
        seen = set()

        for match in self._INTERFACE_PATTERN.finditer(source):
            name = match.group(1)
            if name in seen:
                continue
            seen.add(name)

            line_num = source[: match.start()].count("\n") + 1

            # Extract members from interface/type body
            body_start = source.find("{", match.start())
            members = []
            if body_start != -1:
                body_end = self._find_balanced_brace(source, body_start)
                if body_end:
                    body = source[body_start + 1 : body_end]
                    # Parse key: type; lines
                    for member_line in body.split(";"):
                        member_line = member_line.strip()
                        if not member_line or member_line.startswith("//"):
                            continue
                        member_match = re.match(
                            r"""^\s*(\w+)\s*(?:\?\s*)?:\s*([^;=]+)""",
                            member_line,
                        )
                        if member_match:
                            members.append({
                                "name": member_match.group(1),
                                "type": member_match.group(2).strip(),
                            })

            interfaces.append(
                InterfaceInfo(
                    name=name,
                    members=members,
                    docstring=self._extract_jsdoc(source, match.start()),
                    anchor=SourceAnchor(file=rel_path, line=line_num),
                )
            )

        return interfaces

    def _extract_components(
        self, source: str, rel_path: str, lines: List[str]
    ) -> List[ReactComponentInfo]:
        """Detect React components (PascalCase functions returning JSX)."""
        components = []

        # Get all function names first
        func_names = set()
        for match in self._FUNCTION_DECL_PATTERN.finditer(source):
            func_names.add(match.group(1))
        for match in re.finditer(
            r"""^\s*(?:export\s+)?(?:default\s+)?(?:const|let|var)\s+(\w+)\s*=""",
            source,
            re.MULTILINE,
        ):
            func_names.add(match.group(1))

        for func_name in func_names:
            # React components are PascalCase (first letter uppercase)
            if not func_name or not func_name[0].isupper():
                continue

            # Check if the function body contains JSX
            # Find function position
            pos = self._find_function_pos(source, func_name)
            if pos is None:
                continue

            # Look ahead for JSX in the function body
            # Scan a larger portion (up to 10000 chars) to handle functions with early returns
            fn_body = source[pos : min(pos + 10000, len(source))]
            # Also try to find the end of function by brace matching
            brace_start = source.find("{", pos)
            if brace_start != -1:
                # Find balanced closing brace to get full function body
                depth = 0
                for i in range(brace_start, len(source)):
                    if source[i] == "{":
                        depth += 1
                    elif source[i] == "}":
                        depth -= 1
                        if depth == 0:
                            fn_body = source[pos : i + 1]
                            break
            if not self._JSX_RETURN_PATTERN.search(fn_body):
                # Try broader scan: look for <Foo ...> or </> patterns
                if not re.search(r"<[A-Z]\w+[\s>]", fn_body) and "</" not in fn_body:
                    continue

            line_num = source[:pos].count("\n") + 1

            # Extract hooks used in this component
            hooks = []
            for hook in self._REACT_HOOKS:
                if hook in fn_body:
                    hooks.append(hook)

            # Try to extract props type from the function signature
            props_type = None
            sig_match = re.search(
                rf"{func_name}\s*\(\s*(\{{\s*[\s\S]+\}}|\w+)\s*(?:\:\s*(\w+))?\s*\)",
                source[pos : pos + 500],
            )
            if sig_match:
                if sig_match.group(2):
                    props_type = sig_match.group(2)
                else:
                    props_type = sig_match.group(1)[:80]  # inline type literal

            components.append(
                ReactComponentInfo(
                    name=func_name,
                    props_type=props_type,
                    hooks=hooks,
                    anchor=SourceAnchor(file=rel_path, line=line_num),
                )
            )

        return components

    # ---- Helper Methods ----

    def _extract_jsdoc(self, source: str, pos: int) -> Optional[str]:
        """Extract JSDoc comment immediately before a symbol."""
        before = source[max(0, pos - 500) : pos].rstrip()
        # Match /** ... */ right before the symbol
        jsdoc_match = re.search(r'/\*\*([\s\S]*?)\*/\s*$', before)
        if jsdoc_match:
            text = jsdoc_match.group(1)
            lines = []
            for line in text.split("\n"):
                cleaned = re.sub(r'^\s*\*\s?', '', line).strip()
                if cleaned:
                    lines.append(cleaned)
            return "\n".join(lines[:5]) if lines else None
        # Single-line comment // ... right before
        single_match = re.search(r'//\s*(.+)\s*$', before, re.MULTILINE)
        if single_match:
            return single_match.group(1)
        return None

    def _find_function_pos(self, source: str, name: str) -> Optional[int]:
        """Find the approximate position of a function in source."""
        patterns = [
            rf"function\s+{re.escape(name)}\s*\(",
            rf"(?:const|let|var)\s+{re.escape(name)}\s*=",
        ]
        for pat in patterns:
            match = re.search(pat, source)
            if match:
                return match.start()
        return None

    def _find_balanced_brace(self, source: str, start: int) -> Optional[int]:
        """Find the closing brace matching the opening brace at position start."""
        if source[start] != "{":
            return None
        depth = 0
        for i in range(start, len(source)):
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        return None
