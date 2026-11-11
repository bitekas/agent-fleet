#!/usr/bin/env bash
# run.sh - run every structural gate, tests/gates/*.test.sh, from the
# repository root; exit 1 if any gate fails.
#
# Usage: bash tests/gates/run.sh        (CI's gates job runs it)
#
# With no gate file present it prints "no gates defined" and exits 0: the gate
# set is empty, so there is nothing to fail. Each gate carries its own positive
# control, so a gate that cannot go red is that gate's defect, not this
# runner's.
set -uo pipefail

root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
cd "$root" || exit 2
shopt -s nullglob
gates=(tests/gates/*.test.sh)
if [ "${#gates[@]}" -eq 0 ]; then
  echo "== gates: no gates defined (0 files match tests/gates/*.test.sh); nothing checked"
  exit 0
fi
fails=0
for g in "${gates[@]}"; do
  if bash "$g" </dev/null; then echo "PASS  $g"; else echo "FAIL  $g (exit $?)"; fails=$((fails + 1)); fi
done
echo "== gates: ${#gates[@]} ran, $fails failed"
[ "$fails" -eq 0 ]
