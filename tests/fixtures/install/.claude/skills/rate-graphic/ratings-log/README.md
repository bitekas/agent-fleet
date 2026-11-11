# The fixture install's ratings log directory

`../config.json` names `ratings-log/ratings.jsonl` as this fixture install's
real ratings log. This file exists so the directory exists in a clean checkout:
`rate.mjs` refuses to write into a missing directory, and with no directory a
test case that escaped its temp config would be refused by `rate.mjs` instead of
being caught by `rate.test.mjs`'s real-log control, which would then guard a log
nothing can write and could never fire.

`ratings.jsonl` must never appear here. If it does, a test case wrote to the
install's log instead of its own temp log; delete it and find the case.
