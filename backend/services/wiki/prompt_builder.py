"""
PromptBuilder — constructs LLM prompts from structured AST data (ModuleInfo).

Extracted from WikiGenerator to respect SRP. Uses list+join instead of
repeated string concatenation for efficiency with large modules.
"""

from typing import List

from models.entities import ModuleInfo


class PromptBuilder:
    """Builds language-specific prompts for DeepSeek/OpenAI-compatible LLMs."""

    # Prompt budget: if the raw prompt exceeds this many characters,
    # we truncate entity lists to stay under model context limits.
    MAX_PROMPT_CHARS = 28000

    @staticmethod
    def _format_anchor(module_path: str, line: int) -> str:
        return f"[@src:{module_path}:{line}]"

    # ---- Public API ----

    def build(self, module: ModuleInfo) -> str:
        """Construct the full LLM prompt for a single module."""
        language_label = module.language.value.capitalize()

        parts: List[str] = []
        parts.append(
            f"你是 {language_label} 代码文档专家。根据以下模块的结构化摘要，生成一份简洁的 Markdown Wiki 文档。\n\n"
            "**规则**：\n"
            "1. 用中文撰写\n"
            "2. 每个实体（模块、类、方法、接口、组件）使用 [@src:模块路径:行号] 标注源码位置（我已提供，直接保留）\n"
            "3. 包含: 模块概述、类描述（含方法表格）、模块级函数、接口/类型定义、组件、依赖关系\n"
            "4. 输出纯 Markdown，不添加额外解释\n"
            "5. 对私有成员（以 _ 开头）只列出名称无需详细描述\n\n"
            f"**模块**: `{module.path}` ({module.total_lines} 行, {language_label})\n"
            f"**概述**: {module.docstring or '无'}\n"
        )

        # Classes
        parts.append(f"\n**类** ({len(module.classes)} 个):\n")
        classes_text = self._build_class_section(module)
        parts.append(classes_text if classes_text else "无\n")

        # Functions
        parts.append(f"\n**函数** ({len(module.functions)} 个):\n")
        funcs_text = self._build_function_section(module)
        parts.append(funcs_text if funcs_text else "无\n")

        # Interfaces
        parts.append(f"\n**接口/类型** ({len(module.interfaces)} 个):\n")
        ifaces_text = self._build_interface_section(module)
        parts.append(ifaces_text if ifaces_text else "无\n")

        # Components
        parts.append(f"\n**React 组件** ({len(module.components)} 个):\n")
        comp_text = self._build_component_section(module)
        parts.append(comp_text if comp_text else "无\n")

        # Dependencies
        deps_text = ", ".join(module.imports[:15]) if module.imports else "无内部依赖"
        ext_deps = ", ".join(module.external_imports[:10]) if module.external_imports else "无"
        parts.append(f"\n**内部依赖**: {deps_text}\n")
        parts.append(f"**外部依赖**: {ext_deps}\n")

        parts.append("\n输出:")

        prompt = "".join(parts)

        # Truncate if over budget
        if len(prompt) > self.MAX_PROMPT_CHARS:
            prompt = prompt[: self.MAX_PROMPT_CHARS - 200] + "\n\n[... 内容过长已截断 ...]\n\n输出:"

        return prompt

    # ---- Section builders (each uses list+join) ----

    def _build_class_section(self, module: ModuleInfo) -> str:
        lines: List[str] = []
        for cls in module.classes:
            line = f"\n### 类: {cls.name}"
            if cls.bases:
                line += f" (继承: {', '.join(cls.bases)})"
            anchor_line = cls.anchor.line if cls.anchor else "?"
            line += f" [@src:{module.path}:{anchor_line}]\n"
            lines.append(line)
            if cls.docstring:
                lines.append(f"  描述: {cls.docstring[:200]}\n")
            if cls.methods:
                lines.append("  方法:\n")
                for m in cls.methods:
                    sig = m.signature
                    method_line = f"    - {sig}"
                    if m.anchor:
                        method_line += f" [@src:{module.path}:{m.anchor.line}]"
                    method_line += "\n"
                    lines.append(method_line)
                    if m.docstring:
                        lines.append(f"      描述: {m.docstring[:150]}\n")
        return "".join(lines)

    def _build_function_section(self, module: ModuleInfo) -> str:
        lines: List[str] = []
        for fn in module.functions:
            anchor_line = fn.anchor.line if fn.anchor else "?"
            lines.append(
                f"\n### 函数: {fn.signature} [@src:{module.path}:{anchor_line}]\n"
            )
            if fn.docstring:
                lines.append(f"  描述: {fn.docstring[:200]}\n")
        return "".join(lines)

    def _build_interface_section(self, module: ModuleInfo) -> str:
        lines: List[str] = []
        for iface in module.interfaces:
            anchor_line = iface.anchor.line if iface.anchor else "?"
            lines.append(
                f"\n### 接口: {iface.name} [@src:{module.path}:{anchor_line}]\n"
            )
            if iface.docstring:
                lines.append(f"  描述: {iface.docstring[:200]}\n")
            if iface.members:
                lines.append("  成员:\n")
                for m in iface.members[:15]:
                    lines.append(f"    - {m['name']}: {m.get('type', 'any')}\n")
        return "".join(lines)

    def _build_component_section(self, module: ModuleInfo) -> str:
        lines: List[str] = []
        for comp in module.components:
            anchor_line = comp.anchor.line if comp.anchor else "?"
            lines.append(
                f"\n### 组件: {comp.name} [@src:{module.path}:{anchor_line}]\n"
            )
            if comp.props_type:
                lines.append(f"  属性类型: {comp.props_type}\n")
            if comp.hooks:
                lines.append(f"  使用的 Hook: {', '.join(comp.hooks)}\n")
        return "".join(lines)
