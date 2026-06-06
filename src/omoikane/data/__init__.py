"""Package-data anchor for ``importlib.resources`` lookups.

This module exists only so that ``importlib.resources.files("omoikane.data")``
resolves cleanly. Do not put logic here — the directory is reserved for
bundled SKILL.md briefs and other static assets shipped with the wheel.
"""
