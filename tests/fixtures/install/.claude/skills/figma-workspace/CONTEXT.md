# Figma - fixture install

FIXTURE. A synthetic install context for the fleet's tests; every value is
invented. A real install's `CONTEXT.md` answers the same questions with its own
values, and leads with whose name a posted comment carries.

- **Whose tokens:** Ada Example's. A comment posted with the write token appears
  under Ada's name, so every one starts with the `post.prefix` text.
- **Which files:** `main`, the fixture design file, and `fixture-install-library`.
- **Token roles:** the read token carries `file_comments:read` only; no write
  token and no content token are configured, so this install is read-only and
  anchor names are not looked up.
- **Token expiry:** the read token's expiry date, and the scheduled reminder
  that renews it before then.
- **Path 1:** the hosted connector, signed in as Ada, on a Full seat.
- **Who may post:** whoever the requesting agent's charter names.
- **Design work:** the design skill this install has, by name.
