# agent usage ledger

Fixture for pool_pick.test.sh. The clock is pinned at 2026-10-16T12:00Z. Each
account's rows establish ONE thing about the pick, and pool_pick.test.sh names
which:

- b: two weekly windows, 85% and 0% -> the HIGHER one is the prediction.
- c: one weekly reading whose reset (Oct 12) has PASSED -> predicted 0%, the
  reset rolled forward 7 days to Oct 19 13:00.
- d: an OLD reading at 90% and the LATEST one at 20% -> the latest stands.
- j: the same reset as d, a HIGHER percentage, and an older last row -> wins
  the tie on idle-longest, not on usage.
- f: the soonest reset of all, but leased -> what the pick would be if leases
  were ignored.
- e: no row at all -> idle, predicted 0%, reset unknown, sorted last.
- h: 75% -> under the exclusion line but short of the headroom line.
- c and f are recorded under `beta`, everything else under `alpha`: usage
  follows the account, not the agent's section.

## alpha

| time | account | window | % used | resets at | velocity %/h | projected depletion | decision |
|---|---|---|---|---|---|---|---|
| 2026-10-14T10:00Z | d@example.com | Current week (all models) | 90 | Oct 18, 9am (UTC) | - | - | first-reading |
| 2026-10-15T08:00Z | j@example.com | Current week (all models) | 40 | Oct 18, 9am (UTC) | - | - | first-reading |
| 2026-10-15T08:30Z | j@example.com | Current session | 5 | 3pm (UTC) | - | - | first-reading |
| 2026-10-16T06:00Z | g@example.com | Current week (all models) | 50 | Oct 21, 1pm (UTC) | - | - | first-reading |
| 2026-10-16T10:00Z | d@example.com | Current week (all models) | 20 | Oct 18, 9am (UTC) | - | - | first-reading |
| 2026-10-16T11:00Z | b@example.com | Current week (all models) | 85 | Oct 20, 6am (UTC) | - | - | first-reading |
| 2026-10-16T11:00Z | b@example.com | Current week (Fable) | 0 | Oct 20, 6am (UTC) | - | - | first-reading |
| 2026-10-16T11:00Z | h@example.com | Current week (all models) | 75 | Oct 17, 1pm (UTC) | - | - | first-reading |

## beta

| time | account | window | % used | resets at | velocity %/h | projected depletion | decision |
|---|---|---|---|---|---|---|---|
| 2026-10-10T10:00Z | c@example.com | Current week (all models) | 60 | Oct 12, 1pm (UTC) | - | - | first-reading |
| 2026-10-16T09:00Z | f@example.com | Current week (all models) | 10 | Oct 17, 6am (UTC) | - | - | first-reading |
