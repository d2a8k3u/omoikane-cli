"""``omoikane init-project`` — create a Project Book from local files.

Reads a free-text brief from one file and acceptance criteria from another
(JSON, YAML, or one-per-line text — the format is sniffed). Calls into the
same :func:`omoikane.tools.handlers.project_start` handler the SDK invokes,
so the on-disk shape matches an agent-driven start byte-for-byte.

For an end-to-end flow that also runs the orchestrator, see
``omoikane start``. ``init-project`` is preserved for headless workflows
(e.g. CI seeding test projects).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List


def add_subparser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--brief", "-b", required=True, type=Path,
        help="Path to a markdown/plain-text file holding the project brief.",
    )
    parser.add_argument(
        "--criteria", "-c", required=True, type=Path,
        help=(
            "Path to acceptance criteria. JSON array, YAML list, or "
            "plain text (one criterion per line; blank/`#` lines ignored)."
        ),
    )
    parser.add_argument(
        "--starting-state", default="scratch",
        choices=["scratch", "existing"],
        help="Starting state hint passed into the Book (default: scratch).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit the raw project_start JSON response instead of the human summary.",
    )


def _load_criteria(path: Path) -> List[str]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        raise SystemExit(f"acceptance criteria file is empty: {path}")

    # JSON array (most explicit).
    if stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"failed to parse {path} as JSON: {exc}")
        if not isinstance(data, list):
            raise SystemExit(f"{path}: JSON root must be an array of strings.")
        return [str(item).strip() for item in data if str(item).strip()]

    # YAML list — handled only if PyYAML is available; otherwise fall back to
    # plain-text mode (which still works for ``- item`` lines).
    if stripped.startswith("- ") or path.suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(stripped)
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
        except ModuleNotFoundError:
            pass  # fall through to plain-text parsing below

    # Plain text — one criterion per non-comment, non-blank line. Strip a
    # leading "- " bullet so YAML-flavoured files still work without PyYAML.
    out: List[str] = []
    for raw in stripped.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        if line:
            out.append(line)
    if not out:
        raise SystemExit(f"no acceptance criteria parsed from {path}")
    return out


def run(args: argparse.Namespace) -> int:
    brief_path: Path = args.brief
    criteria_path: Path = args.criteria

    if not brief_path.is_file():
        print(f"brief file not found: {brief_path}", file=sys.stderr)
        return 1
    if not criteria_path.is_file():
        print(f"criteria file not found: {criteria_path}", file=sys.stderr)
        return 1

    brief = brief_path.read_text(encoding="utf-8").strip()
    if not brief:
        print(f"brief file is empty: {brief_path}", file=sys.stderr)
        return 1

    criteria = _load_criteria(criteria_path)

    from omoikane.tools.handlers import project_start

    payload = project_start({
        "brief": brief,
        "acceptance_criteria": criteria,
        "starting_state": args.starting_state,
    })

    response = json.loads(payload)

    if response.get("error"):
        print(f"project_start failed: {response['error']}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(response, indent=2))
    else:
        pid = response.get("project_id", "?")
        print(f"Project created: {pid}")
        print(f"  status: {response.get('status')}")
        print(f"  phase:  {response.get('phase')}")
        print(f"  criteria: {len(criteria)}")
        message = response.get("message")
        if message:
            print(message)
    return 0
