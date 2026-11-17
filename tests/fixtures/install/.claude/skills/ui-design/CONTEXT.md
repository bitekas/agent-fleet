# ui-design: the fixture install's design map

FIXTURE install context for the fleet's own tests
(`FLEET_CONTEXT_ROOT=tests/fixtures/install`). Every value is synthetic: the
design file, its ids and the people do not exist.

## Design map

`installation/check` of the `ui-design` skill reads this table by its row
labels. Keep each label exactly as written and the table under this heading: a
renamed label reads as a missing value, and a table it cannot find is NO
VERDICT.

| Value | Setting |
|---|---|
| Design file | https://design.example.com/file/EXAMPLEFILEKEY01 |
| Drafts page | `1001:1` |
| Approved page | `1002:1` |
| Implemented page | `1003:1` |
| Scratch area | `1004:1` |
| In-build mark | `EXAMPLE-IN-BUILD ` |
| Superseded mark | `EXAMPLE-SUPERSEDED ` |
| Screen-number registry | doc docs/screen-numbers.md |
| Design approver | Ada Example |
| Design-file owner | Grace Example |
| Code-change authorizer | Alan Example |
| Design-tool skills | none |
