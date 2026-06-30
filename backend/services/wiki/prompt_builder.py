"""
PromptBuilder — constructs LLM prompts from structured AST data (ModuleInfo).

v2: Differentiated prompts based on module role + cross-module dependency context.
Extracted from WikiGenerator to respect SRP. Uses list+join instead of
repeated string concatenation for efficiency with large modules.
"""

from typing import Dict, List, Optional

from models.entities import ModuleInfo


class PromptBuilder:
    """Builds language-specific, role-aware prompts for LLMs."""

    # Prompt budget: if the raw prompt exceeds this many characters,
    # we truncate entity lists to stay under model context limits.
    MAX_PROMPT_CHARS = 28_000

    # ── Role classification ──────────────────────────────────────────────

    # Directory-prefix → role mapping (checked in order, first match wins)
    _ROLE_RULES: List[tuple] = [
        ("routes/", "api_entry"),
        ("controllers/", "api_entry"),
        ("handlers/", "api_entry"),
        ("views/", "api_entry"),
        ("services/", "business_logic"),
        ("core/", "business_logic"),
        ("domain/", "business_logic"),
        ("models/", "data_model"),
        ("entities/", "data_model"),
        ("schemas/", "data_model"),
        ("types/", "data_model"),
        ("interfaces/", "data_model"),
        ("utils/", "utility"),
        ("helpers/", "utility"),
        ("lib/", "utility"),
        ("common/", "utility"),
        ("config/", "configuration"),
        ("settings/", "configuration"),
        ("components/", "ui_component"),
        ("pages/", "ui_page"),
        ("hooks/", "hook"),
        ("store/", "state_management"),
        ("middleware/", "middleware"),
        ("tests/", "test"),
    ]

    @classmethod
    def _classify_role(cls, path: str) -> str:
        """Classify a module path into a role based on directory prefix."""
        norm = path.replace("\\", "/")
        for prefix, role in cls._ROLE_RULES:
            if norm.startswith(prefix):
                return role
        return "general"

    # ── Role prompts ─────────────────────────────────────────────────────

    _ROLE_PROMPTS: Dict[str, str] = {
        "api_entry": (
            "**文档重点**：\n"
            "1. 说明这个 API 入口模块提供哪些端点/路由及其用途\n"
            "2. 描述请求处理流程：（鉴权→参数校验→调用业务层→返回响应）\n"
            "3. 标注依赖的业务服务模块和返回的数据模型\n"
            "4. 列出入口函数/处理器的签名、HTTP 方法和路径\n"
        ),
        "business_logic": (
            "**文档重点**：\n"
            "1. 说明这个模块解决什么业务问题，核心职责是什么\n"
            "2. 描述关键业务流程/算法步骤（不是逐行复述代码）\n"
            "3. 标注它调用了哪些数据模型、工具模块和外部服务\n"
            "4. 对核心的公共方法给出调用示例（参数含义+返回值说明）\n"
        ),
        "data_model": (
            "**文档重点**：\n"
            "1. 说明这个数据模型/实体在整个系统中的定位（谁创建、谁使用）\n"
            "2. 对每个类/接口给出完整的字段/属性表格（名称、类型、含义、约束）\n"
            "3. 标注关联关系（1:1, 1:N, 继承, 依赖）\n"
            "4. 提取验证规则和生命周期（创建/更新/删除钩子）\n"
        ),
        "utility": (
            "**文档重点**：\n"
            "1. 列出所有公共函数，按功能分组（字符串/日期/IO/网络…）\n"
            "2. 每个函数给出简洁的用途说明、参数和返回值\n"
            "3. 给出典型使用场景的代码示例（1-2行即可）\n"
            "4. 标注纯函数/有副作用的区别\n"
        ),
        "configuration": (
            "**文档重点**：\n"
            "1. 列出所有配置项及其默认值、类型和环境变量映射\n"
            "2. 说明配置加载顺序和覆盖规则\n"
            "3. 标注哪些配置影响运行时行为、哪些仅在初始化时生效\n"
        ),
        "ui_component": (
            "**文档重点**：\n"
            "1. 说明组件的 UI 职责和复用场景\n"
            "2. 列出所有 Props（名称、类型、是否必填、默认值）\n"
            "3. 描述组件内部状态管理和使用的 Hook\n"
            "4. 标注组件发出的事件/回调\n"
        ),
        "ui_page": (
            "**文档重点**：\n"
            "1. 说明页面的路由和访问权限\n"
            "2. 描述页面布局和子组件树\n"
            "3. 标注数据加载策略（SSR/CSR/ISR）和状态管理\n"
        ),
        "hook": (
            "**文档重点**：\n"
            "1. 说明 Hook 封装了哪些状态/副作用逻辑\n"
            "2. 列出参数和返回值（类型+含义）\n"
            "3. 给出基本使用示例\n"
        ),
        "state_management": (
            "**文档重点**：\n"
            "1. 说明 Store 管理的全局状态和更新方式\n"
            "2. 列出所有 state 字段（类型、含义、默认值）\n"
            "3. 描述 actions/reducers 及其触发场景\n"
        ),
        "middleware": (
            "**文档重点**：\n"
            "1. 说明中间件在请求/响应链中的位置\n"
            "2. 描述处理逻辑和条件\n"
            "3. 标注对请求/响应的修改\n"
        ),
        "test": (
            "**文档重点**：\n"
            "1. 说明测试覆盖的功能模块和场景\n"
            "2. 描述测试数据准备策略和 mock 方式\n"
            "3. 列出关键测试用例的 Given-When-Then\n"
        ),
        "general": (
            "**文档重点**：\n"
            "1. 说明模块的核心职责和在整个项目中的定位\n"
            "2. 对每个公开类/函数给出简洁描述\n"
            "3. 标注依赖和导出\n"
        ),
    }

    @staticmethod
    def _format_anchor(module_path: str, line: int) -> str:
        return f"[@src:{module_path}:{line}]"

    # ── Public API ───────────────────────────────────────────────────────

    def build(
        self,
        module: ModuleInfo,
        *,
        deps_context: Optional[Dict[str, object]] = None,
    ) -> str:
        """Construct the full LLM prompt for a single module.

        Args:
            module: The analyzed module to document.
            deps_context: Optional cross-module context dict with keys:
                - "dependencies": list of module summaries this module imports
                - "dependents": list of module summaries that import this module
                - "graph_rank": (rank, total) tuple for hub/leaf classification
        """
        language_label = module.language.value.capitalize()
        role = self._classify_role(module.path)
        role_guidance = self._ROLE_PROMPTS.get(role, self._ROLE_PROMPTS["general"])

        parts: List[str] = []

        # ── Header: role-specific system prompt ──
        parts.append(
            f"你是 {language_label} 代码文档专家。"
            f"你正在分析一个 **{role_label(role)}** 模块。"
            f"请根据下面的结构化摘要生成一份专业、有针对性的 Markdown Wiki 文档。\n\n"
            "**通用规则**：\n"
            "1. 用中文撰写，专业简洁\n"
            "2. 每个实体（模块、类、方法、接口、组件）使用 [@src:模块路径:行号] 标注源码位置（我已提供，直接保留）\n"
            "3. 输出纯 Markdown，不添加额外解释或客套话，不要输出任何 HTML 标签\n"
            "4. 对私有成员（以 _ 开头）只列出名称，无需详细描述\n"
            "5. 避免泛泛而谈，要结合具体代码内容给出有价值的描述\n"
            "6. 注意 Markdown 格式：表格、代码块、列表前必须有空行，否则不会被正确渲染\n\n"
            + role_guidance
            + "\n"
        )

        # ── Cross-module context (if provided) ──
        if deps_context:
            parts.append(self._build_deps_context(module.path, deps_context))

        # ── Module overview ──
        parts.append(
            f"**模块**: `{module.path}` ({module.total_lines} 行, {language_label})\n"
            f"**模块角色**: {role_label(role)}\n"
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
        ext_deps = (
            ", ".join(module.external_imports[:10])
            if module.external_imports
            else "无"
        )
        parts.append(f"\n**内部依赖**: {deps_text}\n")
        parts.append(f"**外部依赖**: {ext_deps}\n")

        parts.append("\n输出:")

        prompt = "".join(parts)

        # Truncate if over budget
        if len(prompt) > self.MAX_PROMPT_CHARS:
            prompt = (
                prompt[: self.MAX_PROMPT_CHARS - 200]
                + "\n\n[... 内容过长已截断 ...]\n\n输出:"
            )

        return prompt

    # ── Synthesis prompt (project-level architecture) ────────────────────

    def build_synthesis(
        self,
        all_modules: Dict[str, ModuleInfo],
        dep_stats: dict,
        topo: list,
    ) -> str:
        """Build a prompt for a project-level architecture synthesis document."""
        total = len(all_modules)
        # Summary stats
        total_classes = sum(len(m.classes) for m in all_modules.values())
        total_funcs = sum(len(m.functions) for m in all_modules.values())
        total_ifaces = sum(len(m.interfaces) for m in all_modules.values())
        total_comps = sum(len(m.components) for m in all_modules.values())

        parts: List[str] = [
            "你是高级软件架构师。请基于下方整个项目的模块摘要，生成一份 **项目架构综合文档**。\n\n"
            "**要求**：\n"
            "1. 用中文撰写，专业深入但可读性强\n"
            "2. 输出纯 Markdown，不添加客套话，不要输出任何 HTML 标签。注意 Markdown 格式：表格、代码块、列表前必须有空行，否则不会被正确渲染\n"
            "3. 必须包含以下章节：\n"
            "   - **项目概述**：根据模块内容推断项目的业务目的和技术栈\n"
            "   - **架构分层**：将模块按职责分层（API入口/业务逻辑/数据/工具/前端），描述每层职责和关键模块\n"
            "   - **核心业务流程**：从入口模块出发，追踪 2-3 条关键业务路径，描述数据如何流转\n"
            "   - **模块协作关系**：识别核心模块（被最多依赖的）和关键依赖关系\n"
            "   - **设计模式与约定**：识别项目中使用的设计模式和编码约定\n"
            "   - **建议与改进方向**：基于模块结构给出的架构优化建议\n"
            "4. 引用模块时用 `module_path` 标注\n\n"
            f"**项目规模**: {total} 个模块, {total_classes} 类, {total_funcs} 函数, {total_ifaces} 接口, {total_comps} 组件\n"
            f"**依赖边数**: {dep_stats.get('total_edges', 0)}\n"
            f"**独立模块数**: {dep_stats.get('isolated_modules', 0)}\n\n"
        ]

        # Enriched topology: attach role and entity counts
        parts.append("**核心模块排名（按依赖权重）**：\n")
        if topo:
            for path, score in topo[:15]:
                m = all_modules.get(path)
                role = self._classify_role(path) if m else "?"
                entities = m.total_entities if m else 0
                parts.append(
                    f"  - `{path}` | 角色: {role_label(role)} | "
                    f"实体数: {entities} | 依赖权重: {score}\n"
                )
        parts.append("\n")

        # Module summaries: one line per module
        parts.append("**所有模块摘要**：\n")
        for path in sorted(all_modules.keys()):
            m = all_modules[path]
            role = self._classify_role(path)
            brief = (m.docstring or "")[:120].replace("\n", " ")
            parts.append(
                f"  - `{path}` [{role_label(role)}] "
                f"({m.total_lines}行, {m.total_entities}实体)"
            )
            if brief:
                parts.append(f" — {brief}")
            parts.append("\n")

        parts.append("\n输出:")

        prompt = "".join(parts)
        if len(prompt) > self.MAX_PROMPT_CHARS:
            # Keep the header + as many modules as fit
            cutoff = self.MAX_PROMPT_CHARS - 500
            prompt = prompt[:cutoff] + "\n\n[... 模块列表已截断 ...]\n\n输出:"

        return prompt

    # ── Section builders ─────────────────────────────────────────────────

    def _build_deps_context(self, path: str, deps: Dict[str, object]) -> str:
        """Build cross-module context block showing upstream/downstream relationships."""
        lines: List[str] = []

        deps_list = deps.get("dependencies", [])
        dents_list = deps.get("dependents", [])

        if deps_list:
            lines.append("**上游依赖（本模块调用）**：\n")
            for d in deps_list:  # type: ignore[assignment]
                if isinstance(d, dict):
                    lines.append(
                        f"  - `{d.get('path', '?')}` — "
                        f"{d.get('summary', '')[:100]}\n"
                    )
            lines.append("\n")

        if dents_list:
            lines.append("**下游调用者（调用本模块）**：\n")
            for d in dents_list:  # type: ignore[assignment]
                if isinstance(d, dict):
                    lines.append(
                        f"  - `{d.get('path', '?')}` — "
                        f"{d.get('summary', '')[:100]}\n"
                    )
            lines.append("\n")

        rank_info = deps.get("graph_rank")
        if rank_info and isinstance(rank_info, (list, tuple)) and len(rank_info) == 2:
            rank, total = rank_info
            if total > 0:
                pct = int(rank / total * 100)
                if pct <= 10:
                    lines.append(
                        "⚠️ 此模块是项目的 **核心枢纽**（依赖权重 Top 10%），"
                        "请重点描述其与其他模块的协作方式。\n\n"
                    )
                elif rank <= 5:
                    lines.append(
                        "💡 此模块是项目的 **关键节点**（依赖权重 Top 5），"
                        "请说明其在整个架构中的地位。\n\n"
                    )

        if not lines:
            return ""
        return "**跨模块上下文**：\n" + "".join(lines)

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
                        method_line += (
                            f" [@src:{module.path}:{m.anchor.line}]"
                        )
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


# ── Helpers ──────────────────────────────────────────────────────────────

_ROLE_LABELS: Dict[str, str] = {
    "api_entry": "API 入口",
    "business_logic": "业务逻辑",
    "data_model": "数据模型",
    "utility": "工具/辅助",
    "configuration": "配置",
    "ui_component": "UI 组件",
    "ui_page": "页面",
    "hook": "React Hook",
    "state_management": "状态管理",
    "middleware": "中间件",
    "test": "测试",
    "general": "通用模块",
}


def role_label(role: str) -> str:
    """Human-readable label for a module role."""
    return _ROLE_LABELS.get(role, role.replace("_", " ").title())
