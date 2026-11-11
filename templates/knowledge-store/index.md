# Knowledge base

What this install's agents have learned about the project and the machines it
runs on, kept so that it survives the conversation that produced it.

**This is the store for PROJECT knowledge, and the routing is by SUBJECT, never
by author.** What is true about the project lives here, in the topic folder it
belongs to and never in a per-agent folder: an agent that keeps its own corner
of this store splits it in two, and two stores disagree. What is true about one
agent rather than the project lives in that agent's own memory directory.

**What belongs here:** the decision, the constraint, the reason, the trap -
what is not derivable by opening a file, running the code or reading
version-control history. The test is *would this have saved me time if I had
read it first?*

**What does not:** anything derivable from a repository, a narrative of what
happened, a date, an attribution, or the value of any credential. A
credential's LOCATION is knowledge; a credential is not.

**Everything here is written in the present tense.** A file states how
something IS, never how it was or when it changed. The measurement behind a
fact, and its date, go in this store's commit message.

The conventions - the index rule, the file format, committing, several writers
- are the fleet's `knowledge-base` skill, loaded as `/knowledge-base`. They are
not copied here: a second copy of them is the drift the index rule exists to
prevent.

Folders are created when there is something to put in them, never before.
