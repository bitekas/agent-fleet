# agent usage ledger

One section per agent, one row per window read. `parse_usage.py --ledger <this
file> --agent <name> --append` writes the rows and reads the previous ones back
out of them; nothing else may write here, because the previous row IS the
baseline every velocity and every projection is computed against.

`velocity %/h` is the change in `% used` since that window's previous row on the
SAME account, per hour. `projected depletion` is `time + (100 - % used) /
velocity`. `decision` is one of:

| decision | means |
|---|---|
| `first-reading` | no comparable previous row (new agent, new window name, or a new account after a handover). Recorded, not acted on. |
| `ok` | read, and nothing to do: flat or falling usage, or a projection beyond the horizon. |
| `watch` | the projection landed within the horizon for the FIRST time. One more consecutive one switches the agent. A later reading that produces no projection at all CARRIES this forward rather than clearing it - these agents alternate between a burst and idle, and clearing it made the rule inert for exactly them. |
| `hold-reset-first` | the projection landed within the horizon, but the window resets before it would deplete, so the window empties itself. |
| `switch-projection` | the projection landed within the horizon on two consecutive checks with the reset after it. Hand the agent over. |
| `switch-floor` | at or over the absolute floor (short window 90%, any other 95%). Hand the agent over, whatever the velocity says. |
| `floor-only` | evaluated with no ledger, so only the floor was applied. NOT the same claim as `ok`. |

⚠️ Do not delete or rewrite rows to tidy this file. A removed row is a velocity
that cannot be computed and a projection that silently stops existing; an edited
one is a baseline that lies. It grows, and that is the intended shape.
