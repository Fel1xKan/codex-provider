#!/usr/bin/env bash
set -euo pipefail

REPO="${REPO:-Fel1xKan/codex-provider}"
VERSION="${VERSION:-latest}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"

usage() {
  cat <<'EOF'
Usage: install.sh <command>

Install one of the provider switchers from GitHub Releases.

Commands:
  cpx    codex provider switcher
  clpx   claude provider switcher
  cupx   cursor provider switcher
  apx    agy provider switcher
  opx    opencode provider switcher

Environment:
  REPO         GitHub repository (default: Fel1xKan/codex-provider)
  VERSION      Release tag or "latest" (default: latest)
  INSTALL_DIR  Install directory (default: ~/.local/bin)
EOF
}

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

COMMAND="$1"
case "$COMMAND" in
  cpx|clpx|cupx|apx|opx) ;;
  *)
    echo "error: unknown command '$COMMAND'" >&2
    usage
    exit 1
    ;;
esac

OS="$(uname -s)"
MACHINE="$(uname -m)"
case "$OS" in
  Linux)
    PLATFORM="linux"
    ;;
  Darwin)
    PLATFORM="macos"
    ;;
  *)
    echo "error: unsupported OS '$OS'; use install.ps1 on Windows" >&2
    exit 1
    ;;
esac

case "$MACHINE" in
  x86_64|amd64|x64)
    ARCH="x86_64"
    ;;
  aarch64|arm64)
    ARCH="arm64"
    ;;
  *)
    echo "error: unsupported architecture '$MACHINE'" >&2
    exit 1
    ;;
esac

if [[ "$VERSION" == "latest" ]]; then
  API_URL="https://api.github.com/repos/${REPO}/releases/latest"
  TAG="$(curl -fsSL "$API_URL" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1)"
  if [[ -z "$TAG" ]]; then
    echo "error: could not determine latest release" >&2
    exit 1
  fi
  VERSION="${TAG#v}"
else
  VERSION="${VERSION#v}"
fi

ASSET="${COMMAND}-${VERSION}-${PLATFORM}-${ARCH}"
BASE_URL="https://github.com/${REPO}/releases/download/v${VERSION}"
mkdir -p "$INSTALL_DIR"
TARGET="$INSTALL_DIR/$COMMAND"

echo "downloading $ASSET"
curl -fsSL "$BASE_URL/$ASSET" -o "$TARGET"
curl -fsSL "$BASE_URL/$ASSET.sha256" -o "$TARGET.sha256"

EXPECTED="$(awk '{print $1}' "$TARGET.sha256")"
ACTUAL="$(shasum -a 256 "$TARGET" | awk '{print $1}')"
if [[ "$ACTUAL" != "$EXPECTED" ]]; then
  rm -f "$TARGET" "$TARGET.sha256"
  echo "error: checksum mismatch" >&2
  exit 1
fi

chmod +x "$TARGET"
rm -f "$TARGET.sha256"

echo "installed $COMMAND to $TARGET"
echo "run: $COMMAND --help"
case ":$PATH:" in
  *":$INSTALL_DIR:"*) ;;
  *)
    echo "note: add $INSTALL_DIR to your PATH to use $COMMAND"
    ;;
esac
