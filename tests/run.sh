#!/usr/bin/env bash
# Run the full dAImon test suite: bash syntax checks + Python unit tests.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail=0

check_sh_files() {
  while IFS= read -r f; do
    if "$@" "$f"; then echo "  ok  $f"; else echo "  FAIL $f"; fail=1; fi
  done < <(find "$ROOT/lib" "$ROOT/backends" "$ROOT/catalog" "$ROOT/profiles" -name '*.sh')
}

echo "== bash syntax =="
check_sh_files bash -n

echo "== shellcheck =="
if command -v shellcheck >/dev/null 2>&1; then
  check_sh_files shellcheck -x
else
  echo "  skip (shellcheck not installed)"
fi

echo "== python unit tests =="
( cd "$ROOT" && python3 -m unittest discover -s tests -p 'test_*.py' -v ) || fail=1

echo "== bash gate tests =="
bash "$ROOT/tests/test_bash.sh" || fail=1

echo "== bats =="
if command -v bats >/dev/null 2>&1; then
  bats "$ROOT"/tests/*.bats || fail=1
else
  echo "  skip (bats not installed)"
fi

exit "$fail"
