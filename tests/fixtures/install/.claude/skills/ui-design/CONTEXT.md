# ui-design: the fixture install's design map

FIXTURE install context for the fleet's own tests
(`FLEET_CONTEXT_ROOT=tests/fixtures/install`). Every value is synthetic: the
design file, its ids and the people do not exist. The design file's key, the
approved and implemented pages and the two marks are the values the fixture's
definition-of-done `config.json` holds (`figma.*`), because the check compares
them.

## Design map

`installation/check` of the `ui-design` skill reads this table by its row
labels. Keep each label exactly as written and the table under this heading: a
renamed label reads as a missing value, and a table it cannot find is NO
VERDICT.

| Value | Setting |
|---|---|
| Design file | `ExAmPlEfIlEkEy0000000` https://design.example.com/file/ExAmPlEfIlEkEy0000000/Example |
| Drafts page | `300:1` |
| Approved page | `200:1` |
| Implemented page | `100:1` |
| Scratch area | `400:1` |
| In-build mark | `IN BUILD - ` |
| Superseded mark | `MARKED FOR DELETION - ` |
| Screen-number registry | doc docs/screen-numbers.md |
| Design approver | Ada Example |
| Design-file owner | Grace Example |
| Code-change authorizer | Alan Example |
| Design-tool skills | none |
