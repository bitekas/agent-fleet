> EXAMPLE lesson - shows the format and the kind of knowledge a store holds. Not part of any install's store.

---
title: A grep -q at the end of a pipeline reports SIGPIPE as "no match"
topic: evidence
verify: |
  # as a bash script; a non-zero count is the defect reproduced
  set -o pipefail; H=$(seq 1 4000 | sed "s/^/line /"); n=0
  for i in $(seq 1 200); do printf "%s" "$H" | grep -qF -- "line 1" || n=$((n+1)); done
  echo "$n false no-match in 200 (${#H} byte haystack)"
---

## The shape

```bash
set -o pipefail                     # anywhere above, including set -euo pipefail
if printf '%s' "$OUT" | grep -qF -- "$needle"; then
```

`grep -q` exits at the **first match** without draining its input. The upstream
`printf` is still writing, so it takes **SIGPIPE and exits 141**. `pipefail`
makes the pipeline's status the rightmost non-zero one, so the `if` sees 141 and
takes the **else** branch - on input that contains the needle. `PIPESTATUS`
reads `141 0`: grep matched; only the pipeline's status lies.

**The rate is governed by the size of the haystack.** Past the pipe buffer
(64 KiB on Linux) the producer must block on a write nobody reads, so the false
result is close to certain. Below it the race narrows but never closes: a few
kilobytes still fail now and then under load. "Our output is short" is not a
defence, and a check with many such assertions goes red on a different one each
time, which reads as a flake in whatever that assertion is about.

## Why it survives review

**The failure message prints the needle it claims is missing**, so every
hypothesis it suggests is about the subject, and all of them are wrong. **The
inverted form is worse and silent**: `if <pipeline>; then FAIL; else PASS` -
"this string must NOT appear" - takes the same 141 into the pass branch, and
reports a tick while the forbidden string sits in the output.

## What to write instead

A shell substring test, with no pipeline and no fork:

```bash
str_has() { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }
```

A quoted expansion inside a `case` pattern matches literally, so glob
characters in the needle are data. When the match needs a regex or a grep flag,
use a here-string, `grep -qF -- "$needle" <<<"$OUT"`: there is no second
process, so `pipefail` has nothing to read. `grep -c` in a pipeline is safe,
because it reads to the end.

Any consumer that exits early does the same - `grep -q`, `grep -m1`, `head -n`,
`sed -n 1q` - wherever the pipeline's STATUS is then read as a verdict.
