#!/bin/sh
# omoikane-cli installer — downloads the prebuilt binary into ~/.omoikane and
# points ~/.omoikane/bin/omoikane at it. Idempotent: re-run to upgrade.
#
#   curl -fsSL https://d2a8k3u.github.io/omoikane-cli/install.sh | sh
#
# Layout it creates:
#   ~/.omoikane/versions/<version>/omoikane/   (onedir payload)
#   ~/.omoikane/bin/omoikane                    (symlink -> current version exe)
set -eu

# Overridable for offline testing: OMOIKANE_REPO, OMOIKANE_INSTALL_TAG,
# OMOIKANE_INSTALL_BASE (asset download base URL, e.g. file:///path).
REPO="${OMOIKANE_REPO:-d2a8k3u/omoikane-cli}"
HOME_DIR="${OMOIKANE_HOME:-$HOME/.omoikane}"
BIN_DIR="$HOME_DIR/bin"
VERSIONS_DIR="$HOME_DIR/versions"

err() { printf 'error: %s\n' "$1" >&2; exit 1; }
info() { printf '%s\n' "$1" >&2; }

# --- detect platform -> asset name -------------------------------------------
os="$(uname -s)"
arch="$(uname -m)"
case "$os" in
  Darwin)
    case "$arch" in
      arm64|aarch64) asset="omoikane-macos-arm64.tar.gz" ;;
      *) err "unsupported macOS arch '$arch' (only Apple Silicon arm64 is built)" ;;
    esac ;;
  Linux)
    case "$arch" in
      x86_64|amd64) asset="omoikane-linux-x86_64.tar.gz" ;;
      *) err "unsupported Linux arch '$arch' (only x86_64 is built)" ;;
    esac ;;
  *) err "unsupported OS '$os' (only macOS and Linux are supported)" ;;
esac

# --- tools -------------------------------------------------------------------
if command -v curl >/dev/null 2>&1; then
  dl() { curl -fsSL "$1" -o "$2"; }
  fetch() { curl -fsSL "$1"; }
elif command -v wget >/dev/null 2>&1; then
  dl() { wget -qO "$2" "$1"; }
  fetch() { wget -qO- "$1"; }
else
  err "need curl or wget"
fi

if command -v sha256sum >/dev/null 2>&1; then
  sha_of() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
  sha_of() { shasum -a 256 "$1" | awk '{print $1}'; }
else
  sha_of() { echo ""; }  # no tool -> skip verification
fi

# --- resolve latest tag ------------------------------------------------------
if [ -n "${OMOIKANE_INSTALL_TAG:-}" ]; then
  tag="$OMOIKANE_INSTALL_TAG"
else
  info "Resolving latest release of $REPO ..."
  _extract_tag() { grep '"tag_name"' | head -1 | sed -E 's/.*"tag_name" *: *"([^"]+)".*/\1/'; }
  # Prefer the latest stable release; fall back to the newest release (which may
  # be a prerelease) — /releases/latest 404s when only prereleases exist.
  tag="$(fetch "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null | _extract_tag)"
  [ -n "$tag" ] || tag="$(fetch "https://api.github.com/repos/$REPO/releases" 2>/dev/null | _extract_tag)"
fi
[ -n "$tag" ] || err "could not determine latest release tag"
version="${tag#v}"
info "Latest: $tag"

base="${OMOIKANE_INSTALL_BASE:-https://github.com/$REPO/releases/download/$tag}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# --- download + verify -------------------------------------------------------
info "Downloading $asset ..."
dl "$base/$asset" "$tmp/$asset"
if dl "$base/$asset.sha256" "$tmp/$asset.sha256" 2>/dev/null; then
  expected="$(awk '{print $1}' "$tmp/$asset.sha256")"
  actual="$(sha_of "$tmp/$asset")"
  if [ -n "$actual" ] && [ -n "$expected" ] && [ "$expected" != "$actual" ]; then
    err "checksum mismatch (expected $expected, got $actual)"
  fi
else
  info "warning: no .sha256 sidecar; skipping integrity check"
fi

# --- install (extract -> flip symlink) ---------------------------------------
dest="$VERSIONS_DIR/$version"
mkdir -p "$dest" "$BIN_DIR"
rm -rf "${dest:?}/omoikane"
tar -xzf "$tmp/$asset" -C "$dest"          # tarball root is `omoikane/`
exe="$dest/omoikane/omoikane"
[ -f "$exe" ] || err "extracted payload missing $exe"
chmod +x "$exe"

if [ "$os" = "Darwin" ]; then
  xattr -dr com.apple.quarantine "$dest/omoikane" 2>/dev/null || true
fi

ln -sfn "$exe" "$BIN_DIR/omoikane"
info "Installed omoikane $version -> $BIN_DIR/omoikane"

# --- PATH hint ---------------------------------------------------------------
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    info ""
    info "Add omoikane to your PATH:"
    info "    export PATH=\"$BIN_DIR:\$PATH\""
    case "${SHELL:-}" in
      *zsh) info "  e.g. echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.zshrc" ;;
      *bash) info "  e.g. echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.bashrc" ;;
    esac ;;
esac

"$exe" --version

# --- first-run onboarding (interactive only) ---------------------------------
# Under `curl | sh` stdin is the pipe, so prompts must come from /dev/tty.
# Skipped when config already exists, in CI/containers (no readable tty), or
# when OMOIKANE_NO_ONBOARD is set. `|| true` keeps `set -e` from aborting.
if [ -z "${OMOIKANE_NO_ONBOARD:-}" ] && [ ! -e "$HOME_DIR/config.toml" ] \
   && [ -e /dev/tty ] && [ -r /dev/tty ]; then
  info ""
  info "Starting onboarding..."
  if ! "$exe" onboard </dev/tty; then
    info "onboarding did not finish — run 'omoikane onboard' anytime to configure."
  fi
fi
