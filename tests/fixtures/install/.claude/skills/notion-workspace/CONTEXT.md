# Notion - fixture install

FIXTURE. A synthetic install context for the fleet's tests; every value is
invented. A real install's `CONTEXT.md` answers the same questions with its own
values, and leads with the wrong-workspace risk.

- **Whose workspace:** Example Workspace, for the fixture project.
- **Who a write is attributed to:** the MCP path writes as Ada Example; the
  token path writes as the `example-agent` bot, owned by Ada.
- **Credentials:** the token path in `config.json`, outside every checkout; no
  OAuth client credentials are kept.
- **Integration kind:** internal (token-based).
- **What the token reaches:** one fixture database.
- **Who may use the surface:** whoever the requesting agent's charter names.
