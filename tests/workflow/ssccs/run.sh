#!/usr/bin/env bash
# ===========================================================================
# tests/workflow/ssccs/run.sh -- Full production workflow test
#
# Executes ``sdb build docs --website`` against a real ssccs checkout in
# two phases and reports results for both.
#
# Phase 1 (cold):  no cache -- every target renders from scratch
# Phase 2 (warm):  cache pre-populated by phase 1 -- every target hits cache
#
# Usage:
#   ./tests/workflow/ssccs/run.sh                       # clone fresh
#   SSCCS_REPO=/path ./tests/workflow/ssccs/run.sh      # reuse local checkout
#
# Exit status:
#   0  -- both phases pass, all output files verified
#   1  -- any phase failed or output missing
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SDBS_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ------------------------------------------------------------------
# Prerequisites
# ------------------------------------------------------------------
command -v quarto >/dev/null 2>&1 || { echo "[FAIL] quarto not found on PATH"; exit 1; }
command -v rumdl  >/dev/null 2>&1 || { echo "[FAIL] rumdl not found on PATH";  exit 1; }

# ------------------------------------------------------------------
# Source checkout
# ------------------------------------------------------------------
SSCCS_REPO="${SSCCS_REPO:-}"

if [ -z "$SSCCS_REPO" ]; then
  CLONE_DIR=$(mktemp -d /tmp/ssccs_workflow.XXXXXX)
  echo "[INFO] Cloning ssccsorg/ssccs into $CLONE_DIR ..."
  git clone --depth 1 --single-branch "https://github.com/ssccsorg/ssccs" "$CLONE_DIR"
  SSCCS_REPO="$CLONE_DIR"
  CLEANUP_CLONE=1
else
  echo "[INFO] Using existing checkout: $SSCCS_REPO"
  CLEANUP_CLONE=0
fi

if [ ! -d "$SSCCS_REPO/docs" ]; then
  echo "[FAIL] docs/ not found in $SSCCS_REPO"
  exit 1
fi

# ------------------------------------------------------------------
# Clean docs copy (strip cached artifacts)
# ------------------------------------------------------------------
BUILD_DIR=$(mktemp -d /tmp/ssccs_build.XXXXXX)
echo "[INFO] Clean docs copy: $BUILD_DIR/docs"

rsync -a --delete \
  --exclude=_cached \
  --exclude=_site \
  --exclude=_docsbuild \
  --exclude=_llms \
  --exclude=.jupyter_cache \
  --exclude='*_cached' \
  --exclude='*_files' \
  --exclude='*_libs' \
  --exclude='*_output' \
  --exclude='*_pages' \
  --exclude='*.html' \
  "$SSCCS_REPO/docs/" "$BUILD_DIR/docs/"

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

check_file() {
  local path="$1"
  local label="$2"
  if [ -f "$path" ]; then
    echo "    [OK]   $label  ->  $path"
  else
    echo "    [FAIL] $label  ->  $path  (missing)"
    return 1
  fi
}

check_html() {
  local path="$1"
  local label="$2"
  if [ ! -f "$path" ]; then
    echo "    [FAIL] $label  ->  $path  (missing)"
    return 1
  fi
  if grep -q '<!DOCTYPE html>' "$path" || grep -q '<html' "$path"; then
    echo "    [OK]   $label  ->  $path  (valid HTML)"
  else
    echo "    [WARN] $label  ->  $path  (exists, but no HTML tag found)"
  fi
}

run_phase() {
  local label="$1"
  local docs_dir="$2"
  local log="$3"

  echo ""
  echo "========================================================"
  echo "  Phase $label"
  echo "  sdb build docs --website"
  echo "========================================================"
  echo ""

  local start end duration
  start=$(date +%s)

  cd "$SDBS_ROOT"
  PYTHONPATH="$SDBS_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m sdb.cli build "$docs_dir" --website 2>&1 | tee "$log"
  local ok
  ok=${PIPESTATUS[0]}

  end=$(date +%s)
  duration=$(( end - start ))

  echo ""
  echo "  --- Phase $label finished (exit $ok, ${duration}s) ---"
  echo ""

  # Store duration for summary
  echo "$duration" > "$log.dur"

  return "$ok"
}

verify_outputs() {
  local docs_dir="$1"
  local label="$2"
  local failed=0

  local site
  site="$docs_dir/_site"

  echo ""
  echo "  --- $label output verification ---"
  echo ""
  check_html   "$site/index.html"     "index.qmd -> HTML"     || failed=1
  check_html   "$site/code_of_conduct.html" "code_of_conduct.qmd -> HTML" || failed=1
  check_file   "$docs_dir/_include/_updated_docs_list.qmd" "pre-build: _updated_docs_list.qmd" || failed=1
  check_file   "$docs_dir/_llms/llms.txt"                  "post-render: llms.txt"           || failed=1

  if [ "$failed" -ne 0 ]; then
    echo ""
    echo "  [FAIL] $label output verification failed"
  else
    echo ""
    echo "    * All outputs verified *"
  fi
  echo ""

  return "$failed"
}

# ------------------------------------------------------------------
# Phase 1 -- cold build (no cache)
# ------------------------------------------------------------------
LOG1=$(mktemp /tmp/ssccs_phase1.XXXXXX)
run_phase "1 (cold)" "$BUILD_DIR/docs" "$LOG1" || { echo "[FAIL] Phase 1 build failed"; exit 1; }
verify_outputs "$BUILD_DIR/docs" "Phase 1" || { echo "[FAIL] Phase 1 output verification failed"; exit 1; }

# ------------------------------------------------------------------
# Phase 2 -- warm build (reuse cache populated by phase 1)
#
# Same command, same docs copy -- cache from phase 1 should make this
# instant (all cache hits, no actual rendering).
# ------------------------------------------------------------------
LOG2=$(mktemp /tmp/ssccs_phase2.XXXXXX)
run_phase "2 (warm)" "$BUILD_DIR/docs" "$LOG2" || { echo "[FAIL] Phase 2 build failed"; exit 1; }
verify_outputs "$BUILD_DIR/docs" "Phase 2" || { echo "[FAIL] Phase 2 output verification failed"; exit 1; }

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo ""
echo "========================================================"
echo "  Summary"
echo "========================================================"
echo ""

echo "  Phase 1 (cold):  $(cat "$LOG1.dur")s"
echo "  Phase 2 (warm):  $(cat "$LOG2.dur")s"
echo ""

# ------------------------------------------------------------------
# Cleanup temporary logs and cloned repo
# ------------------------------------------------------------------
rm -f "$LOG1" "$LOG2" "$LOG1.dur" "$LOG2.dur"
if [ "${CLEANUP_CLONE:-0}" -eq 1 ]; then
  rm -rf "$CLONE_DIR"
fi

echo "[INFO] Build output preserved at: $BUILD_DIR/docs"
echo "[INFO] Remove manually: rm -rf $BUILD_DIR"
echo ""

exit 0
