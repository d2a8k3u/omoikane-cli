# Contributing to omoikane-cli

Thanks for your interest in contributing. This guide covers the development
setup, conventions, and the release flow.

## Development setup

```sh
git clone https://github.com/d2a8k3u/omoikane-cli.git
cd omoikane-cli
python3.11 -m venv .venv
.venv/bin/pip install -e ".[all]"     # runtime + tui + transport + dev
```

Requires Python 3.11+. The distribution is `omoikane-cli`; the import package
and the installed command both stay `omoikane`.

The optional extras are intentionally narrow — a core-only change (the Book
layer) does not need the SDK, textual, or httpx:

| Extra | Needed for |
|-------|------------|
| `runtime` | running the CTO (`hermes-agent` SDK, pinned to a commit) |
| `tui` | `omoikane open` (textual, watchfiles, rich) |
| `transport` | Telegram / Slack push (httpx) |
| `dev` | pytest, pytest-cov |

## Project layout

```
omoikane/        the package (cli, core, runtime, orchestrator, supervisor, tools, transport, tui, config, data)
tests/           pytest suite
docs/            MkDocs site (published to GitHub Pages)
examples/        generated showcase projects
omoikane.spec    PyInstaller spec for the standalone binary
```

## Tests

Every change must keep the suite green:

```sh
.venv/bin/python -m pytest -q
```

Add or update tests alongside the change. Tests isolate state via the
`temp_omoikane_home` fixture (a temporary `OMOIKANE_HOME`) — never write to a
real home directory in a test.

## Code conventions

- Match the surrounding style; prefer the smallest change that solves the problem.
- Validate at boundaries, handle errors explicitly, no silent `except: pass`
  outside the few documented best-effort callbacks.
- No comments that restate the code; explain *why*, not *what*.
- Keep public behaviour covered by tests.

## Commits & pull requests

- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`,
  `fix:`, `docs:`, `test:`, `build:`, `ci:`, `refactor:`, `chore:`
  (optionally scoped, e.g. `fix(orchestrator): …`).
- Keep each commit a single coherent change; split unrelated work.
- Branch off `main`, ensure `pytest -q` passes, and open a PR describing the
  change and how you verified it.

## hermes-agent dependency

The `runtime` extra pins `hermes-agent` to a specific commit in
`pyproject.toml` for reproducible binary builds. Bumping it is a deliberate
change: update the pin, then re-validate that the PyInstaller binary still
loads the SDK (`omoikane --self-test`) before merging.

## Building the binary

```sh
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller --clean --noconfirm omoikane.spec
./dist/omoikane/omoikane --version
./dist/omoikane/omoikane --self-test     # confirms the bundled SDK loads
```

Releases are cut by tagging `vX.Y.Z` (version comes from
`omoikane/_version.py`); the `release` workflow builds the macOS arm64 and
Linux x86_64 binaries and attaches them to the GitHub Release. Tags in the
`0.x` series (and any `rc`/`beta`/`alpha` tag) are published as prereleases.

## Docs

```sh
.venv/bin/pip install mkdocs-material
.venv/bin/mkdocs serve        # preview at http://127.0.0.1:8000
```

Docs under `docs/` deploy to GitHub Pages on push to `main`.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
