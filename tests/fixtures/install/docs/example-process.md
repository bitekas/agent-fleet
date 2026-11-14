# Example process

FIXTURE document for the fleet's own tests: the install's own process document,
which the fixture manifest's `conventions.branch_naming` points at (section
*Branch names*). Every value in it is synthetic.

## Branch names

A branch is named `<agent>/<type>/<slug>`, where `<agent>` is the writing
agent's name in lower case and `<type>` is one of `feature`, `bug`, `chore` or
`docs`. A commit subject starts with the agent's name, capitalised, and a
colon, followed by `type(scope): subject`.
