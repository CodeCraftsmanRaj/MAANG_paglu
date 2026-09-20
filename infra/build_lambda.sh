#!/usr/bin/env bash
# Stage the ContextForge backend into backend/lambda-build/ ready for AWS packaging.
# - copies only runtime code: app/ + lambda_handler.py (+ slim requirements.txt)
# - installs wheels for the Lambda python3.12 x86_64 runtime, even when building
#   from a different host OS/Python (macOS/Windows/other Linux), so the bundle is ABI-correct.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="$ROOT/backend/lambda-build"
REQ="$ROOT/backend/requirements-lambda.txt"

echo "==> Staging Lambda package in ${STAGE}"
rm -rf "$STAGE"
mkdir -p "$STAGE"

cp -r "$ROOT/backend/app" "$STAGE/app"
cp "$ROOT/backend/lambda_handler.py" "$STAGE/"
cp "$REQ" "$STAGE/requirements.txt"
find "$STAGE" -type d -name "__pycache__" -prune -exec rm -rf {} +

# Locate a pip on the host. Prefer an isolated build venv: PEP 668 systems
# (macOS Homebrew, Ubuntu 23+) refuse global pip installs even with --target.
VENV="$ROOT/infra/.build-venv"
PIP=()
if [ -x "$VENV/bin/pip" ]; then
  PIP=("$VENV/bin/pip")
elif [ -f "$VENV/Scripts/pip.exe" ]; then
  PIP=("$VENV/Scripts/pip")
else
  rm -rf "$VENV"
  if python3 -m venv "$VENV" 2>/dev/null && [ -x "$VENV/bin/pip" ]; then
    PIP=("$VENV/bin/pip")
  elif [ -f "$VENV/Scripts/pip.exe" ]; then
    PIP=("$VENV/Scripts/pip")
  elif python3 -m pip --version >/dev/null 2>&1; then
    PIP=(python3 -m pip)
  elif command -v pip3 >/dev/null 2>&1; then
    PIP=(pip3)
  else
    echo "ERROR: no usable pip found. Install Python 3 (with pip or ensurepip), or run inside a standard venv." >&2
    exit 1
  fi
fi

echo "==> Installing dependencies for Lambda runtime python3.12 / x86_64"
if ! "${PIP[@]}" install \
    -r "$STAGE/requirements.txt" \
    --target "$STAGE" \
    --upgrade \
    --only-binary=:all: \
    --implementation cp \
    --python-version 3.12 \
    --platform x86_64 \
    --platform linux_x86_64 \
    --platform manylinux2014_x86_64 \
    --platform manylinux_2_28_x86_64 \
    --no-compile ; then
  echo "==> Cross-platform wheel install failed; retrying host install." >&2
  echo "    NOTE: this must run on Linux x86_64 (e.g. WSL) to produce a working bundle." >&2
  "${PIP[@]}" install -r "$STAGE/requirements.txt" --target "$STAGE" --upgrade --no-compile
fi

# Prune artifacts not needed at runtime
find "$STAGE" -type d -name "__pycache__" -prune -exec rm -rf {} +
rm -rf "$STAGE/bin"

echo "==> Staged package: $(du -sh "$STAGE" | cut -f1) at ${STAGE}"
