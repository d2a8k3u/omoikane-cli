# Install

## Quick install (recommended)

```sh
curl -fsSL https://d2a8k3u.github.io/omoikane-cli/install.sh | sh
```

This downloads the prebuilt binary, installs it under `~/.omoikane/`, and points
`~/.omoikane/bin/omoikane` at it. Re-running the script upgrades in place.

Supported platforms: **macOS (Apple Silicon, arm64)** and **Linux (x86_64)**.

### Add to your PATH

The installer prints the exact line if needed:

```sh
export PATH="$HOME/.omoikane/bin:$PATH"
```

Add it to `~/.zshrc` or `~/.bashrc` to make it permanent, then restart your shell.

### macOS Gatekeeper

The binary is unsigned. The installer clears the quarantine attribute
automatically. If you download manually instead, run:

```sh
xattr -dr com.apple.quarantine ~/.omoikane/versions/<version>/omoikane
```

## Verify

```sh
omoikane --version
omoikane --help
```

## Updating

```sh
omoikane self-update            # upgrade to the latest release
omoikane self-update --check    # report only, don't install
```

A frozen binary also prints a one-line "new version available" notice (at most
once a day, only on an interactive terminal). Disable it with:

```sh
export OMOIKANE_NO_UPDATE_CHECK=1
```

## From source (developers)

```sh
git clone https://github.com/d2a8k3u/omoikane-cli
cd omoikane-cli
pip install -e ".[all]"
```

A pip/source install is managed by pip — `self-update` will tell you to use
`pip install -U` instead.

## Uninstall

```sh
rm -rf ~/.omoikane          # removes the binary AND all project data
```

To keep your projects, remove only `~/.omoikane/bin` and `~/.omoikane/versions`.
