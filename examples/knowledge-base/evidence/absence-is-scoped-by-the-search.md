> EXAMPLE lesson - shows the format and the kind of knowledge a store holds. Not part of any install's store.

---
title: Absence is only evidence within the scope you set
topic: evidence
---

Before reporting that something is MISSING, **state where you looked and ask
what would be true if it had simply MOVED.** A "not found" is scoped to the
search you ran, and you chose the scope.

**Name the scope inside the finding.** "Not present in this file" is honest;
"does not exist" is a claim about the world you have not checked. Deletion is
the rarest explanation for a thing you cannot find: spend one step on where it
would be if it had moved - a new file, a rename, another repository, another
account.

## Search for the effect, not the name you predict

**A name is a guess; an effect is not.** A search for
`rateLimit|maxRequests|quota` misses a cap whose identifier says `velocity`.
The status code it returns, the error string a user sees, or the log line it
writes each find it at once. Search for what the thing DOES to the world.

## A null from a broken instrument looks exactly like an absence

- **A search that returns nothing for a term that MUST occur is a broken
  search, never an absence.** Zero hits for "error" across a large codebase is
  a filter in the pipe, not a clean codebase. Point the instrument at something
  you know is there before trusting its silence.
- **A failed query returns zero rows, and zero rows is what "nothing is wrong"
  looks like.** A health check that prints a count renders a failure as a clean
  result. Print the status beside the count and read it first; in a check that
  matters, assert on the status instead of displaying it.
- **Identifier classes are not interchangeable, and an API rarely says so.**
  Passing a user id where a conversation id is expected yields a plain "not
  found", which reads as "nothing there" rather than "wrong question".

## "Absent now" and "absent ever" are different claims

Reading current source proves the first and says nothing about the second.
Anything of the form *"there is no X"* about historical data needs a history
check: version-control history, or the data itself.

## Absence of intervention is not observable

Telemetry shows **effects, never actions**. There is no event for "a person
changed a setting", so the absence of such an event is an absence of
instrumentation. **Never assert "nobody touched it."** Report what recovered
and when, and ask the system's owner if the cause matters: one question removes
the whole false claim.

**A person's specific number is evidence.** "It stopped me at 50" is too precise
to be a misperception; when a search disagrees with a stated figure, doubt the
search.
