#!/usr/bin/env bash
#
# Build an example documentation project using SDBS.
#
# Usage:
#   ./build.sh quickstart          # build examples/quickstart with website profile
#
# Prerequisites: Python 3.11+, Quarto installed on PATH
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

EXAMPLE="${1:-quickstart}"
EXAMPLE_DIR="$SCRIPT_DIR/$EXAMPLE"

if [ ! -d "$EXAMPLE_DIR" ]; then
  echo "Error: example '$EXAMPLE' not found at $EXAMPLE_DIR"
  echo "Available examples:"
  for d in "$SCRIPT_DIR"/*/; do
    echo "  $(basename "${d%/}")"
  done
  exit 1
fi

# Install SDBS from local source if not already installed
if ! command -v sdb &>/dev/null; then
  echo "SDBS not found. Installing from repo root..."
  pip install -e "$REPO_ROOT" 2>&1 | tail -1
fi

echo "Building example: $EXAMPLE"
cd "$EXAMPLE_DIR"

# Check Quarto availability
if ! command -v quarto &>/dev/null; then
  # Try the docker fallback
  echo "Quarto not found on PATH. Using Docker image..."
  IMAGE="ghcr.io/ssccsorg/sdbs:latest"
  if ! docker image inspect "$IMAGE" &>/dev/null; then
    echo "Pulling Docker image..."
    docker pull "$IMAGE" 2>/dev/null || {
      echo "Building Docker image from repo root..."
      docker build -t "$IMAGE" -f "$REPO_ROOT/Dockerfile" "$REPO_ROOT"
    }
  fi
  exec docker run --rm \
    -v "$EXAMPLE_DIR":/work \
    -w /work \
    -e QUARTO_PYTHON=python3 \
    "$IMAGE" \
    sdb build . --website
fi

exec sdb build . --website
