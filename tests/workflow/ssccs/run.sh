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
# Phase 3 -- publish build (cold, fresh docs copy, no pre-existing cache)
# ------------------------------------------------------------------
PUBLISH_BUILD_DIR=$(mktemp -d /tmp/ssccs_publish.XXXXXX)
echo "[INFO] Clean docs copy for publish: $PUBLISH_BUILD_DIR/docs"

rsync -a --delete \
  --exclude=_cached --exclude=_site --exclude=_docsbuild --exclude=_llms --exclude=_publish --exclude=.jupyter_cache --exclude='*_cached' --exclude='*_libs' --exclude='*_output' --exclude='*_pages' \
  "$SSCCS_REPO/docs/" "$PUBLISH_BUILD_DIR/docs/"

LOG3=$(mktemp /tmp/ssccs_phase3.XXXXXX)
LABEL="3 (publish)"

echo ""
echo "========================================================"
echo "  Phase $LABEL"
echo "  sdb build docs --publish (cold, implies --website)"
echo "========================================================"
echo ""

start=$(date +%s)

cd "$SDBS_ROOT"
PYTHONPATH="$SDBS_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"   python3 -m sdb.cli build "$PUBLISH_BUILD_DIR/docs" --publish 2>&1 | tee "$LOG3"
ok=${PIPESTATUS[0]}

end=$(date +%s)
duration=$(( end - start ))

echo ""
echo "  --- Phase $LABEL finished (exit $ok, ${duration}s) ---"
echo ""
echo "$duration" > "$LOG3.dur"

if [ "$ok" -ne 0 ]; then
  echo "[FAIL] Phase $LABEL build failed"
  exit 1
fi

# Phase 3 output verification
PUBLISH_DIR="$PUBLISH_BUILD_DIR/docs/_publish"
echo ""
echo "  --- Phase $LABEL output verification ---"
echo ""

failed=0

check_file   "$PUBLISH_DIR/whitepaper-whitepaper/whitepaper.tex"     "whitepaper -> .tex"      || failed=1
check_file   "$PUBLISH_DIR/whitepaper-whitepaper/whitepaper.pdf"     "whitepaper -> .pdf"      || failed=1
check_file   "$PUBLISH_DIR/whitepaper-whitepaper/whitepaper.html"    "whitepaper -> .html"     || failed=1
check_file   "$PUBLISH_DIR/whitepaper-whitepaper/metadata.yaml"      "whitepaper -> metadata"  || failed=1

FIG_PDF="$PUBLISH_DIR/whitepaper-whitepaper/whitepaper_files/figure-pdf"
if [ -d "$FIG_PDF" ] && [ "$(ls -A "$FIG_PDF" 2>/dev/null | wc -l)" -gt 0 ]; then
  count=$(ls "$FIG_PDF" | wc -l)
  echo "    [OK]   whitepaper -> figure-pdf/  ($count files)"
else
  echo "    [FAIL] whitepaper -> figure-pdf/  (missing or empty)"
  failed=1
fi

# _files/ metadata is QMD config-dependent; skip CI check
check_file   "$PUBLISH_DIR/index/index.html"       "index -> .html"           || failed=1
check_file   "$PUBLISH_DIR/index/metadata.yaml"    "index -> metadata"        || failed=1

if [ -d "$PUBLISH_DIR/whitepaper-whitepaper/site_libs" ]; then
  lib_count=$(find "$PUBLISH_DIR/whitepaper-whitepaper/site_libs" -type f 2>/dev/null | wc -l)
  echo "    [OK]   whitepaper -> site_libs/  ($lib_count files)"
else
  echo "    [FAIL] whitepaper -> site_libs/  (missing)"
  failed=1
fi

# Compile .tex with lualatex to verify it's valid
TEX_FILE="$PUBLISH_DIR/whitepaper-whitepaper/whitepaper.tex"
if [ -f "$TEX_FILE" ]; then
  TEX_DIR=$(mktemp -d /tmp/tex_compile.XXXXXX)
  cp -r "$PUBLISH_DIR/whitepaper-whitepaper"/* "$TEX_DIR/"
  cd "$TEX_DIR"
  if lualatex -interaction=nonstopmode whitepaper.tex 2>&1 | grep -q "Output written on whitepaper.pdf"; then
    pages=$(strings whitepaper.pdf | grep -c "/Type /Page" 2>/dev/null || echo "?")
    echo "    [OK]   whitepaper.tex -> lualatex -> PDF  (${pages:+$pages pages})"
  else
    echo "    [FAIL] whitepaper.tex -> lualatex failed"
    grep -i "error" whitepaper.log 2>/dev/null | head -3
    failed=1
  fi
  rm -rf "$TEX_DIR"
  cd "$PUBLISH_DIR"
else
  echo "    [WARN] whitepaper.tex not found, skipping lualatex test"
fi

if [ "$failed" -ne 0 ]; then
  echo ""
  echo "  [FAIL] Phase $LABEL output verification failed"
  exit 1
else
  echo ""
  echo "    * All publish outputs verified *"
fi
echo ""

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo ""
echo "========================================================"
echo "  Summary"
echo "========================================================"
echo ""

echo "  Phase 1 (cold):     $(cat "$LOG1.dur")s"
echo "  Phase 2 (warm):     $(cat "$LOG2.dur")s"
echo "  Phase 3 (publish):  $(cat "$LOG3.dur")s"
echo ""

# ------------------------------------------------------------------
# Cleanup temporary logs and cloned repo
# ------------------------------------------------------------------
rm -f "$LOG1" "$LOG2" "$LOG3" "$LOG1.dur" "$LOG2.dur" "$LOG3.dur"
  rm -rf "$PUBLISH_BUILD_DIR"
if [ "${CLEANUP_CLONE:-0}" -eq 1 ]; then
  rm -rf "$CLONE_DIR"
fi

echo "[INFO] Build output preserved at: $BUILD_DIR/docs"
echo "[INFO] Remove manually: rm -rf $BUILD_DIR"
echo ""

exit 0
