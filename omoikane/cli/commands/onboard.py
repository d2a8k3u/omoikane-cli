"""``omoikane onboard`` — interactive first-run setup.

Collects an API key, provider/model, notification backend, and (optionally) the
supervisor schedule, then writes ``~/.omoikane/config.toml``. Runs automatically
on first install (from ``install.sh``), after ``self-update`` when no config
exists, and on a normal CLI run when no config exists.

Prompts are read from ``/dev/tty`` when stdin is not a terminal, so the flow
works even under ``curl | bash`` (where stdin is the install pipe). Secrets are
masked via ``getpass`` on a real terminal. In a truly non-interactive context
(CI, no controlling terminal) it prints guidance and exits 0 without writing.

Dismissing the wizard with Ctrl-C writes a skip sentinel so the gate does not
re-prompt on every later command. Re-running reformats ``config.toml`` and does
not preserve hand-added comments (see :mod:`omoikane.config.toml_writer`).
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from omoikane.config import settings, toml_writer

_VALID_BACKENDS = ("stdout", "telegram", "slack")
_DEFAULT_SCHEDULE = "*/5 * * * *"
_DEFAULT_MODEL = "openrouter/owl-alpha"
_DEFAULT_PROVIDER = "openrouter"
_SECRET_MASK = "********"


def add_subparser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--reconfigure", "--force", action="store_true", dest="reconfigure",
        help="Re-run onboarding even if config.toml already exists.",
    )
    parser.add_argument(
        "--no-supervisor", action="store_true",
        help="Skip installing the supervisor health-check schedule.",
    )


# --------------------------------------------------------------------------
# I/O helpers
# --------------------------------------------------------------------------
def _open_tty():
    """Return a readable stream for prompts, or ``None`` if non-interactive."""
    if sys.stdin.isatty():
        return sys.stdin
    try:
        return open("/dev/tty", "r", encoding="utf-8")  # noqa: SIM115
    except OSError:
        return None


def _is_tty(stream) -> bool:
    return hasattr(stream, "isatty") and stream.isatty()


def _echo(text: str) -> None:
    """Write an informational line to stderr (keeps stdout clean for piping)."""
    sys.stderr.write(text + "\n")


def _prompt(
    stream,
    label: str,
    default: Optional[str] = None,
    *,
    default_display: Optional[str] = None,
    secret: bool = False,
) -> str:
    """Show ``label`` and read one line. Blank input returns ``default``.

    ``default_display`` overrides what is shown in the ``[...]`` hint (used to
    mask stored secrets). ``secret=True`` reads without echo on a real tty.
    """
    shown = default_display if default_display is not None else default
    suffix = f" [{shown}]" if shown else ""
    prompt_str = f"{label}{suffix}: "

    if secret and _is_tty(stream):
        import getpass

        try:
            line = getpass.getpass(prompt_str)
        except EOFError:
            return default or ""
        value = line.strip()
        return value or (default or "")

    sys.stderr.write(prompt_str)
    sys.stderr.flush()
    line = stream.readline()
    if not line:  # EOF
        return default or ""
    value = line.strip()
    return value or (default or "")


def _prompt_yes_no(stream, label: str, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    answer = _prompt(stream, f"{label} [{hint}]", default=None).strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def _parse_backends(raw: str) -> list:
    """Parse a comma list, warning on unrecognized names (instead of silently
    dropping them to stdout)."""
    tokens = [b.strip().lower() for b in raw.split(",") if b.strip()]
    valid = [b for b in tokens if b in _VALID_BACKENDS]
    unknown = [b for b in tokens if b not in _VALID_BACKENDS]
    if unknown:
        _echo(
            f"  ! ignored unknown backend(s): {', '.join(unknown)} "
            f"(valid: {', '.join(_VALID_BACKENDS)})"
        )
    return valid or ["stdout"]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def run(args: argparse.Namespace) -> int:
    if settings.config_exists() and not args.reconfigure:
        from omoikane.config import paths

        print(
            f"Already configured ({paths.config_file()}). "
            "Re-run with `omoikane onboard --reconfigure` to change settings."
        )
        return 0

    stream = _open_tty()
    if stream is None:
        _echo(
            "onboard: no interactive terminal; skipping setup. "
            "Run `omoikane onboard` in a terminal to configure."
        )
        return 0

    try:
        return _run_interactive(stream, args)
    except KeyboardInterrupt:
        _remember_skip("\nSetup skipped.")
        return 0
    finally:
        if stream is not sys.stdin:
            stream.close()


def _remember_skip(reason: str) -> None:
    """Any non-writing dismissal (Ctrl-C, or declining the final confirm) drops a
    sentinel so the auto-gate stops re-prompting on every subsequent command.

    Harmless for an explicit ``omoikane onboard`` — ``run`` ignores the sentinel
    when invoked directly; it only suppresses the first-run auto-trigger.
    """
    _echo(reason)
    _echo(
        "Run `omoikane onboard` anytime to finish setup, "
        "or set OMOIKANE_NO_ONBOARD=1 to silence this."
    )
    try:
        from omoikane.config import paths

        paths.ensure_home()
        paths.onboard_skip_file().write_text("skipped\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 - best effort
        pass


def _run_interactive(stream, args: argparse.Namespace) -> int:
    existing = settings.load_config()
    auth = existing.get("auth", {}) or {}
    model = existing.get("model", {}) or {}
    transport = existing.get("transport", {}) or {}
    gate_triggered = bool(getattr(args, "gate_triggered", False))

    from omoikane.config import paths

    _echo("")
    _echo("Omoikane setup — configure credentials and notifications.")
    _echo(f"Saved to {paths.config_file()} (chmod 600). Press Enter to accept [defaults].")
    _echo("")

    api_key = _ask_api_key(stream, auth)
    provider, model_id = _ask_model(stream, model)
    backends, tg, slack = _ask_notifications(stream, transport)
    install_supervisor, schedule = _ask_supervisor(stream, args, existing, gate_triggered)

    config = _assemble(existing, auth, model, transport, api_key, provider, model_id,
                       backends, tg, slack, install_supervisor, schedule)

    # --- summary + confirm -------------------------------------------------
    _print_summary(config, install_supervisor, schedule)
    if not _prompt_yes_no(stream, "Write this configuration?", default=True):
        _remember_skip("Aborted; nothing written.")
        return 0

    path = toml_writer.write_config(config)
    # A completed setup supersedes any earlier skip.
    try:
        paths.onboard_skip_file().unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    print(f"Wrote {path}")

    if install_supervisor:
        _install_supervisor(schedule)
    elif args.reconfigure and (existing.get("supervisor") or {}).get("schedule"):
        _uninstall_supervisor()

    _warn_if_no_key(config)
    _echo("")
    _echo("Next: create a brief, then run")
    _echo("  omoikane start -b brief.md -c criteria.txt")
    return 0


# --------------------------------------------------------------------------
# Prompt sections
# --------------------------------------------------------------------------
def _ask_api_key(stream, auth: dict) -> str:
    existing_key = str(auth.get("api_key") or "")
    if existing_key:
        return _prompt(
            stream, "API key",
            default=existing_key, default_display="keep current", secret=True,
        )
    _echo("API key — from your provider (e.g. OpenRouter or Anthropic).")
    _echo("  Leave blank to read it from $OMOIKANE_API_KEY / $OPENROUTER_API_KEY /")
    _echo("  $ANTHROPIC_API_KEY at runtime, or enter 'env:MY_VAR' to point at a")
    _echo("  variable. A literal key is stored as plaintext in config.toml (chmod 600).")
    return _prompt(stream, "API key", default="", secret=True)


def _ask_model(stream, model: dict) -> tuple:
    provider = _prompt(
        stream, "Provider (e.g. openrouter, anthropic)",
        default=str(model.get("provider") or _DEFAULT_PROVIDER),
    )
    model_id = _prompt(
        stream, "Model id (e.g. openrouter/owl-alpha)",
        default=str(model.get("id") or _DEFAULT_MODEL),
    )
    return provider, model_id


def _ask_notifications(stream, transport: dict) -> tuple:
    _echo("")
    _echo("Where should approval requests and completion alerts go?")
    _echo("  stdout = print to the terminal · telegram · slack (comma-separate to combine)")
    prev_backends = ", ".join(transport.get("backends") or ["stdout"])
    backends = _parse_backends(
        _prompt(stream, "Notification backends", default=prev_backends)
    )

    tg: dict = {}
    if "telegram" in backends:
        prev_tg = transport.get("telegram", {}) or {}
        token = _prompt(
            stream, "Telegram bot token (or 'env:TELEGRAM_BOT_TOKEN')",
            default=str(prev_tg.get("bot_token") or "env:TELEGRAM_BOT_TOKEN"),
            default_display=_mask(prev_tg.get("bot_token")),
        )
        chat = _prompt(
            stream, "Telegram chat id (the numeric id of your chat/channel)",
            default=str(prev_tg.get("chat_id") or ""),
        )
        if not _effective(token) or not chat.strip():
            _echo("  ! telegram needs both a bot token and a chat id; "
                  "dropping it. Re-run `omoikane onboard --reconfigure` to add it.")
            backends = [b for b in backends if b != "telegram"]
        else:
            tg = {"bot_token": token, "chat_id": chat}

    slack: dict = {}
    if "slack" in backends:
        prev_sl = transport.get("slack", {}) or {}
        webhook = _prompt(
            stream, "Slack webhook URL (or 'env:SLACK_WEBHOOK_URL')",
            default=str(prev_sl.get("webhook_url") or "env:SLACK_WEBHOOK_URL"),
            default_display=_mask(prev_sl.get("webhook_url")),
        )
        if not _effective(webhook):
            _echo("  ! slack needs a webhook URL; dropping it.")
            backends = [b for b in backends if b != "slack"]
        else:
            slack = {"webhook_url": webhook}

    if not backends:
        backends = ["stdout"]
    return backends, tg, slack


def _ask_supervisor(stream, args, existing: dict, gate_triggered: bool) -> tuple:
    if args.no_supervisor:
        return False, _DEFAULT_SCHEDULE
    _echo("")
    _echo("The supervisor is a background health-check that restarts stalled")
    _echo("agents on a schedule (installs a launchd/systemd/cron job).")
    # When onboarding was forced by the gate (user just ran some other command),
    # default to NO so we never install a background job from a passive Enter.
    default_yes = not gate_triggered
    if not _prompt_yes_no(stream, "Install the supervisor health-check?", default=default_yes):
        return False, _DEFAULT_SCHEDULE
    prev_sched = (existing.get("supervisor", {}) or {}).get("schedule")
    schedule = _prompt(
        stream, "Schedule (cron syntax; '*/5 * * * *' = every 5 minutes)",
        default=str(prev_sched or _DEFAULT_SCHEDULE),
    )
    return True, schedule


# --------------------------------------------------------------------------
# Assembly + reporting
# --------------------------------------------------------------------------
def _assemble(existing, auth, model, transport, api_key, provider, model_id,
              backends, tg, slack, install_supervisor, schedule) -> dict:
    config = dict(existing)

    if api_key:
        config.setdefault("auth", dict(auth))["api_key"] = api_key

    model_section = dict(model)
    model_section["provider"] = provider
    model_section["id"] = model_id
    config["model"] = model_section

    transport_section = dict(transport)
    transport_section["backends"] = backends
    # Drop stale subtables when a backend is deselected so config matches reality.
    if "telegram" in backends and tg:
        transport_section["telegram"] = tg
    else:
        transport_section.pop("telegram", None)
    if "slack" in backends and slack:
        transport_section["slack"] = slack
    else:
        transport_section.pop("slack", None)
    config["transport"] = transport_section

    if install_supervisor:
        config.setdefault("supervisor", {})["schedule"] = schedule
    else:
        config.pop("supervisor", None)  # don't leave a stale schedule we ignore

    return config


def _print_summary(config: dict, install_supervisor: bool, schedule: str) -> None:
    auth = config.get("auth", {}) or {}
    model = config.get("model", {}) or {}
    transport = config.get("transport", {}) or {}
    _echo("")
    _echo("Summary:")
    _echo(f"  api key      : {_describe_key(auth.get('api_key'))}")
    _echo(f"  provider     : {model.get('provider')}")
    _echo(f"  model        : {model.get('id')}")
    _echo(f"  notifications: {', '.join(transport.get('backends') or ['stdout'])}")
    _echo(f"  supervisor   : {('yes (' + schedule + ')') if install_supervisor else 'no'}")
    _echo("")


def _warn_if_no_key(config: dict) -> None:
    if settings.resolve_api_key(config):
        # If a literal key is an env:VAR that is unset, surface it now.
        raw = str((config.get("auth", {}) or {}).get("api_key") or "")
        if raw.startswith("env:") and not os.environ.get(raw[4:]):
            _echo(f"  Note: ${raw[4:]} is not set yet — export it before `omoikane start`.")
        return
    _echo(
        "  Note: no API key configured. Set one (env var, or "
        "`omoikane onboard --reconfigure`) before `omoikane start`."
    )


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------
def _effective(value: str) -> str:
    """Resolve env: indirection to test whether a value is actually present."""
    return settings._resolve_env(str(value or "")).strip()


def _mask(value) -> Optional[str]:
    text = str(value or "")
    if not text:
        return None
    if text.startswith("env:"):
        return text  # not a secret — it's a variable name
    return _SECRET_MASK


def _describe_key(value) -> str:
    text = str(value or "")
    if not text:
        return "(from environment)"
    if text.startswith("env:"):
        return text
    return _SECRET_MASK


# --------------------------------------------------------------------------
# Supervisor side effects
# --------------------------------------------------------------------------
def _install_supervisor(schedule: str) -> None:
    from omoikane.config import paths
    from omoikane.supervisor import install as _install

    try:
        result = _install.install(schedule=schedule, log_dir=paths.logs_dir(), backend=None)
        print(f"[{result.backend}] supervisor installed.")
    except Exception as exc:  # noqa: BLE001 - never fail onboarding on this
        _echo(
            f"supervisor install failed ({type(exc).__name__}: {exc}); "
            "run `omoikane supervisor install` later."
        )


def _uninstall_supervisor() -> None:
    from omoikane.supervisor import install as _install

    try:
        result = _install.uninstall()
        print(f"[{result.backend}] supervisor uninstalled.")
    except Exception as exc:  # noqa: BLE001
        _echo(
            f"supervisor uninstall failed ({type(exc).__name__}: {exc}); "
            "run `omoikane supervisor uninstall` later."
        )
