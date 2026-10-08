#!/usr/bin/env bash
# Build a distributable zip of the boring skill.
#
# Output:
#   boring/dist/boring/             — staged tree (kept for inspection)
#   boring/dist/boring-<version>.zip — artifact for distribution
#
# Version is read from boring/src/pyproject.toml.
#
# Usage (from anywhere):
#   boring/tools/build.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BORING_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="$BORING_DIR/src"
DIST_DIR="$BORING_DIR/dist"
STAGE_DIR="$DIST_DIR/boring"

if [[ ! -f "$SRC_DIR/SKILL.md" ]]; then
    echo "error: $SRC_DIR/SKILL.md not found — is the layout intact?" >&2
    exit 1
fi

VERSION="$(awk -F'"' '/^version[[:space:]]*=/ { print $2; exit }' "$SRC_DIR/pyproject.toml")"
if [[ -z "$VERSION" ]]; then
    echo "error: could not parse version from $SRC_DIR/pyproject.toml" >&2
    exit 1
fi

ZIP_PATH="$DIST_DIR/boring-$VERSION.zip"

rm -rf "$STAGE_DIR" "$DIST_DIR"/boring-*.zip
mkdir -p "$STAGE_DIR"

# Stage src/ → dist/boring/, dropping dev cruft.
rsync -a \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='*.egg-info/' \
    --exclude='*.pyc' \
    --exclude='.envrc' \
    --exclude='.ruff_cache/' \
    --exclude='.DS_Store' \
    "$SRC_DIR/" "$STAGE_DIR/"

# Zip with the boring/ wrapper so `unzip` produces a single top-level dir.
( cd "$DIST_DIR" && zip -qr "$(basename "$ZIP_PATH")" boring/ )

FILE_COUNT="$(find "$STAGE_DIR" -type f | wc -l | tr -d ' ')"
ZIP_SIZE="$(du -h "$ZIP_PATH" | cut -f1)"
echo "Built $ZIP_PATH ($FILE_COUNT files, $ZIP_SIZE)"
