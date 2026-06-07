# Production PyInstaller spec — builds the standalone `omoikane` onedir binary.
#
# Build:  pyinstaller --clean --noconfirm omoikane.spec
# Output: dist/omoikane/  (onedir: `omoikane` exe + `_internal/`)
#
# onedir (NOT onefile) is mandatory: the orchestrator daemon double-forks and
# lazily imports hermes after the parent exits — onefile's temp extraction is
# deleted on parent exit and would crash the detached daemon. See the freeze
# spike notes. Build from a NON-editable install (CI does `pip install .`) or
# rely on `pathex` so omoikane submodules are visible to the module graph.
import os

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

REPO_ROOT = os.path.abspath(SPECPATH)

datas = []
binaries = []
hiddenimports = []

# Every hermes-agent top-level package (from its dist-info top_level.txt).
# Full bundle by design — maximize the chance everything works frozen.
HERMES_PKGS = [
    "acp_adapter", "agent", "batch_runner", "cli", "cron", "gateway",
    "hermes_bootstrap", "hermes_cli", "hermes_constants", "hermes_logging",
    "hermes_state", "hermes_time", "mcp_serve", "model_tools", "plugins",
    "providers", "run_agent", "tools", "toolset_distributions", "toolsets",
    "trajectory_compressor", "tui_gateway", "utils",
]
for pkg in HERMES_PKGS:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Heavy deps with import-time metadata / native extensions.
for pkg in ["pydantic", "pydantic_core"]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# TUI extra. textual and rich resolve widgets/submodules via importlib at
# runtime, so PyInstaller's static graph misses the package code and only the
# dist-info (from copy_metadata below) lands — `omoikane open` then dies with
# "No module named 'textual'". collect_all pulls the actual package trees.
for pkg in ["textual", "rich", "watchfiles"]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# certifi — the updater's stdlib urllib needs its CA bundle (cacert.pem) for
# HTTPS to GitHub; the OS trust store is not reliably found in a frozen app.
_cd, _cb, _ch = collect_all("certifi")
datas += _cd
binaries += _cb
hiddenimports += _ch

# Our own package + bundled data. pyproject package-data does NOT feed
# PyInstaller — agents_registry resolves omoikane/data at import time.
datas += collect_data_files("omoikane")
hiddenimports += collect_submodules("omoikane")

# Dist metadata for runtime importlib.metadata lookups (entry_points/version()).
for dist in ["hermes-agent", "pydantic", "openai", "fastapi", "uvicorn", "rich", "textual"]:
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass

a = Analysis(
    [os.path.join(REPO_ROOT, "omoikane", "__main__.py")],
    pathex=[REPO_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="omoikane",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="omoikane",
)
