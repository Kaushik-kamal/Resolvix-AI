"""Versioned, atomically swapped knowledge-base store with previous-version retention."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from resolvix_contracts.models import KBSource, KBVersionInfo

from ..embeddings import Embedder
from ..faq import FaqIndex
from ..settings import PROMPTS_DIR, BrainSettings
from .compiler import CompiledKB, KBCompileError, compile_entries
from .loader import load_entries_async

log = logging.getLogger("resolvix_brain.kb")
RETAIN_VERSIONS = 3


@dataclass
class KBVersion:
    kb: CompiledKB
    faq: FaqIndex


class KBStore:
    def __init__(self, settings: BrainSettings, directory, embedder: Embedder):
        self.settings = settings
        self.directory = directory
        self.embedder = embedder
        self._active: KBVersion | None = None
        self._versions: dict[str, KBVersion] = {}
        self._order: list[str] = []
        self._lock = asyncio.Lock()
        self.last_warmup: dict | None = None
        self.last_source: KBSource | None = None     # the source of the active version (used for the daily refresh)

    @property
    def active(self) -> KBVersion | None:
        return self._active

    def get(self, kb_version: str | None) -> KBVersion | None:
        """The pinned version if still retained, else the active one."""
        if kb_version and kb_version in self._versions:
            return self._versions[kb_version]
        return self._active

    async def reload(self, source: KBSource, *, in_use: set[str] | None = None, warmup=None) -> KBVersionInfo:
        """Compile and atomically activate. On any failure the old version stays active (KBCompileError)."""
        async with self._lock:
            try:
                entries = await load_entries_async(source, service_key=self.settings.kb_export_service_key or None)
                persona = (PROMPTS_DIR / "persona.md").read_text(encoding="utf-8")
                compiled = await asyncio.to_thread(
                    compile_entries, entries, today=self.settings.today(), persona=persona, directory=self.directory,
                    budget=self.settings.kb_token_budget, index_all=self.settings.faq_index_all)
                faq = await asyncio.to_thread(FaqIndex.build, compiled.faq_items, self.embedder)
            except KBCompileError:
                raise
            except Exception as exc:  # defensive: anything unexpected must not clear the active KB
                raise KBCompileError([f"{type(exc).__name__}: {exc}"]) from exc
            info = compiled.info
            if self.embedder.degraded:
                info = info.model_copy(update={"warnings": [*info.warnings, "degraded embedder in use (lexical)"]})
                compiled.info = info
            ver = KBVersion(compiled, faq)
            if compiled.kb_version not in self._versions:
                self._order.append(compiled.kb_version)
            self._versions[compiled.kb_version] = ver
            self._active = ver                       # the atomic swap: one reference assignment
            self.last_source = source
            self._prune(in_use or set())
            log.info("kb activated version=%s entries=%d tokens=%d", compiled.kb_version, info.entry_count, info.token_count)
        if warmup is not None and self.settings.warmup_on_reload:
            try:
                self.last_warmup = await warmup(compiled.prefix)
            except Exception as exc:  # warm-up is best effort
                self.last_warmup = {"error": f"{type(exc).__name__}: {exc}"}
                info = info.model_copy(update={"warnings": [*info.warnings, f"warm-up failed: {type(exc).__name__}"]})
                compiled.info = info
        return info

    def _prune(self, in_use: set[str]) -> None:
        keep = set(self._order[-RETAIN_VERSIONS:]) | in_use
        if self._active:
            keep.add(self._active.kb.kb_version)
        for v in list(self._order):
            if v not in keep:
                self._order.remove(v)
                self._versions.pop(v, None)
