"""Resolvix Brain: grounded, safe, multilingual decision engine (Member B).

    from resolvix_brain import create_brain, BrainSettings
    brain = create_brain(BrainSettings.from_env())   # satisfies resolvix_contracts.Brain
"""
from __future__ import annotations

from .brain import ResolvixBrain
from .kb.compiler import KBCompileError
from .settings import BrainSettings

__version__ = "1.0.0"
__all__ = ["create_brain", "BrainSettings", "ResolvixBrain", "KBCompileError"]


def create_brain(settings: BrainSettings | None = None) -> ResolvixBrain:
    """Factory used by Member A. Cheap: models and the KB load lazily on ``start_call`` (or ``await brain.ready()``)."""
    return ResolvixBrain(settings or BrainSettings.from_env())
