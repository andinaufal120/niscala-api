#!/usr/bin/env bash
# PreToolUse guard for Edit/Write in the TDD subagents.
# Usage: restrict-edits.sh only-tests|no-tests
set -euo pipefail

mode="$1"
file=$(jq -r '.tool_input.file_path // empty')
[ -z "$file" ] && exit 0

root=$(realpath -m "$CLAUDE_PROJECT_DIR")
path=$(realpath -m "$file")
case "$path" in
  "$root"/tests/*) in_tests=1 ;;
  *) in_tests=0 ;;
esac

if [ "$mode" = only-tests ] && [ "$in_tests" = 0 ]; then
  echo "test-writer may only edit files under tests/: $file" >&2
  exit 2
fi
if [ "$mode" = no-tests ] && [ "$in_tests" = 1 ]; then
  echo "implementer must not edit tests; stop and report the conflict instead: $file" >&2
  exit 2
fi
exit 0
