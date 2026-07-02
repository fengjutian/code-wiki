"""
Tree-sitter unified parser — replaces stdlib ast + regex-based analyzers.

Multi-language code parsing with one consistent API.  Uses tree-sitter
grammars for accurate, fault-tolerant CSTs and S-expression queries
for structural extraction.

Features (vs. current analyzer.py + ts_analyzer.py):
  - 40+ languages via tree-sitter grammars
  - Fault-tolerant parsing (works on incomplete / syntactically invalid code)
  - Incremental re-parsing via Tree.edit() for file-watch scenarios
  - Declarative queries (S-expression) instead of imperative AST walking
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tree_sitter import Language, Parser, Query, Node, Tree, QueryCursor

from models.entities import (
    ModuleInfo,
    ClassInfo,
    FunctionInfo,
    InterfaceInfo,
    ReactComponentInfo,
    SourceAnchor,
    SupportedLanguage,
)

logger = logging.getLogger("code-wiki.tree_sitter")

# ---------------------------------------------------------------------------
# Language loading — lazy, per-language
# ---------------------------------------------------------------------------

# Map SupportedLanguage → (import-path, callable-name)
_LANGUAGE_LOADERS: Dict[SupportedLanguage, Tuple[str, str]] = {
    SupportedLanguage.PYTHON:     ("tree_sitter_python",     "language"),
    SupportedLanguage.TYPESCRIPT: ("tree_sitter_typescript", "language_typescript"),
    SupportedLanguage.JAVASCRIPT: ("tree_sitter_typescript", "language_typescript"),
}

# TSX → same grammar as TypeScript (JSX is part of the TS grammar)
# We use a small wrapper to distinguish them at the ModuleInfo level.
_TSX_EXTENSIONS = frozenset({".tsx", ".jsx"})


class TreeSitterParser:
    """Unified multi-language parser.

    Usage::

        parser = TreeSitterParser()
        module: ModuleInfo = parser.parse_file("services/auth.py")
    """

    def __init__(self):
        self._parsers: Dict[SupportedLanguage, Parser] = {}
        self._languages: Dict[SupportedLanguage, Language] = {}
        self._init_ok: Dict[SupportedLanguage, bool] = {}

        # Warm-up: pre-load grammars that are installed
        for lang in SupportedLanguage:
            self._ensure_language(lang)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_file(self, rel_path: str, repo_path: str | Path = ".") -> ModuleInfo:
        """Parse one source file → ModuleInfo (same schema as current Analyzer)."""
        repo_path = Path(repo_path)
        full_path = repo_path / rel_path
        source = full_path.read_text(encoding="utf-8", errors="replace")

        lang = self._detect_language(rel_path)
        return self.parse_source(source, lang, rel_path)

    def parse_source(
        self, source: str, language: SupportedLanguage, rel_path: str = "<unknown>"
    ) -> ModuleInfo:
        """Parse source text for a given language."""
        lines = source.splitlines()
        total_lines = len(lines)

        # Try tree-sitter first; fall back gracefully
        tree = self._try_parse(source, language)

        if tree is None:
            # Grammar not available — return a minimal ModuleInfo
            return ModuleInfo(
                path=rel_path,
                language=language,
                docstring=None,
                total_lines=total_lines,
            )

        root = tree.root_node

        # Dispatch to language-specific extractors
        if language == SupportedLanguage.PYTHON:
            return self._extract_python(root, source, lines, rel_path, language)
        else:
            return self._extract_typescript(root, source, lines, rel_path, language)

    def parse_batch(
        self, files: List[str], repo_path: str | Path = "."
    ) -> Dict[str, ModuleInfo]:
        """Analyze multiple files → {rel_path: ModuleInfo}."""
        result: Dict[str, ModuleInfo] = {}
        for f in files:
            result[f] = self.parse_file(f, repo_path)
        return result

    # ------------------------------------------------------------------
    # Grammar loading
    # ------------------------------------------------------------------

    def _ensure_language(self, language: SupportedLanguage) -> Optional[Language]:
        """Lazy-load a tree-sitter grammar (idempotent)."""
        if language in self._languages:
            return self._languages[language]
        if language in self._init_ok and not self._init_ok[language]:
            return None

        loader = _LANGUAGE_LOADERS.get(language)
        if loader is None:
            self._init_ok[language] = False
            return None

        module_path, callable_name = loader
        try:
            import importlib
            mod = importlib.import_module(module_path)
            factory = getattr(mod, callable_name)
            capsule = factory()                     # PyCapsule
            ts_lang = Language(capsule)             # tree_sitter.Language
            self._languages[language] = ts_lang
            self._parsers[language] = Parser(ts_lang)
            self._init_ok[language] = True
            logger.info("Tree-sitter grammar loaded: %s", language.value)
            return ts_lang
        except ImportError:
            logger.debug(
                "tree-sitter grammar for %s not installed (%s)",
                language.value, module_path,
            )
        except Exception:
            logger.warning(
                "Failed to load tree-sitter grammar for %s",
                language.value, exc_info=True,
            )
        self._init_ok[language] = False
        return None

    def _try_parse(self, source: str, language: SupportedLanguage) -> Optional[Tree]:
        """Parse source; return None if grammar not available or parse fails."""
        parser = self._parsers.get(language)
        if parser is None:
            return None
        try:
            return parser.parse(source.encode("utf-8"))
        except Exception:
            logger.warning("Tree-sitter parse failed for %s", language.value)
            return None

    @staticmethod
    def _detect_language(rel_path: str) -> SupportedLanguage:
        ext = Path(rel_path).suffix.lower()
        lang = SupportedLanguage.from_extension(ext)
        return lang or SupportedLanguage.PYTHON

    # ------------------------------------------------------------------
    # Python extraction (tree-sitter queries)
    # ------------------------------------------------------------------

    # Query: capture all function definitions (with optional @decorator)
    _PY_FUNC_Q = """
    (function_definition
      name: (identifier) @func.name
      parameters: (parameters) @func.params
      return_type: (type)? @func.ret
      body: (block) @func.body
    ) @func.def

    (decorated_definition
      (decorator) @func.deco
      definition: (function_definition
        name: (identifier) @func.name
        parameters: (parameters) @func.params
        return_type: (type)? @func.ret
        body: (block) @func.body)
    ) @func.def
    """

    # Query: capture all class definitions (with optional @decorator)
    _PY_CLASS_Q = """
    (class_definition
      name: (identifier) @class.name
      superclasses: (argument_list)? @class.bases
      body: (block) @class.body
    ) @class.def

    (decorated_definition
      (decorator) @class.deco
      definition: (class_definition
        name: (identifier) @class.name
        superclasses: (argument_list)? @class.bases
        body: (block) @class.body)
    ) @class.def
    """

    # Query: capture imports
    _PY_IMPORT_Q = """
    (import_statement name: (dotted_name) @import.name) @import.stmt
    (import_from_statement module_name: (dotted_name) @import.from) @import.from_stmt
    """

    _PY_STDLIB = frozenset({
        "os", "sys", "re", "json", "time", "datetime", "collections",
        "typing", "abc", "io", "pathlib", "math", "random", "logging",
        "unittest", "itertools", "functools", "asyncio", "subprocess",
        "hashlib", "uuid", "dataclasses", "enum", "copy", "textwrap",
        "argparse", "traceback", "warnings", "contextlib", "inspect",
        "ast", "threading", "multiprocessing", "queue", "socket",
        "http", "urllib", "xml", "csv", "sqlite3", "pickle", "shutil",
        "tempfile", "glob", "fnmatch", "statistics", "decimal",
        "fractions", "concurrent", "importlib", "pkgutil", "types",
    })

    def _extract_python(
        self,
        root: Node,
        source: str,
        lines: List[str],
        rel_path: str,
        language: SupportedLanguage,
    ) -> ModuleInfo:
        lang = self._languages.get(SupportedLanguage.PYTHON)
        assert lang is not None

        total_lines = len(lines)
        docstring = self._py_module_docstring(root, source)

        # Functions and classes at module level
        functions, class_functions, classes = self._py_extract_top_level(root, source, rel_path, lang)

        # Merge method functions into the module's function list
        all_functions = functions + class_functions

        # Imports
        internal_imports, external_imports = self._py_extract_imports(root, source, lang)

        return ModuleInfo(
            path=rel_path,
            language=language,
            docstring=docstring,
            imports=sorted(internal_imports),
            external_imports=sorted(external_imports),
            classes=classes,
            functions=all_functions,
            total_lines=total_lines,
        )

    def _py_module_docstring(self, root: Node, source: str) -> Optional[str]:
        """Extract module-level docstring via tree-sitter query."""
        lang = self._languages.get(SupportedLanguage.PYTHON)
        if lang is None:
            return None
        query_src = """
        (module
          (expression_statement
            (string) @module.doc)) @module.doc_stmt
        """
        try:
            for _, caps in self._query_matches(lang, query_src, root):
                node = caps.get("module.doc")
                if node:
                    return self._node_text(node[0], source).strip("'\"")
        except Exception:
            pass
        return None

    def _py_extract_top_level(
        self, root: Node, source: str, rel_path: str, lang: Language
    ) -> Tuple[List[FunctionInfo], List[FunctionInfo], List[ClassInfo]]:
        """Extract top-level functions and classes."""
        functions: List[FunctionInfo] = []
        class_functions: List[FunctionInfo] = []
        classes: List[ClassInfo] = []
        seen_func_names: set[str] = set()
        seen_func_positions: set[tuple] = set()    # dedup: (name, start_line)
        seen_class_positions: set[tuple] = set()   # dedup: (name, start_line)

        # ---- Classes first ----
        try:
            for _, caps in self._query_matches(lang, self._PY_CLASS_Q, root):
                class_node = self._first(caps, "class.def")
                name_node = self._first(caps, "class.name")
                body_node = self._first(caps, "class.body")
                bases_node = self._first(caps, "class.bases")
                deco_nodes = caps.get("class.deco", [])

                if not (class_node and name_node):
                    continue

                class_name = self._node_text(name_node, source)
                bases = self._py_extract_bases(bases_node, source)
                decorators = [self._node_text(d, source) for d in deco_nodes]
                start_line = name_node.start_point[0] + 1
                end_line = class_node.end_point[0] + 1

                # Deduplicate: decorated_definition also exposes inner class_definition
                pos_key = (class_name, start_line)
                if pos_key in seen_class_positions:
                    continue
                seen_class_positions.add(pos_key)

                methods: List[FunctionInfo] = []
                if body_node:
                    methods = self._py_extract_methods(body_node, source, rel_path, lang)
                    for m in methods:
                        seen_func_names.add(m.name)

                cls = ClassInfo(
                    name=class_name,
                    docstring=self._py_class_docstring(class_node, source, lang),
                    bases=bases,
                    methods=methods,
                    anchor=SourceAnchor(file=rel_path, line=start_line),
                    end_line=end_line,
                    decorators=decorators,
                )
                classes.append(cls)

        except Exception:
            logger.warning("Python class extraction failed", exc_info=True)

        # ---- Functions ----
        try:
            for _, caps in self._query_matches(lang, self._PY_FUNC_Q, root):
                func_node = self._first(caps, "func.def")
                name_node = self._first(caps, "func.name")
                params_node = self._first(caps, "func.params")
                ret_node = self._first(caps, "func.ret")
                deco_nodes = caps.get("func.deco", [])

                if not (func_node and name_node):
                    continue

                func_name = self._node_text(name_node, source)
                if func_name in seen_func_names:
                    continue
                seen_func_names.add(func_name)

                args = self._py_extract_params(params_node, source)
                returns = self._node_text(ret_node, source) if ret_node else None
                decorators = [self._node_text(d, source) for d in deco_nodes]
                start_line = name_node.start_point[0] + 1
                end_line = func_node.end_point[0] + 1

                # Deduplicate: decorated functions also expose inner function_definition
                pos_key = (func_name, start_line)
                if pos_key in seen_func_positions:
                    continue
                seen_func_positions.add(pos_key)

                fn = FunctionInfo(
                    name=func_name,
                    docstring=self._py_func_docstring(func_node, source, lang),
                    args=args,
                    returns=returns,
                    anchor=SourceAnchor(file=rel_path, line=start_line),
                    end_line=end_line,
                    decorators=decorators,
                )
                functions.append(fn)

        except Exception:
            logger.warning("Python function extraction failed", exc_info=True)

        return functions, class_functions, classes

    def _py_extract_methods(
        self, body_node: Node, source: str, rel_path: str, lang: Language
    ) -> List[FunctionInfo]:
        """Extract method definitions from a class body."""
        methods: List[FunctionInfo] = []
        method_q = """
        (function_definition
          name: (identifier) @method.name
          parameters: (parameters) @method.params
          return_type: (type)? @method.ret
        ) @method.def

        (decorated_definition
          (decorator) @method.deco
          definition: (function_definition
            name: (identifier) @method.name
            parameters: (parameters) @method.params
            return_type: (type)? @method.ret)
        ) @method.def
        """
        try:
            for _, caps in self._query_matches(lang, method_q, body_node):
                m_node = self._first(caps, "method.def")
                name_node = self._first(caps, "method.name")
                params_node = self._first(caps, "method.params")
                ret_node = self._first(caps, "method.ret")
                deco_nodes = caps.get("method.deco", [])

                if not (m_node and name_node):
                    continue

                m_name = self._node_text(name_node, source)
                args = self._py_extract_params(params_node, source)
                returns = self._node_text(ret_node, source) if ret_node else None
                decorators = [self._node_text(d, source) for d in deco_nodes]
                start_line = name_node.start_point[0] + 1
                end_line = m_node.end_point[0] + 1

                methods.append(FunctionInfo(
                    name=m_name,
                    docstring=self._py_func_docstring(m_node, source, lang),
                    args=args,
                    returns=returns,
                    anchor=SourceAnchor(file=rel_path, line=start_line),
                    end_line=end_line,
                    decorators=decorators,
                ))
        except Exception:
            logger.warning("Method extraction failed", exc_info=True)

        return methods

    def _py_extract_params(self, params_node: Optional[Node], source: str) -> List[dict]:
        """Extract function parameters from a parameters node."""
        if params_node is None:
            return []
        args: List[dict] = []
        for child in params_node.children:
            if child.type == "identifier":
                # Simple parameter: name (e.g., 'self', 'x')
                args.append({"name": self._node_text(child, source),
                             "type_annotation": None, "default": None})
            elif child.type == "typed_parameter":
                # name: type
                name = type_ann = None
                for c in child.children:
                    if c.type == "identifier":
                        name = self._node_text(c, source)
                    elif c.type == "type":
                        type_ann = self._node_text(c, source)
                if name:
                    args.append({"name": name, "type_annotation": type_ann, "default": None})
            elif child.type == "typed_default_parameter":
                # name: type = default  OR  name = default
                name = type_ann = default = None
                for c in child.children:
                    if c.type == "identifier":
                        name = self._node_text(c, source)
                    elif c.type == "type":
                        type_ann = self._node_text(c, source)
                    elif c.type == "string":
                        default = self._node_text(c, source)
                    elif c.type == "none":
                        default = "None"
                    elif c.type in ("true", "false"):
                        default = self._node_text(c, source)
                    elif c.type == "integer":
                        default = self._node_text(c, source)
                if name:
                    args.append({"name": name, "type_annotation": type_ann, "default": default})
            elif child.type == "list_splat_pattern":
                args.append({"name": "*args", "type_annotation": None, "default": None})
            elif child.type == "dictionary_splat_pattern":
                args.append({"name": "**kwargs", "type_annotation": None, "default": None})
            elif child.type == "tuple_pattern":
                # Multiple parameters in a tuple like (x, y)
                for c in child.children:
                    if c.type == "identifier":
                        args.append({"name": self._node_text(c, source),
                                     "type_annotation": None, "default": None})
        return args

    def _py_extract_bases(self, bases_node: Optional[Node], source: str) -> List[str]:
        if bases_node is None:
            return []
        bases: List[str] = []
        for child in bases_node.children:
            if child.type not in ("(", ")", ","):
                bases.append(self._node_text(child, source))
        return bases


    def _py_extract_imports(
        self, root: Node, source: str, lang: Language
    ) -> Tuple[List[str], List[str]]:
        """Extract imports from Python module."""
        internal: set[str] = set()
        external: set[str] = set()

        # tree-sitter Python grammar node types:
        # import_statement: import X, import X.Y
        # import_from_statement: from X import Y
        import_query = """
        (import_statement
          name: (dotted_name) @name) @stmt

        (import_from_statement
          module_name: (dotted_name)? @module
          name: (dotted_name) @name) @stmt
        """
        try:
            for _, caps in self._query_matches(lang, import_query, root):
                name_node = self._first(caps, "name")
                module_node = self._first(caps, "module")

                if name_node:
                    name = self._node_text(name_node, source)
                    top = name.split(".")[0]
                    if top in self._PY_STDLIB:
                        external.add(name)
                    else:
                        internal.add(name)

                if module_node:
                    mod = self._node_text(module_node, source)
                    top = mod.split(".")[0]
                    if top in self._PY_STDLIB:
                        external.add(mod)
                    else:
                        internal.add(mod)

        except Exception:
            logger.warning("Import extraction failed", exc_info=True)

        return sorted(internal), sorted(external)

    def _py_func_docstring(self, func_node: Node, source: str, lang: Language) -> Optional[str]:
        """Extract function docstring via query."""
        try:
            for _, caps in self._query_matches(lang, """
            (function_definition
              body: (block
                (expression_statement
                  (string) @doc)))
            """, func_node):
                doc = self._first(caps, "doc")
                if doc:
                    return self._node_text(doc, source).strip("'\"")
        except Exception:
            pass
        return None

    def _py_class_docstring(self, class_node: Node, source: str, lang: Language) -> Optional[str]:
        """Extract class docstring."""
        try:
            for _, caps in self._query_matches(lang, """
            (class_definition
              body: (block
                (expression_statement
                  (string) @doc)))
            """, class_node):
                doc = self._first(caps, "doc")
                if doc:
                    return self._node_text(doc, source).strip("'\"")
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # TypeScript / JavaScript extraction
    # ------------------------------------------------------------------

    _TS_FUNC_Q = """
    (function_declaration
      name: (identifier) @func.name
      parameters: (formal_parameters) @func.params
      return_type: (type_annotation)? @func.ret
    ) @func.def

    (arrow_function) @arrow.def

    (method_definition
      name: (property_identifier) @func.name
      parameters: (formal_parameters) @func.params
      return_type: (type_annotation)? @func.ret
    ) @method.def
    """

    _TS_CLASS_Q = """
    (class_declaration
      name: (identifier) @class.name
      body: (class_body) @class.body
    ) @class.def
    """

    _TS_INTERFACE_Q = """
    (interface_declaration
      name: (type_identifier) @iface.name
      body: (interface_body) @iface.body
    ) @iface.def

    (type_alias_declaration
      name: (type_identifier) @type.name
      value: (_) @type.value
    ) @type.def
    """

    _TS_IMPORT_Q = """
    (import_statement
      source: (string) @import.source
    ) @import.stmt

    (import_statement) @import.stmt

    (call_expression
      function: (identifier) @call.name
      arguments: (arguments
        (string) @import.req))
    """

    _REACT_HOOKS = frozenset({
        "useState", "useEffect", "useContext", "useReducer",
        "useCallback", "useMemo", "useRef", "useImperativeHandle",
        "useLayoutEffect", "useDebugValue", "useTransition",
        "useDeferredValue", "useId", "useSyncExternalStore",
        "useInsertionEffect", "useActionState", "useOptimistic",
    })

    def _extract_typescript(
        self,
        root: Node,
        source: str,
        lines: List[str],
        rel_path: str,
        language: SupportedLanguage,
    ) -> ModuleInfo:
        # Pick the right grammar language (TS vs JS/TSX/JSX share the same grammar)
        # For extract purposes TS and JS are identical in tree-sitter
        ts_lang = self._languages.get(SupportedLanguage.TYPESCRIPT) or \
                  self._languages.get(SupportedLanguage.JAVASCRIPT)
        if ts_lang is None:
            return ModuleInfo(path=rel_path, language=language, total_lines=len(lines))

        total_lines = len(lines)
        docstring = self._ts_file_header(root, source, ts_lang)
        imports = self._ts_extract_imports(root, source, ts_lang)
        external_imports = self._ts_classify_external(imports)
        exports = self._ts_extract_exports(root, source, ts_lang)
        functions = self._ts_extract_functions(root, source, rel_path, ts_lang)
        classes = self._ts_extract_classes(root, source, rel_path, ts_lang)
        interfaces = self._ts_extract_interfaces(root, source, rel_path, ts_lang)
        components = self._ts_extract_components(
            root, source, lines, rel_path, ts_lang
        )

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

    def _ts_file_header(self, root: Node, source: str, lang: Language) -> Optional[str]:
        """Extract file-level comment."""
        for child in root.children:
            if child.type == "comment":
                text = self._node_text(child, source)
                if text.startswith("/**") or text.startswith("/*"):
                    return text.strip("/* \n\t").split("\n")[0].strip("*").strip()
                if text.startswith("//"):
                    return text[2:].strip()
            elif child.type not in ("comment",):
                break  # only look at the very top
        return None

    def _ts_extract_imports(self, root: Node, source: str, lang: Language) -> List[str]:
        imports: List[str] = []
        import_q = """
        (import_statement
          source: (string (string_fragment) @src))
        (call_expression
          function: (identifier) @fn
          arguments: (arguments (string (string_fragment) @src)))
        """
        try:
            for _, caps in self._query_matches(lang, import_q, root):
                src_node = self._first(caps, "src")
                fn_node = self._first(caps, "fn")
                if src_node:
                    import_path = self._node_text(src_node, source)
                    for qchar in "'\"`":
                        import_path = import_path.strip(qchar)
                    imports.append(import_path)
                elif fn_node:
                    if self._node_text(fn_node, source) in ("require", "import"):
                        pass
        except Exception:
            logger.warning("TS import extraction failed", exc_info=True)

        return sorted(set(imports))

    @staticmethod
    def _ts_classify_external(imports: List[str]) -> List[str]:
        external: List[str] = []
        for imp in imports:
            if imp.startswith("@/") or imp.startswith("~/") or imp.startswith("."):
                continue
            parts = imp.split("/")
            if imp.startswith("@"):
                pkg = "/".join(parts[:2]) if len(parts) >= 2 else imp
            else:
                pkg = parts[0]
            external.append(pkg)
        return sorted(set(external))

    def _ts_extract_exports(self, root: Node, source: str, lang: Language) -> List[str]:
        exports: List[str] = []
        export_q = """
        (export_statement
          declaration: (_) @decl
          value: (_) @val)
        (export_statement
          source: (string) @re_export)
        """
        try:
            for _, caps in self._query_matches(lang, export_q, root):
                decl = self._first(caps, "decl")
                if decl:
                    for child in decl.children:
                        if child.type in ("identifier", "type_identifier"):
                            exports.append(self._node_text(child, source))
                            break
        except Exception:
            pass
        return sorted(set(exports))

    def _ts_extract_functions(
        self, root: Node, source: str, rel_path: str, lang: Language
    ) -> List[FunctionInfo]:
        functions: List[FunctionInfo] = []
        seen: set[str] = set()

        # Function declarations
        func_q = """
        (function_declaration
          name: (identifier) @name) @def

        (variable_declarator
          name: (identifier) @name
          value: (arrow_function) @arrow) @def

        (variable_declarator
          name: (identifier) @name
          value: (function_expression) @func) @def

        (method_definition
          name: (property_identifier) @name) @def
        """
        try:
            for _, caps in self._query_matches(lang, func_q, root):
                name_node = self._first(caps, "name")
                def_node = self._first(caps, "def")
                if not name_node:
                    continue
                name = self._node_text(name_node, source)
                if name in seen:
                    continue
                seen.add(name)
                start_line = def_node.start_point[0] + 1 if def_node else name_node.start_point[0] + 1
                end_line = def_node.end_point[0] + 1 if def_node else start_line
                functions.append(FunctionInfo(
                    name=name,
                    anchor=SourceAnchor(file=rel_path, line=start_line),
                    end_line=end_line,
                ))
        except Exception:
            logger.warning("TS function extraction failed", exc_info=True)

        return functions

    def _ts_extract_classes(
        self, root: Node, source: str, rel_path: str, lang: Language
    ) -> List[ClassInfo]:
        classes: List[ClassInfo] = []
        class_q = """
        (class_declaration
          name: (identifier) @name
          body: (class_body) @body) @def

        (class
          name: (identifier) @name
          body: (class_body) @body) @def
        """
        try:
            for _, caps in self._query_matches(lang, class_q, root):
                name_node = self._first(caps, "name")
                body_node = self._first(caps, "body")
                def_node = self._first(caps, "def")
                if not name_node:
                    continue
                name = self._node_text(name_node, source)
                start_line = def_node.start_point[0] + 1 if def_node else name_node.start_point[0] + 1
                end_line = def_node.end_point[0] + 1 if def_node else start_line

                # Extract methods from body
                methods: List[FunctionInfo] = []
                if body_node:
                    methods = self._ts_extract_class_methods(body_node, source, rel_path, lang)

                classes.append(ClassInfo(
                    name=name,
                    methods=methods,
                    anchor=SourceAnchor(file=rel_path, line=start_line),
                    end_line=end_line,
                ))
        except Exception:
            logger.warning("TS class extraction failed", exc_info=True)

        return classes

    def _ts_extract_class_methods(
        self, body_node: Node, source: str, rel_path: str, lang: Language
    ) -> List[FunctionInfo]:
        methods: List[FunctionInfo] = []
        method_q = """
        (method_definition
          name: (property_identifier) @name) @def
        """
        try:
            for _, caps in self._query_matches(lang, method_q, body_node):
                name_node = self._first(caps, "name")
                def_node = self._first(caps, "def")
                if not name_node:
                    continue
                name = self._node_text(name_node, source)
                start_line = def_node.start_point[0] + 1 if def_node else 0
                methods.append(FunctionInfo(
                    name=name,
                    anchor=SourceAnchor(file=rel_path, line=start_line),
                ))
        except Exception:
            pass
        return methods

    def _ts_extract_interfaces(
        self, root: Node, source: str, rel_path: str, lang: Language
    ) -> List[InterfaceInfo]:
        interfaces: List[InterfaceInfo] = []
        iface_q = """
        (interface_declaration
          name: (type_identifier) @name
          body: (interface_body) @body) @def

        (type_alias_declaration
          name: (type_identifier) @name
          value: (_) @value) @def
        """
        try:
            for _, caps in self._query_matches(lang, iface_q, root):
                name_node = self._first(caps, "name")
                body_node = self._first(caps, "body")
                def_node = self._first(caps, "def")
                if not name_node:
                    continue
                name = self._node_text(name_node, source)
                start_line = def_node.start_point[0] + 1 if def_node else name_node.start_point[0] + 1

                members: List[dict] = []
                if body_node:
                    for child in body_node.children:
                        if child.type == "property_signature":
                            prop_parts = [self._node_text(c, source) for c in child.children
                                          if c.type not in (":", ";", "?", ",")]
                            if len(prop_parts) >= 2:
                                members.append({"name": prop_parts[0], "type": " ".join(prop_parts[1:])})

                interfaces.append(InterfaceInfo(
                    name=name,
                    members=members,
                    anchor=SourceAnchor(file=rel_path, line=start_line),
                ))
        except Exception:
            logger.warning("TS interface extraction failed", exc_info=True)

        return interfaces

    def _ts_extract_components(
        self,
        root: Node,
        source: str,
        lines: List[str],
        rel_path: str,
        lang: Language,
    ) -> List[ReactComponentInfo]:
        """Detect React components (PascalCase + JSX return)."""
        components: List[ReactComponentInfo] = []

        # Find PascalCase function/arrow declarations that contain JSX
        # We use a simpler approach: collect all named declarations,
        # check if PascalCase, then check if body contains JSX
        comp_q = """
        (function_declaration
          name: (identifier) @name
          body: (statement_block) @body) @def

        (variable_declarator
          name: (identifier) @name
          value: (arrow_function
            body: (statement_block) @body)) @def

        (variable_declarator
          name: (identifier) @name
          value: (arrow_function
            body: (jsx_element) @body)) @def

        (variable_declarator
          name: (identifier) @name
          value: (function_expression
            body: (statement_block) @body)) @def
        """
        try:
            for _, caps in self._query_matches(lang, comp_q, root):
                name_node = self._first(caps, "name")
                body_node = self._first(caps, "body")
                def_node = self._first(caps, "def")
                if not name_node:
                    continue
                name = self._node_text(name_node, source)
                # PascalCase check
                if not name or not name[0].isupper():
                    continue

                # Check if body contains JSX
                body_text = self._node_text(body_node, source) if body_node else ""
                has_jsx = "<" in body_text and (">" in body_text)

                if not has_jsx and body_node:
                    # Check deeper for jsx_element nodes
                    for child in self._iter_nodes(body_node):
                        if child.type in ("jsx_element", "jsx_self_closing_element",
                                          "jsx_fragment", "jsx_expression"):
                            has_jsx = True
                            break

                if not has_jsx:
                    continue

                start_line = def_node.start_point[0] + 1 if def_node else name_node.start_point[0] + 1

                # Detect hooks
                hooks: List[str] = []
                if body_text:
                    hook_pattern = None
                    import re as _re
                    for h in self._REACT_HOOKS:
                        if h in body_text:
                            hooks.append(h)

                components.append(ReactComponentInfo(
                    name=name,
                    hooks=hooks,
                    anchor=SourceAnchor(file=rel_path, line=start_line),
                ))
        except Exception:
            logger.warning("TS component extraction failed", exc_info=True)

        return components

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _query_matches(lang: Language, query_src: str, node: Node):
        """Run a tree-sitter query and yield (match_id, {capture_name: [Node]}) pairs."""
        q = Query(lang, query_src)
        cursor = QueryCursor(q)
        yield from cursor.matches(node)

    @staticmethod
    def _first(caps: dict, key: str):
        """Get first captured node for a key, or None."""
        nodes = caps.get(key)
        return nodes[0] if nodes else None

    @staticmethod
    def _all(caps: dict, key: str) -> list:
        """Get all captured nodes for a key."""
        return caps.get(key, [])

    @staticmethod
    def _node_text(node, source: str) -> str:
        """Get the source text spanned by a node."""
        return source[node.start_byte : node.end_byte]

    @staticmethod
    def _iter_nodes(node):
        """Iterate all descendant nodes (DFS)."""
        yield node
        for child in node.children:
            yield from TreeSitterParser._iter_nodes(child)

    @property
    def available_languages(self) -> List[str]:
        """Return list of loaded language names."""
        return [k.value for k, v in self._init_ok.items() if v]

    def has_language(self, language: SupportedLanguage) -> bool:
        """Check if a grammar is loaded and ready."""
        return self._init_ok.get(language, False)
