"""
MarkdownBuilder — generates Markdown content without LLM.

Handles:
- Fallback markdown (when LLM fails)
- Empty module markdown
- Index page (architecture overview)

All string building uses list+join for efficiency.
"""

from datetime import datetime
from typing import Callable, Dict, List

from models.entities import ModuleInfo


class MarkdownBuilder:
    """Builds Markdown documents from structured module data."""

    def __init__(self, source_to_wiki_path: Callable[[str], str]) -> None:
        self._source_to_wiki_path = source_to_wiki_path

    # ---- Fallback (no LLM) ----

    def build_fallback(self, module: ModuleInfo, error: str) -> str:
        """Generate basic Markdown without LLM (when API fails)."""
        language_label = module.language.value.capitalize()
        lines: List[str] = [
            f"# {module.path}",
            "",
            f"> ⚠️ LLM 生成失败: {error}",
            "> 以下为基础结构摘要。",
            "",
        ]

        if module.docstring:
            lines += ["## 模块概述", "", module.docstring, ""]

        # Classes
        if module.classes:
            lines += self._fallback_classes(module)

        # Functions
        if module.functions:
            lines += self._fallback_functions(module)

        # Interfaces (TS)
        if module.interfaces:
            lines += self._fallback_interfaces(module)

        # React Components
        if module.components:
            lines += self._fallback_components(module)

        # Imports
        if module.imports:
            lines += [
                "## 内部依赖",
                "",
                ", ".join(f"`{i}`" for i in module.imports),
                "",
            ]

        lines += [
            "***",
            f"*由 Code Wiki 自动生成（fallback 模板）· {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        ]
        return "\n".join(lines)

    def build_empty(self, module: ModuleInfo) -> str:
        """Minimal Markdown for empty modules."""
        language_label = module.language.value.capitalize()
        return (
            f"# {module.path}\n\n"
            f"*空模块（{language_label}），无类、函数或组件定义*\n\n"
            "***\n"
            f"*由 Code Wiki 自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}*"
        )

    # ---- Index page ----

    def build_index(
        self,
        modules: Dict[str, ModuleInfo],
        dep_graph_stats: dict,
    ) -> str:
        """Generate the architecture overview index.md."""
        total_classes = sum(len(m.classes) for m in modules.values())
        total_funcs = sum(len(m.functions) for m in modules.values())
        total_interfaces = sum(len(m.interfaces) for m in modules.values())
        total_components = sum(len(m.components) for m in modules.values())

        # Count by language
        lang_counts: Dict[str, int] = {}
        for m in modules.values():
            lang_counts[m.language.value] = lang_counts.get(m.language.value, 0) + 1

        lang_summary = ", ".join(
            f"{k.capitalize()}: {v}" for k, v in sorted(lang_counts.items())
        )

        lines: List[str] = [
            "# 项目架构概览",
            "",
            f"> 自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "## 统计",
            "",
            "| 指标 | 数量 |",
            "|------|------|",
            f"| 模块 | {len(modules)} ({lang_summary}) |",
            f"| 类 | {total_classes} |",
            f"| 函数 | {total_funcs} |",
            f"| 接口/类型 | {total_interfaces} |",
            f"| React 组件 | {total_components} |",
            f"| 依赖边 | {dep_graph_stats.get('total_edges', 0)} |",
            "",
            "## 模块列表",
            "",
        ]

        # Group by directory
        groups: Dict[str, List[str]] = {}
        for path in sorted(modules.keys()):
            parts = path.replace("\\", "/").split("/")
            group = parts[0] if len(parts) > 1 else "root"
            groups.setdefault(group, []).append(path)

        for group, paths in sorted(groups.items()):
            lines.append(f"### {group}/")
            for path in paths:
                mod = modules[path]
                wiki_path = self._source_to_wiki_path(path)
                entities = f"{len(mod.classes)}C/{len(mod.functions)}F"
                if mod.interfaces:
                    entities += f"/{len(mod.interfaces)}I"
                if mod.components:
                    entities += f"/{len(mod.components)}Comp"
                lang_badge = f"[{mod.language.value}]"
                lines.append(
                    f"- {lang_badge} [{path}]({wiki_path}) "
                    f"({mod.total_lines} 行, {entities})"
                )
            lines.append("")

        lines += [
            "## 依赖关系",
            "",
            "参见 [架构图](diagrams/architecture.mmd) 和 [依赖图](diagrams/dependencies.mmd)。",
            "",
            "***",
            "*由 Code Wiki 自动生成*",
        ]

        return "\n".join(lines)

    # ---- Private helpers ----

    def _fallback_classes(self, module: ModuleInfo) -> List[str]:
        lines = ["## 类", ""]
        for cls in module.classes:
            lines.append(f"### {cls.name}")
            if cls.anchor:
                lines.append(f"[@src:{module.path}:{cls.anchor.line}]")
            lines.append("")
            if cls.docstring:
                lines.append(f"{cls.docstring}\n")
            if cls.methods:
                lines.append("| 方法 | 签名 |")
                lines.append("|------|------|")
                for m in cls.methods:
                    sig = m.signature.replace("|", "\\|")
                    anchor = (
                        f"[@src:{module.path}:{m.anchor.line}]"
                        if m.anchor
                        else ""
                    )
                    lines.append(f"| {m.name} | {sig} {anchor} |")
                lines.append("")
        return lines

    def _fallback_functions(self, module: ModuleInfo) -> List[str]:
        lines = ["## 函数", ""]
        for fn in module.functions:
            lines.append(f"### {fn.signature}")
            if fn.anchor:
                lines.append(f"[@src:{module.path}:{fn.anchor.line}]")
            lines.append("")
            if fn.docstring:
                lines.append(f"{fn.docstring}\n")
        return lines

    def _fallback_interfaces(self, module: ModuleInfo) -> List[str]:
        lines = ["## 接口/类型", ""]
        for iface in module.interfaces:
            lines.append(f"### {iface.name}")
            if iface.anchor:
                lines.append(f"[@src:{module.path}:{iface.anchor.line}]")
            lines.append("")
            if iface.docstring:
                lines.append(f"{iface.docstring}\n")
            if iface.members:
                lines.append("| 成员 | 类型 |")
                lines.append("|------|------|")
                for m in iface.members:
                    lines.append(f"| {m['name']} | {m.get('type', 'any')} |")
                lines.append("")
        return lines

    def _fallback_components(self, module: ModuleInfo) -> List[str]:
        lines = ["## React 组件", ""]
        for comp in module.components:
            lines.append(f"### {comp.name}")
            if comp.anchor:
                lines.append(f"[@src:{module.path}:{comp.anchor.line}]")
            lines.append("")
            if comp.props_type:
                lines.append(f"- 属性类型: `{comp.props_type}`")
            if comp.hooks:
                lines.append(f"- 使用的 Hook: {', '.join(comp.hooks)}")
            lines.append("")
        return lines
