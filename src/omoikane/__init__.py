"""Omoikane — standalone CLI/TUI orchestrator on hermes-agent SDK.

Public re-exports keep the top-level import shallow. The Phase 2 tool
registration (``register_book_tools``) is not invoked at import time during
Phase 1 because the SDK is an optional extra; callers that want SDK
integration must ``from omoikane.tools import register_book_tools`` and
invoke it before constructing an ``AIAgent``.
"""
from omoikane._version import __version__

__all__ = ["__version__"]
