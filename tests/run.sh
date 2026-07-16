#!/usr/bin/env bash
# ===========================================================================
# tests/run.sh -- Frontend for all tests
#
# Discovers and runs every test suite under tests/:
#   1. Python unit tests (pytest)
#   2. Each subdirectory containing run.sh (e.g. tests/workflow/ssccs/run.sh)
#
# Usage:
#   ./tests/run.sh              # all suites
#   ./tests/run.sh --unit       # unit tests only (skip workflow suites)
#   SSCCS_REPO=/path ./tests/run.sh
#
# Exit status:
#   0  -- all suites pass
#   1  -- any suite failed
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FAILED=0

# Parse --unit flag: skip workflow suites when set
RUN_UNIT_ONLY=0
if [[ "${1:-}" == "--unit" ]]; then
  RUN_UNIT_ONLY=1
  shift
fi

# ANSI color helpers
GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

ok()  { printf "  ${GREEN}[PASS]${NC} %s\n" "$1"; }
fail(){ printf "  ${RED}[FAIL]${NC} %s\n" "$1"; FAILED=1; }

# ------------------------------------------------------------------
# Suite 1: Python unit tests
# ------------------------------------------------------------------
set +e
PYTHONPATH="$SCRIPT_DIR/../src" python3 -m pytest "$SCRIPT_DIR" \
  --ignore="$SCRIPT_DIR/workflow" \
  --ignore="$SCRIPT_DIR/command" \
  -v
status=$?
set -e
if [ "$status" -ne 0 ]; then
  fail "Python unit tests"
  if [ "$RUN_UNIT_ONLY" -eq 0 ]; then
    printf "\n${RED}Aborting: workflow tests require passing unit tests.${NC}\n"
    exit 1
  fi
  exit 1
fi
ok "Python unit tests"

# --unit flag: exit after unit tests
if [ "$RUN_UNIT_ONLY" -eq 1 ]; then
  printf "\n"
  if [ "$FAILED" -ne 0 ]; then
    printf "${RED}Unit tests failed.${NC}\n"
    exit 1
  fi
  printf "${GREEN}All unit tests passed.${NC}\n"
  exit 0
fi

# ------------------------------------------------------------------
# Suite 2: Workflow tests (each run.sh under tests/*/)
# ------------------------------------------------------------------
while IFS= read -r -d '' runner; do
  rel="${runner#$SCRIPT_DIR/}"
  printf "\n${CYAN}==== %s${NC}\n\n" "$rel"
  if bash "$runner"; then
    ok "$rel"
  else
    fail "$rel"
  fi
done < <(find "$SCRIPT_DIR" -mindepth 2 -name run.sh -print0)

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
printf "\n"
if [ "$FAILED" -ne 0 ]; then
  printf "${RED}Some test suites failed.${NC}\n"
  exit 1
fi
printf "${GREEN}All test suites passed.${NC}\n"
exit 0
