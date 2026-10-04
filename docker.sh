#!/usr/bin/env bash
#
# Build the SDBS Docker image and verify the engine inside it.
#
# The image is the complete distribution: Quarto, the renderer, and the sdbs
# package with its deploy channels installed. This script builds it and runs a
# self-contained check, so the distribution can be built and validated without
# an external registry, a cloud provider, or a CI pipeline.
#
# Usage:
#   ./docker.sh build [tag]   Build the image (default tag: sdbs:local).
#   ./docker.sh check [tag]   Build the image, then run the check inside it.
#
# The check runs a dry-run deploy. A dry run validates the channel and counts
# the objects without contacting a store, so the check needs no credentials and
# no network beyond the image build.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMMAND="${1:-check}"
TAG="${2:-sdbs:local}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

build() {
  echo "Building $TAG from $SCRIPT_DIR/Dockerfile"
  docker build -t "$TAG" -f "$SCRIPT_DIR/Dockerfile" "$SCRIPT_DIR"
}

check() {
  local work
  work="$(mktemp -d)"
  # The variable is out of scope by the time the trap runs, so default it.
  trap 'rm -rf "${work:-}"' EXIT

  mkdir -p "$work/docs/_site"
  cat > "$work/docs/build.yml" <<'YAML'
deploy:
  - name: check
    plugin: s3
    source: _site
    options:
      bucket: check-bucket
      prefix: check/docs
YAML
  printf '<html>check</html>' > "$work/docs/_site/index.html"

  echo "Running the deploy self-check inside $TAG"
  # The workspace is mounted read-only: the check proves the image carries the
  # engine and the s3 channel, and that a deploy reaches validation without a
  # store, a credential, or a write.
  docker run --rm \
    -v "$work":/work:ro \
    -w /work \
    -e S3_ENDPOINT=https://example.invalid \
    -e AWS_REGION=check-region \
    -e AWS_ACCESS_KEY_ID=check \
    -e AWS_SECRET_ACCESS_KEY=check \
    "$TAG" \
    bash -c 'set -euo pipefail; sdb --version; python3 -c "import sdb.plugins.s3"; sdb deploy docs --dry-run'

  echo "OK: $TAG carries the deploy engine and the s3 channel"
}

case "$COMMAND" in
  build) build ;;
  check) build; check ;;
  *) echo "usage: $0 {build|check} [tag]" >&2; exit 2 ;;
esac
