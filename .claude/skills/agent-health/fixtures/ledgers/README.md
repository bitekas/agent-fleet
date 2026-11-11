# ledger fixtures

Each file is a usage ledger in the state a test case needs it in, and the tests
copy one into a temp directory before touching it - nothing here is written to
in place.

They differ from each other in ONE respect at a time, on purpose:

| file | the one thing it establishes |
|---|---|
| `empty.md` | the preamble alone, no agent section - a first reading |
| `prev-ok.md` | a previous row 30 min back whose decision was `ok` - so a trip is the FIRST trip and must come back `watch`, never `switch` |
| `prev-watch.md` | the same row with decision `watch` - the SECOND consecutive trip, which switches |
| `prev-ok-distant.md` | a previous row 60 min back, giving a gentler slope whose projection lands beyond the horizon |
| `prev-flat-90.md` | a previous row identical in percent to the capture, so velocity is exactly 0 and only the floor can fire |
| `prev-high.md` | a previous row ABOVE the capture, so velocity is negative and no projection may be produced |
| `prev-other-account.md` | `prev-watch.md`'s row on a DIFFERENT account - the handover discontinuity, which must read as a first reading |
| `prev-one-minute.md` | a previous row ONE MINUTE back, an ordinary gap between a session-start sweep and the scheduled one. One percentage point over a minute reads as 60 %/h if a slope is taken from it |
| `prev-unrounded.md` | a previous row 35 minutes back, so the velocity is 20.571... and the rounding to one decimal place is visible. 24.0 is 24.0 rounded or not, so no other fixture can see it |
| `prev-bad-time.md` | a row with a corrupt `time` cell - a first reading, never an uncaught `strptime` (which exits 1, i.e. "hand this agent over") |
| `prev-malformed.md` | a row with SEVEN cells. An instrument fault, not a skipped row: skipping it makes an OLDER row the baseline and downgrades a handover to a wait |
| `prev-subheading.md` | `prev-watch.md`'s row parked under an operator's `### notes`. Read as the agent's, it would switch the agent on somebody's annotation |

⚠️ `prev-ok.md` and `prev-watch.md` differ in the decision cell and nothing
else. That pair is the only thing in the suite that can see the two-consecutive-
checks rule disappear: with one of them alone, a parser that switched on the
first trip would pass.
