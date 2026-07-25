#!/usr/bin/env bash
# ===========================================================================
# tests/run_units.sh -- Unit test runner (excludes command/ and workflow/)
#
# Runs all Python tests under tests/ except:
#   - tests/command/   (slow integration tests: build, check, clean, init, pre)
#   - tests/workflow/  (end-to-end workflow tests)
#
# Usage:
#   ./tests/run_units.sh              # default python
#   PYTHON=python3.14 ./tests/run_units.sh    # specific interpreter
#
# Exit status:
#   0  -- all tests pass
#   1  -- any test failed
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

printf "[test:unit] Running unit tests (excluding command/ and workflow/) ...\n\n"

PYTHONPATH="$SCRIPT_DIR/../src" "$PYTHON" -m pytest "$SCRIPT_DIR" \
  --ignore="$SCRIPT_DIR/command" \
  --ignore="$SCRIPT_DIR/workflow" \
  --tb=short \
  -q

status=$?
printf "\n"
if [ "$status" -ne 0 ]; then
  printf "${RED}[test:unit] Some unit tests failed.${NC}\n"
  exit 1
fi
printf "${GREEN}[test:unit] All unit tests passed.${NC}\n"
exit 0
