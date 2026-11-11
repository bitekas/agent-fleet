# Knowledge base - example

An example store: a small set of generic lessons that show the layout, the index rule
and the file format the `knowledge-base` skill prescribes, and the kind of
knowledge worth keeping. It is not part of any install's store. An install
starts its own store empty, from `templates/knowledge-store/index.md`, and fills
it with what its own agents learn; nothing here is copied into it.

Every lesson opens with a line marking it as an example. In a real store that
line does not exist, and the file starts at its front matter.

## Subfolders
- [agents/](agents/index.md) - handing work to an agent and judging what comes back: work orders, completion signals, scheduled work, and writes that carry authorship
- [communication/](communication/index.md) - answering the ask that was made, chasing someone who went quiet, and taking a correction
- [evidence/](evidence/index.md) - deciding whether a claim is true: controls that do not discriminate, checks that cannot reach their subject, and what an absence proves
- [machine/](machine/index.md) - shell and host traps that fail silently: Claude Code's rm guard, and signalling a process group
