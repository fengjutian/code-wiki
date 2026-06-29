"""File scanning and analysis trigger."""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from config import _config, get_wiki_path
from services.scanner import Scanner
from services.analyzer import Analyzer
from services.dependency_graph import DependencyGraph
from services.wiki import WikiGenerator
from services.embedder import Embedder
from routes.status import _analysis_state, update_status
from routes.events import broadcast
from routes.wiki import clear_cache

logger = logging.getLogger("code-wiki.scan")

_last_push_time = 0.0


def _push_status(**kw):
    global _last_push_time
    # Throttle progress updates to max ~3/sec during scanning/analyzing.
    # Final/error states always go through.
    now = time.time()
    status = kw.get("status", "")
    if status not in ("done", "error", "cancelled", "cancelling") and now - _last_push_time < 0.3:
        return
    _last_push_time = now
    update_status(**kw)
    broadcast("progress", {
        "status": _analysis_state.get("status", "idle"),
        "progress": _analysis_state.get("progress", 0),
        "current_step": _analysis_state.get("current_step", ""),
        "processed_modules": _analysis_state.get("processed_modules", 0),
        "total_modules": _analysis_state.get("total_modules", 0),
        "processed_wiki": _analysis_state.get("processed_wiki", 0),
        "total_wiki": _analysis_state.get("total_wiki", 0),
    })

router = APIRouter()

# Cancel flag for in-flight scans
_scan_cancel_event: asyncio.Event = asyncio.Event()
_scan_task: asyncio.Task | None = None  # Track running scan for immediate cancellation


class ScanRequest(BaseModel):
    mode: str = "full"  # "full" | "partial" | "incremental"
    files: Optional[list[str]] = None


@router.post("/scan")
async def trigger_scan(request: ScanRequest):
    """Trigger code analysis pipeline."""
    repo_path = _config.get("repo_path", "")
    logger.info(f"Scan requested: mode={request.mode}, repo={repo_path or '(empty)'}")
    if not repo_path or not os.path.isdir(repo_path):
        logger.warning(f"Scan rejected: invalid repo_path '{repo_path}'")
        raise HTTPException(status_code=400, detail="无效的仓库路径，请先在设置中配置仓库")

    # Validate config before starting background task
    excludes = _config.get("exclude_patterns", [])
    languages = _config.get("languages", ["python"])

    # Require API key — analysis without LLM produces useless templates
    api_key = _config.get("llm", {}).get("api_key", "")
    if not api_key:
        logger.warning("Scan rejected: no API key configured")
        raise HTTPException(
            status_code=400,
            detail="请先在设置中配置 LLM API Key（DeepSeek），否则无法生成 Wiki 文档",
        )

    try:
        scanner = Scanner(repo_path, user_excludes=excludes, languages=languages)
        # Quick validation: scan for files upfront to give instant feedback.
        # Pass the scanned list to _run_scan to avoid a second traversal.
        pre_scanned = scanner.scan_all()
        if len(pre_scanned) == 0:
            logger.warning(f"Scan rejected: 0 files to analyze (languages={languages})")
            raise HTTPException(status_code=400, detail="未找到可分析的文件（请检查语言配置和排除规则）")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Scanner init failed: {e}")
        raise HTTPException(status_code=400, detail=f"扫描初始化失败: {e}")

    # Clear any previous cancel signal and task reference
    _scan_cancel_event.clear()
    _scan_task = None

    # Use asyncio.create_task instead of BackgroundTasks for proper async execution
    logger.info(f"Scan accepted, launching background task (mode={request.mode})")
    # Pass pre-scanned files to avoid re-scanning
    task = asyncio.create_task(_run_scan(repo_path, request.mode, pre_scanned if request.mode == "full" else (request.files or [])))
    _scan_task = task
    return {"status": "accepted", "mode": request.mode}


@router.post("/scan/cancel")
async def cancel_scan():
    """Cancel the currently running scan."""
    global _scan_task
    _scan_cancel_event.set()
    # Immediately cancel the asyncio task — injects CancelledError into
    # the current HTTP request / sleep, not just rely on flag polling.
    if _scan_task is not None and not _scan_task.done():
        _scan_task.cancel()
        logger.info("Scan task cancelled via asyncio.Task.cancel()")
        _scan_task = None
    update_status(status="cancelling", current_step="正在取消...")
    broadcast("progress", {
        "status": _analysis_state.get("status", "cancelling"),
        "progress": _analysis_state.get("progress", 0),
        "current_step": "正在取消...",
        "processed_modules": _analysis_state.get("processed_modules", 0),
        "total_modules": _analysis_state.get("total_modules", 0),
        "processed_wiki": _analysis_state.get("processed_wiki", 0),
        "total_wiki": _analysis_state.get("total_wiki", 0),
    })
    logger.info("Scan cancel requested")
    return {"status": "cancelling"}


async def _run_scan(repo_path: str, mode: str, files: list[str]):
    """Execute the scan → analyze pipeline."""
    logger.info(f"Scan pipeline started: repo={repo_path}, mode={mode}")
    _push_status(
        status="scanning",
        progress=0,
        current_step="正在扫描文件...",
        started_at=datetime.now().isoformat(),
    )

    try:
        # ---- Step 1: Scan ----
        excludes = _config.get("exclude_patterns", [])
        languages = _config.get("languages", ["python"])
        scanner = Scanner(repo_path, user_excludes=excludes, languages=languages)

        if mode == "full" and files:
            # Full scan with pre-scanned file list from trigger_scan
            py_files = files
            logger.info(f"Using pre-scanned file list ({len(py_files)} files)")
        elif mode == "partial" and files:
            py_files = scanner.scan_partial(files)
        elif mode == "incremental" and files:
            py_files = scanner.scan_partial(files)
            logger.info(f"Incremental scan: {len(py_files)} changed files to re-analyze")
        else:
            py_files = scanner.scan_all()

        logger.info(f"Scan found {len(py_files)} files to analyze")

        _push_status(
            status="analyzing",
            progress=0.2,
            current_step=f"已扫描 {len(py_files)} 个文件，开始分析...",
            total_modules=len(py_files),
        )

        # ---- Step 2: Analyze ----
        if not py_files:
            _push_status(
                status="done",
                progress=1.0,
                current_step=f"没有找到需要分析的文件（已配置语言: {', '.join(languages)}）",
                finished_at=datetime.now().isoformat(),
            )
            return

        analyzer = Analyzer(repo_path)
        modules = {}

        # Parallel analysis using a thread pool (CPU-bound AST parsing)
        loop = asyncio.get_running_loop()
        sem = asyncio.Semaphore(os.cpu_count() or 4)  # Limit concurrent AST parses

        async def _analyze_one(rel_path: str, index: int, total: int):
            """Analyze one file in a thread-pool executor, honouring cancel."""
            if _scan_cancel_event.is_set():
                return rel_path, None
            async with sem:
                if _scan_cancel_event.is_set():
                    return rel_path, None
                try:
                    module = await loop.run_in_executor(None, analyzer.analyze_file, rel_path)
                    return rel_path, module
                except Exception as e:
                    logger.warning(f"Analysis failed for {rel_path}: {e}")
                    return rel_path, None

        batch_size = 50
        for batch_start in range(0, len(py_files), batch_size):
            if _scan_cancel_event.is_set():
                logger.info(f"Scan cancelled during analysis batch starting at {batch_start}")
                _push_status(status="cancelled", progress=1.0, current_step=f"已取消 (分析了 {len(modules)} 个文件)", finished_at=datetime.now().isoformat())
                return

            batch = py_files[batch_start:batch_start + batch_size]
            tasks = [
                _analyze_one(rel_path, batch_start + i, len(py_files))
                for i, rel_path in enumerate(batch)
            ]
            results = await asyncio.gather(*tasks)

            for rel_path, module in results:
                if module is not None:
                    modules[rel_path] = module

            processed = len(modules)
            progress = 0.2 + 0.5 * processed / len(py_files)
            _push_status(
                status="analyzing",
                progress=progress,
                current_step=f"分析中: {processed}/{len(py_files)}",
                processed_modules=processed,
            )

        # ---- Step 3: Build dependency graph ----
        logger.info(f"Building dependency graph from {len(modules)} modules")
        _push_status(
            status="generating",
            progress=0.75,
            current_step="构建依赖图...",
            processed_modules=len(py_files),
        )
        dep_graph = DependencyGraph().build(modules)

        # ---- Step 4: Save analysis results ----
        _save_analysis_results(modules, dep_graph, mode)

        # ---- Step 5: Generate Wiki (LLM) ----
        llm_config = _config.get("llm", {})
        api_key = llm_config.get("api_key", "")

        if api_key:
            wiki_gen = WikiGenerator(
                repo_path=repo_path,
                wiki_path=str(get_wiki_path()),
                api_key=api_key,
                model=llm_config.get("model", "deepseek-v4-flash"),
                base_url=llm_config.get("base_url", "https://api.deepseek.com"),
                temperature=llm_config.get("temperature", 0.3),
            )

            total_mods = len(modules)
            # Clean old .md files once at the start (not during write_all)
            wiki_gen.clean_wiki_dir()
            _push_status(
                status="generating",
                progress=0.80,
                current_step=f"正在生成 Wiki: 0/{total_mods}",
                processed_modules=total_mods,
                total_modules=total_mods,
                processed_wiki=0,
                total_wiki=total_mods,
            )

            wiki_pages = await wiki_gen.generate_all(
                modules,
                dep_graph.stats,
                cancel_check=lambda: _scan_cancel_event.is_set(),
                on_progress=lambda done, total: _push_status(
                    status="cancelling" if _scan_cancel_event.is_set() else "generating",
                    progress=0.80 + 0.18 * done / total,
                    current_step=f"{'正在取消...' if _scan_cancel_event.is_set() else '正在生成 Wiki'}: {done}/{total}",
                    processed_wiki=done,
                    total_wiki=total,
                ),
            )

            # Check cancel after LLM generation
            if _scan_cancel_event.is_set():
                logger.info("Scan cancelled after wiki generation, skipping embed")
                if wiki_pages:
                    wiki_gen.write_all(wiki_pages)
                clear_cache()
                _push_status(status="cancelled", progress=1.0, current_step="已取消", finished_at=datetime.now().isoformat())
                return

            wiki_gen.write_all(wiki_pages)

            # ---- Step 6: Embed Wiki for RAG ----
            if _scan_cancel_event.is_set():
                logger.info("Scan cancelled before embedding")
                _push_status(status="cancelled", progress=1.0, current_step="已取消", finished_at=datetime.now().isoformat())
                return

            _push_status(
                status="generating",
                progress=0.95,
                current_step=f"正在向量化 {len(wiki_pages)} 个 Wiki 页面...",
            )

            embedder = Embedder(
                repo_path=repo_path,
                wiki_path=str(get_wiki_path()),
                api_key=api_key,
                base_url=llm_config.get("base_url", "https://api.deepseek.com"),
            )
            await embedder.rebuild_index(wiki_pages)

        # ---- Step 7: Write state.json ----
        _write_state(modules, dep_graph, mode)

        clear_cache()  # Clear stale wiki cache so new files appear immediately
        broadcast("file-change", {"files": ["wiki"]})

        logger.info(f"Scan pipeline completed: {len(modules)} modules, {dep_graph.stats.get('total_edges', 0)} edges")
        _push_status(
            status="done",
            progress=1.0,
            current_step="分析完成",
            finished_at=datetime.now().isoformat(),
            processed_modules=len(py_files),
        )

    except asyncio.CancelledError:
        logger.info("Scan pipeline cancelled via task cancellation")
        _push_status(
            status="cancelled",
            progress=1.0,
            current_step="已取消",
            finished_at=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.exception(f"Scan pipeline failed: {e}")
        _push_status(
            status="error",
            progress=0,
            current_step="",
            error_message=str(e),
        )
    finally:
        global _scan_task
        if _scan_task is not None:
            _scan_task = None


def _save_analysis_results(
    modules: dict,
    dep_graph: DependencyGraph,
    mode: str,
):
    """Persist analysis output to wiki directory."""
    wiki_dir = get_wiki_path()
    wiki_dir.mkdir(parents=True, exist_ok=True)

    # Save structured analysis data (for later Wiki generation)
    analysis_data = {
        "mode": mode,
        "analyzed_at": datetime.now().isoformat(),
        "modules": {},
        "dependency_graph": {
            "edges": [
                {"source": src, "targets": tgts}
                for src, tgts in dep_graph.get_topology()
            ],
            "stats": dep_graph.stats,
        },
    }

    for path, module in modules.items():
        analysis_data["modules"][path] = _module_to_dict(module)

    # Write to analysis.json
    analysis_path = wiki_dir / "analysis.json"
    with open(analysis_path, "w", encoding="utf-8") as f:
        json.dump(analysis_data, f, indent=2, ensure_ascii=False, default=str)

    # Also save Mermaid diagrams
    mermaid_dir = wiki_dir / "diagrams"
    mermaid_dir.mkdir(exist_ok=True)

    with open(mermaid_dir / "architecture.mmd", "w", encoding="utf-8") as f:
        f.write(dep_graph.to_architecture_mermaid())

    with open(mermaid_dir / "dependencies.mmd", "w", encoding="utf-8") as f:
        f.write(dep_graph.to_mermaid())


def _write_state(
    modules: dict,
    dep_graph: DependencyGraph,
    mode: str,
):
    """Update state.json with analysis metadata."""
    total_classes = sum(len(m.classes) for m in modules.values())
    total_functions = sum(len(m.functions) for m in modules.values())
    total_interfaces = sum(len(getattr(m, 'interfaces', [])) for m in modules.values())
    total_components = sum(len(getattr(m, 'components', [])) for m in modules.values())

    state = {
        "last_analysis": datetime.now().isoformat(),
        "mode": mode,
        "total_modules": len(modules),
        "total_classes": total_classes,
        "total_functions": total_functions,
        "total_interfaces": total_interfaces,
        "total_components": total_components,
        "total_entities": total_classes + total_functions + total_interfaces + total_components,
        "dependency_stats": dep_graph.stats,
    }

    state_path = get_wiki_path() / "state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _module_to_dict(module) -> dict:
    """Serialize a ModuleInfo to dict."""
    result = {
        "path": module.path,
        "language": module.language.value if hasattr(module, 'language') else "python",
        "docstring": module.docstring,
        "total_lines": module.total_lines,
        "imports": module.imports,
        "external_imports": module.external_imports,
        "exports": getattr(module, 'exports', []),
        "classes": [
            {
                "name": c.name,
                "docstring": c.docstring,
                "bases": c.bases,
                "anchor": {"file": c.anchor.file, "line": c.anchor.line}
                if c.anchor
                else None,
                "methods": [
                    {
                        "name": m.name,
                        "signature": m.signature,
                        "docstring": m.docstring,
                        "anchor": {
                            "file": m.anchor.file,
                            "line": m.anchor.line,
                        }
                        if m.anchor
                        else None,
                    }
                    for m in c.methods
                ],
            }
            for c in module.classes
        ],
        "functions": [
            {
                "name": f.name,
                "signature": f.signature,
                "docstring": f.docstring,
                "anchor": {
                    "file": f.anchor.file,
                    "line": f.anchor.line,
                }
                if f.anchor
                else None,
            }
            for f in module.functions
        ],
    }

    # Optional fields (frontend files)
    if hasattr(module, 'interfaces') and module.interfaces:
        result["interfaces"] = [
            {
                "name": i.name,
                "members": i.members,
                "anchor": {"file": i.anchor.file, "line": i.anchor.line}
                if i.anchor else None,
            }
            for i in module.interfaces
        ]
    if hasattr(module, 'components') and module.components:
        result["components"] = [
            {
                "name": c.name,
                "props_type": c.props_type,
                "hooks": c.hooks,
                "anchor": {"file": c.anchor.file, "line": c.anchor.line}
                if c.anchor else None,
            }
            for c in module.components
        ]

    return result
