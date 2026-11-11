# google-spreadsheet - this install (FIXTURE)

Synthetic install context for the fleet's own tests. Every value is invented; a real
install replaces this file with its own.

## The identity

Each agent acts as `<agent>@example.com`, signing with its own key at
`{home}/secrets/personal/<agent>@example.com-service-account.json`.

## What the delegation grant actually covers

The full Sheets and Drive scopes. Nothing here has been probed: it is a fixture.
