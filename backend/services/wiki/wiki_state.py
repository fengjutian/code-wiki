"""
WikiState — manages state.json persistence with enhanced metadata.

Tracks: repo hash, git commit, durations, token usage, cost, per-module status.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from models.entities import WikiPage

logger = logging.getLogger("code-wiki.wiki_state")


class WikiState:
    """Read/write state.json for a wiki generation run."""

    def __init__(self, wiki_path: str) -> None:
        self._wiki_dir = Path(wiki_path)
        self._state_path = self._wiki_dir / "state.json"
        self._start_time = time.monotonic()
        # Per-run counters
        self.success_modules: List[str] = []
        self.failed_modules: List[str] = []
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0

    # ---- Public API ----

    def load(self) -> dict:
        """Load existing state, or return empty dict."""
        if not self._state_path.exists():
            return {}
        try:
            return json.loads(self._state_path.read_text())
        except (json.JSONDecodeError, IOError) as exc:
            logger.warning("Failed to read state.json: %s", exc)
            return {}

    def save(
        self,
        pages: List[WikiPage],
        mode: str,
        *,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist state.json with metadata about the generation run."""
        existing = self.load()

        elapsed = time.monotonic() - self._start_time

        existing.update(
            {
                "last_wiki_generation": self._now_iso(),
                "wiki_mode": mode,
                "total_pages": len(pages),
                "total_anchors": sum(p.anchors_count for p in pages),
                "llm_model": pages[0].model if pages else "",
                "generation_duration_seconds": round(elapsed, 2),
                "success_modules": len(self.success_modules),
                "failed_modules": len(self.failed_modules),
                "prompt_tokens_est": self.total_prompt_tokens,
                "completion_tokens_est": self.total_completion_tokens,
            }
        )

        if extra:
            existing.update(extra)

        self._wiki_dir.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False)
        )
        logger.debug("state.json saved: %d pages, mode=%s", len(pages), mode)

    def record_success(self, module_path: str) -> None:
        self.success_modules.append(module_path)

    def record_failure(self, module_path: str) -> None:
        self.failed_modules.append(module_path)

    def add_token_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()
