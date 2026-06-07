# Quickstart

## 1. Set credentials

omoikane reads the LLM API key from the environment (first match wins):

```sh
export OMOIKANE_API_KEY=...        # or OPENROUTER_API_KEY / ANTHROPIC_API_KEY
export OMOIKANE_MODEL=...          # optional; defaults to a built-in model
export OMOIKANE_PROVIDER=...       # optional; e.g. openrouter
```

## 2. Describe the project

Write a brief and acceptance criteria:

```sh
cat > brief.md <<'EOF'
Build a small CLI that converts Markdown files to HTML.
EOF

cat > criteria.json <<'EOF'
["converts a .md file to .html", "has a --help flag", "has tests"]
EOF
```

The criteria file accepts a JSON array, a YAML list, or one item per line.

## 3. Start the team

```sh
omoikane start -b brief.md -c criteria.json --detach
```

- `--detach` runs the CTO as a background daemon (default for unattended runs).
- `--foreground` runs it attached to your terminal.
- `--no-run` just creates the project on disk without starting the CTO.

## 4. Watch and steer

```sh
omoikane list                     # all projects + health
omoikane status <project-id>      # phase + criteria summary
omoikane open <project-id>        # live TUI
omoikane inject <project-id> "focus on tests first"
omoikane approvals list           # review gated actions
```

## 5. Keep it healthy

Install the supervisor so stalled/crashed runs are respawned automatically:

```sh
omoikane supervisor install
omoikane supervisor status
```

See [Commands](commands.md) for the full surface and [Configuration](configuration.md)
for `config.toml` and environment variables.
