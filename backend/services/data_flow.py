"""
Data Flow / Taint Analysis + Control Flow Graph (CFG) for Python.

Combined module providing:
1. DataFlowAnalyzer: tracks variable propagation within functions
2. TaintAnalyzer: tracks untrusted data flow from sources → sinks
3. CFGBuilder: constructs basic-block CFG with cyclomatic complexity
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from tree_sitter import Language, Node, Parser

from models.entities import SourceAnchor, SupportedLanguage

logger = logging.getLogger("code-wiki.data_flow")


# ======================================================================
# Shared helpers
# ======================================================================

@dataclass
class BasicBlock:
    """A basic block in a control flow graph."""
    id: int
    start_line: int
    end_line: int
    statements: List[SourceAnchor] = field(default_factory=list)
    successors: List[int] = field(default_factory=list)
    predecessors: List[int] = field(default_factory=list)
    is_loop_header: bool = False
    is_entry: bool = False
    is_exit: bool = False


@dataclass
class ControlFlowGraph:
    """Control Flow Graph for a single function."""
    function_name: str
    blocks: List[BasicBlock]
    entry_block: int
    exit_block: int

    @property
    def cyclomatic_complexity(self) -> int:
        """McCabe cyclomatic complexity: E - N + 2P."""
        e = sum(len(b.successors) for b in self.blocks)
        n = len(self.blocks)
        return max(1, e - n + 2)

    @property
    def max_nesting_depth(self) -> int:
        """Approximate max nesting depth from block structure."""
        return self._dfs_depth(self.entry_block, set(), 0)

    def _dfs_depth(self, block_id: int, visited: Set[int], depth: int) -> int:
        if block_id in visited or block_id >= len(self.blocks):
            return depth
        visited.add(block_id)
        max_d = depth
        for succ in self.blocks[block_id].successors:
            max_d = max(max_d, self._dfs_depth(succ, visited.copy(), depth + 1))
        return max_d

    @property
    def unreachable_blocks(self) -> List[int]:
        """Return IDs of blocks not reachable from entry."""
        reachable = self._reachable_from(self.entry_block)
        return [b.id for b in self.blocks if b.id not in reachable]

    def _reachable_from(self, start: int) -> Set[int]:
        visited = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in visited or cur >= len(self.blocks):
                continue
            visited.add(cur)
            stack.extend(self.blocks[cur].successors)
        return visited

    def to_mermaid(self, title: str = "") -> str:
        """Export as Mermaid flowchart."""
        lines = ["graph TD"]
        if title:
            lines.append(f'    title["{title}"]')
        for b in self.blocks:
            label = f"B{b.id}"
            if b.is_entry:
                label += "\\n[entry]"
            if b.is_exit:
                label += "\\n[exit]"
            if b.is_loop_header:
                label += "\\n[loop]"
            style = ""
            if b.is_entry:
                style = ":::entry"
            elif b.is_exit:
                style = ":::exit"
            lines.append(f'    block{b.id}["{label}"]{style}')
        for b in self.blocks:
            for succ in b.successors:
                lines.append(f"    block{b.id} --> block{succ}")
        # Add legend
        lines.append("    classDef entry fill:#90EE90")
        lines.append("    classDef exit fill:#FFB6C1")
        return "\n".join(lines)


@dataclass
class DataFlowEdge:
    """A data flow edge from one variable to another."""
    source_var: str
    target_var: str
    location: SourceAnchor
    operation: str  # "assign" | "call_arg" | "return" | "phi"


@dataclass
class TaintFlow:
    """A complete taint flow from source to sink."""
    source: SourceAnchor
    sink: SourceAnchor
    path: List[DataFlowEdge] = field(default_factory=list)
    sanitized: bool = False
    risk_level: str = "medium"  # "high" | "medium" | "low"


# ======================================================================
# Taint sources / sinks / sanitizers (Python)
# ======================================================================

_PY_TAINT_SOURCES: Set[str] = {
    "request.args", "request.form", "request.json", "request.data",
    "os.environ.get", "os.environ", "input", "sys.argv",
    "open", "pathlib.Path.read_text", "Path.read_text",
    "file.read", "raw_input",
}

_PY_TAINT_SINKS: Set[str] = {
    "subprocess.run", "subprocess.call", "subprocess.Popen",
    "os.system", "os.popen", "os.exec",
    "eval", "exec", "compile",
    "sqlite3.execute", "sqlite3.executemany",
    "cursor.execute", "cursor.executemany",
    "open",
    "pickle.load", "pickle.loads",
    "yaml.load", "marshal.loads",
    "ctypes.CDLL",
}

_PY_TAINT_SANITIZERS: Set[str] = {
    "html.escape", "html.unescape",
    "int", "float", "str", "bool", "list", "dict",
    "json.loads", "json.dumps",
    "re.match", "re.fullmatch", "re.search",
    "bleach.clean", "markupsafe.escape",
    "hashlib.sha256", "hashlib.md5",
    "base64.b64encode", "base64.b64decode",
    "urllib.parse.quote", "urllib.parse.quote_plus",
}


# ======================================================================
# CFG Builder
# ======================================================================

class CFGBuilder:
    """Builds a Control Flow Graph from a tree-sitter function node."""

    # Branch-creating node types
    BRANCH_TYPES = {
        "if_statement", "elif_clause", "else_clause",
        "for_statement", "while_statement",
        "try_statement", "except_clause", "finally_clause",
        "with_statement", "match_statement", "case_clause",
    }

    def build(self, func_node: Node, source: str, func_name: str) -> ControlFlowGraph:
        """Build CFG for a single function."""
        body_node = self._find_body(func_node)
        if body_node is None:
            # Empty function — minimal CFG
            entry = BasicBlock(id=0, start_line=func_node.start_point[0] + 1,
                              end_line=func_node.end_point[0] + 1,
                              is_entry=True, is_exit=True)
            return ControlFlowGraph(
                function_name=func_name,
                blocks=[entry],
                entry_block=0, exit_block=0,
            )

        # Collect statements as linear sequence, then split into blocks
        statements = self._collect_statements(body_node, source)
        blocks = self._split_into_blocks(statements, func_node, source)
        self._connect_blocks(blocks)

        start_line = func_node.start_point[0] + 1
        end_line = func_node.end_point[0] + 1

        # Mark entry and exit
        entry = BasicBlock(
            id=0, start_line=start_line, end_line=start_line,
            is_entry=True,
        )
        exit_blk = BasicBlock(
            id=len(blocks) + 1, start_line=end_line, end_line=end_line,
            is_exit=True,
        )

        all_blocks = [entry] + blocks + [exit_blk]

        # Entry → first real block
        if blocks:
            entry.successors = [1]
            blocks[0].predecessors.append(0)

        # Blocks with no successors → exit
        for b in blocks:
            if not b.successors:
                b.successors = [len(all_blocks) - 1]
                exit_blk.predecessors.append(b.id)

        # Re-index
        for i, b in enumerate(all_blocks):
            b.id = i

        return ControlFlowGraph(
            function_name=func_name,
            blocks=all_blocks,
            entry_block=0,
            exit_block=len(all_blocks) - 1,
        )

    def _find_body(self, func_node: Node) -> Optional[Node]:
        for child in func_node.children:
            if child.type == "block":
                return child
        return None

    def _collect_statements(self, body_node: Node, source: str) -> List[dict]:
        """Collect statements with their branch context."""
        stmts: List[dict] = []
        for child in body_node.children:
            if child.type in ("expression_statement", "return_statement",
                              "assert_statement", "raise_statement",
                              "assignment", "augmented_assignment",
                              "yield_statement", "pass_statement",
                              "break_statement", "continue_statement",
                              "delete_statement", "global_statement",
                              "nonlocal_statement", "import_statement",
                              "import_from_statement", "exec_statement"):
                stmts.append({
                    "type": child.type,
                    "line": child.start_point[0] + 1,
                    "node": child,
                    "is_branch": False,
                })
            elif child.type in self.BRANCH_TYPES:
                stmts.append({
                    "type": child.type,
                    "line": child.start_point[0] + 1,
                    "node": child,
                    "is_branch": True,
                })
        return stmts

    def _split_into_blocks(self, statements: List[dict], func_node: Node, source: str) -> List[BasicBlock]:
        """Split statements into basic blocks at branch points."""
        if not statements:
            return []

        blocks: List[BasicBlock] = []
        current_stmts: List[SourceAnchor] = []
        block_id = 0
        branch_stack: List[int] = []  # block IDs for pending branch join points

        for stmt in statements:
            if stmt["is_branch"]:
                # Flush current block
                if current_stmts:
                    blocks.append(BasicBlock(
                        id=block_id,
                        start_line=current_stmts[0].line,
                        end_line=current_stmts[-1].line,
                        statements=current_stmts,
                    ))
                    block_id += 1
                    current_stmts = []

                # Create branch block
                blocks.append(BasicBlock(
                    id=block_id,
                    start_line=stmt["line"],
                    end_line=self._get_node_end_line(stmt["node"]),
                    statements=[
                        SourceAnchor(file="", line=stmt["line"]),
                    ],
                ))
                branch_block_id = block_id
                block_id += 1

                # Mark as loop header if applicable
                if stmt["type"] in ("for_statement", "while_statement"):
                    blocks[-1].is_loop_header = True

                branch_stack.append(branch_block_id)
            else:
                anchor = SourceAnchor(file="", line=stmt["line"])
                current_stmts.append(anchor)

                # Check if this statement follows a branch end
                if stmt["type"] in ("break_statement", "continue_statement", "return_statement",
                                    "raise_statement", "yield_statement"):
                    if current_stmts:
                        blocks.append(BasicBlock(
                            id=block_id,
                            start_line=current_stmts[0].line,
                            end_line=current_stmts[-1].line,
                            statements=current_stmts,
                        ))
                        block_id += 1
                        current_stmts = []

        # Flush remaining
        if current_stmts:
            blocks.append(BasicBlock(
                id=block_id,
                start_line=current_stmts[0].line,
                end_line=current_stmts[-1].line,
                statements=current_stmts,
            ))

        return blocks

    def _connect_blocks(self, blocks: List[BasicBlock]):
        """Connect basic blocks with sequential and branch edges."""
        for i in range(len(blocks) - 1):
            # Sequential flow (default)
            if not blocks[i].successors:
                blocks[i].successors.append(blocks[i + 1].id)
                blocks[i + 1].predecessors.append(blocks[i].id)

    @staticmethod
    def _get_node_end_line(node: Node) -> int:
        return node.end_point[0] + 1


# ======================================================================
# Data Flow Analyzer (simplified, function-local)
# ======================================================================

class DataFlowAnalyzer:
    """Tracks variable definitions and uses within a function."""

    def analyze_function(self, func_node: Node, source: str, rel_path: str) -> List[DataFlowEdge]:
        """Extract data flow edges from a function's AST."""
        edges: List[DataFlowEdge] = []
        body = self._find_function_body(func_node)
        if body is None:
            return edges

        self._walk_for_assignments(body, source, rel_path, edges)
        return edges

    def _find_function_body(self, func_node: Node) -> Optional[Node]:
        for child in func_node.children:
            if child.type == "block":
                return child
        return None

    def _walk_for_assignments(self, node: Node, source: str, rel_path: str, edges: List[DataFlowEdge]):
        """Walk the AST finding assignment patterns."""
        for child in node.children:
            if child.type == "assignment":
                # x = expr
                self._extract_assignment(child, source, rel_path, edges)
            elif child.type == "augmented_assignment":
                self._extract_augmented(child, source, rel_path, edges)
            elif child.type == "expression_statement":
                for gc in child.children:
                    if gc.type == "assignment":
                        self._extract_assignment(gc, source, rel_path, edges)
            # Recurse (but not into nested functions)
            if child.type not in ("function_definition", "lambda", "class_definition"):
                self._walk_for_assignments(child, source, rel_path, edges)

    def _extract_assignment(self, assign_node: Node, source: str, rel_path: str, edges: List[DataFlowEdge]):
        """Extract data flow from an assignment: target = value."""
        targets: List[str] = []
        value_vars: List[str] = []

        for child in assign_node.children:
            if child.type == "=":
                continue
            if not targets:
                # Left side(s): identifiers
                targets = self._extract_names(child)
            elif not value_vars:
                # Right side: variable references
                value_vars = self._extract_names(child)

        line = assign_node.start_point[0] + 1
        for tgt in targets:
            for src in value_vars:
                edges.append(DataFlowEdge(
                    source_var=src,
                    target_var=tgt,
                    location=SourceAnchor(file=rel_path, line=line),
                    operation="assign",
                ))
            if not value_vars:
                edges.append(DataFlowEdge(
                    source_var="<literal>",
                    target_var=tgt,
                    location=SourceAnchor(file=rel_path, line=line),
                    operation="assign",
                ))

    def _extract_augmented(self, node: Node, source: str, rel_path: str, edges: List[DataFlowEdge]):
        """x += expr → x reads itself, writes itself."""
        target = value = None
        for child in node.children:
            if child.type == "identifier" and target is None:
                target = self._node_text(child, source)
            elif child.type not in ("+=", "-=", "*=", "/=", "%=", "**=", "//=", "&=", "|=", "^=", "<<=", ">>="):
                names = self._extract_names(child)
                if names:
                    value = names

        if target:
            line = node.start_point[0] + 1
            if value:
                for v in value:
                    edges.append(DataFlowEdge(
                        source_var=v,
                        target_var=target,
                        location=SourceAnchor(file=rel_path, line=line),
                        operation="assign",
                    ))

    def _extract_names(self, node: Node) -> List[str]:
        """Extract variable names from a node (identifier or attribute)."""
        names: List[str] = []
        if node.type == "identifier":
            names.append(self._node_text(node, ""))
        elif node.type == "attribute":
            names.append(self._node_text(node, ""))
        elif node.type in ("tuple", "list", "pattern_list"):
            for child in node.children:
                if child.type == "identifier":
                    names.append(self._node_text(child, ""))
        elif node.type == "call":
            # Function call: extract function name and args
            for child in node.children:
                if child.type == "identifier":
                    names.append(self._node_text(child, ""))
                elif child.type == "argument_list":
                    for arg in child.children:
                        if arg.type == "identifier":
                            names.append(self._node_text(arg, ""))
        else:
            # Recursively extract identifiers
            for child in node.children:
                names.extend(self._extract_names(child))
        return names

    @staticmethod
    def _node_text(node: Node, source: str) -> str:
        if source:
            return source[node.start_byte: node.end_byte]
        return node.text.decode() if isinstance(node.text, bytes) else str(node.text)


# ======================================================================
# Taint Analyzer
# ======================================================================

class TaintAnalyzer:
    """Tracks tainted data from sources to sinks."""

    def __init__(self):
        self.sources = _PY_TAINT_SOURCES
        self.sinks = _PY_TAINT_SINKS
        self.sanitizers = _PY_TAINT_SANITIZERS

    def analyze_function(
        self, func_node: Node, source: str, rel_path: str,
        data_flow_edges: Optional[List[DataFlowEdge]] = None,
    ) -> List[TaintFlow]:
        """Find taint flows in a function."""
        flows: List[TaintFlow] = []

        # Find taint sources in this function
        sources = self._find_taint_sources(func_node, source, rel_path)
        sinks = self._find_taint_sinks(func_node, source, rel_path)
        sanitizer_locs = self._find_sanitizers(func_node, source, rel_path)

        if not sources or not sinks:
            return flows

        # If data flow edges provided, try to trace paths
        if data_flow_edges:
            for taint_src in sources:
                for taint_sink in sinks:
                    path = self._trace_path(taint_src, taint_sink, data_flow_edges)
                    sanitized = any(
                        sloc.line >= taint_src.line and sloc.line <= taint_sink.line
                        for sloc in sanitizer_locs
                    )
                    risk = "high"
                    if sanitized:
                        risk = "low"
                    elif taint_src.line < taint_sink.line:
                        risk = "medium"

                    flows.append(TaintFlow(
                        source=taint_src,
                        sink=taint_sink,
                        path=path,
                        sanitized=sanitized,
                        risk_level=risk,
                    ))
        else:
            # Simple: just report source-sink pairs
            for taint_src in sources:
                for taint_sink in sinks:
                    flows.append(TaintFlow(
                        source=taint_src,
                        sink=taint_sink,
                        sanitized=False,
                        risk_level="medium",
                    ))

        return flows

    def _find_taint_sources(self, node: Node, source: str, rel_path: str) -> List[SourceAnchor]:
        return self._match_functions(node, source, rel_path, self.sources)

    def _find_taint_sinks(self, node: Node, source: str, rel_path: str) -> List[SourceAnchor]:
        return self._match_functions(node, source, rel_path, self.sinks)

    def _find_sanitizers(self, node: Node, source: str, rel_path: str) -> List[SourceAnchor]:
        return self._match_functions(node, source, rel_path, self.sanitizers)

    def _match_functions(self, node: Node, source: str, rel_path: str, patterns: Set[str]) -> List[SourceAnchor]:
        """Find calls to functions matching patterns."""
        anchors: List[SourceAnchor] = []
        text = source[node.start_byte: node.end_byte] if source else ""

        for pattern in patterns:
            if pattern in text:
                # Find the line(s) where this pattern occurs
                for i, line_text in enumerate(text.split("\n")):
                    if pattern in line_text:
                        line_num = node.start_point[0] + 1 + i
                        anchors.append(SourceAnchor(file=rel_path, line=line_num))
        return anchors

    def _trace_path(self, src: SourceAnchor, sink: SourceAnchor, edges: List[DataFlowEdge]) -> List[DataFlowEdge]:
        """Trace data flow path from source to sink using edges."""
        # Simplified: return edges between src and sink lines
        return [
            e for e in edges
            if e.location.line >= src.line and e.location.line <= sink.line
        ]
