"""Tiered, per-document memory.

Three tiers (build plan Phase 7):
  * session scratchpad — current task state, keyed by session id,
  * design-intent store — what the user is trying to achieve, persisted with
    the document,
  * project facts — units / standards / fit conventions.

Memory is scoped per document and never silently leaks across unrelated models.
Persistence is a small JSON sidecar so intent survives a harness restart.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from orion_agent.shared.config import get_config


@dataclass
class DocumentMemory:
    document: str = ""
    design_intent: list[str] = field(default_factory=list)
    project_facts: dict[str, str] = field(default_factory=dict)
    recent: list[dict] = field(default_factory=list)   # rolling task scratchpad
    updated_at: float = field(default_factory=time.time)

    def summary(self, max_intent: int = 5, max_recent: int = 4) -> str:
        parts = []
        if self.project_facts:
            facts = ", ".join(f"{k}={v}" for k, v in self.project_facts.items())
            parts.append(f"Project conventions: {facts}")
        if self.design_intent:
            intents = "; ".join(self.design_intent[-max_intent:])
            parts.append(f"Stated design intent: {intents}")
        if self.recent:
            last = "; ".join(r["request"][:80] for r in self.recent[-max_recent:])
            parts.append(f"Recent in this session: {last}")
        return "\n".join(parts)


class MemoryStore:
    def __init__(self, root: Optional[str] = None):
        cfg = get_config()
        self.root = root or os.path.join(cfg.repo_root, cfg.trajectory_dir, "memory")
        os.makedirs(self.root, exist_ok=True)
        self._cache: dict[str, DocumentMemory] = {}

    # ------------------------------------------------------------------ #
    def get(self, document: str) -> DocumentMemory:
        if not document:
            return DocumentMemory()
        if document in self._cache:
            return self._cache[document]
        path = self._path(document)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    mem = DocumentMemory(**json.load(fh))
            except Exception:  # noqa: BLE001
                mem = DocumentMemory(document=document)
        else:
            mem = DocumentMemory(document=document)
        self._cache[document] = mem
        return mem

    def observe(self, session_id: str, document: str, message: str, result) -> None:
        """Record a turn into memory (intent capture is deliberately light)."""
        mem = self.get(document)
        mem.recent.append({"session": session_id, "request": message,
                           "pillar": getattr(result, "pillar", ""), "ts": time.time()})
        mem.recent = mem.recent[-20:]
        intent = self._extract_intent(message, getattr(result, "pillar", ""))
        if intent and intent not in mem.design_intent:
            mem.design_intent.append(intent)
            mem.design_intent = mem.design_intent[-20:]
        mem.updated_at = time.time()
        self._persist(mem)

    def set_fact(self, document: str, key: str, value: str) -> None:
        mem = self.get(document)
        mem.project_facts[key] = value
        self._persist(mem)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_intent(message: str, pillar: str) -> Optional[str]:
        # Persist intent only for edits/builds, where "what we're trying to do"
        # matters across turns; questions are transient.
        if pillar in ("modify", "reconstruct", "generate"):
            return message[:140]
        return None

    def _path(self, document: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in document)
        return os.path.join(self.root, f"{safe or 'untitled'}.json")

    def _persist(self, mem: DocumentMemory) -> None:
        try:
            with open(self._path(mem.document), "w", encoding="utf-8") as fh:
                json.dump(asdict(mem), fh, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass
