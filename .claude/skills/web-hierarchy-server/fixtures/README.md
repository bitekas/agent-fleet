# fixtures/ - the synthetic transcript tree `serve.test.mjs` drives

Everything here is invented. No real session, agent, person or path appears in
it, and nothing here is read by a real run of the server.

```
config.fixture.json             the fixture config (fleet key `fixture-agent`)
fixture-image.png               carried (base64) in agent-aaaa1111's transcript
fixture-root-image.png          carried (base64) in the ROOT session transcript
config-dir/projects/-fixture-project/
  <session>.jsonl               the root session transcript
  <session>/subagents/
    agent-aaaa1111.jsonl        a subagent that is ALIVE  (timestamps: __NOW__)
    agent-aaaa1111.meta.json    agentType software-engineer
    agent-bbbb2222.jsonl        a subagent that is STOPPED (timestamps: 2020)
    agent-bbbb2222.meta.json    agentType qa-engineer
```

Four properties are load-bearing, and each one is invisible until it is gone:

- **`__NOW__` is a token, not a timestamp.** An agent counts as alive when its
  last event is under three minutes old, so a frozen timestamp would make the
  alive/stopped distinction depend on the date the suite runs and the leg would
  silently stop measuring anything. `serve.test.mjs` substitutes the current
  time when it copies this tree.
- **The tree is COPIED before it is used.** The test deletes a subagent's
  transcript as its negative control, and a test that mutates its own committed
  fixtures passes exactly once.
- **The TWO images are a PAIR, and the pair is the point.** They are the same
  format made the same way; the only difference is whose log carries them. The
  ROOT one is in a log the served document BAKES IN, so it must appear in
  `GET /` as a base64 data URI - that is the standalone-page property. The
  SUBAGENT one is in a log the document does not bake, so it must NOT appear
  there and must be reachable only through `GET /img/<hash>`. Drop the root one
  and the "not inlined" half passes just as well on a build where inlining is
  broken everywhere, which is the property gone with a green suite. Both are
  deterministic noise (a fixed seed, zlib level 0) so they stay byte-stable and
  do not compress away, and `serve.test.mjs` compares what `/img/<hash>` serves
  against these files byte for byte.
- **The copy lands at `<tmp>/fixture-agent/.claude`,** whose basename is the
  literal `.claude`, and `config.fixture.json` here maps the key `fixture-agent`. That
  is what makes the fleet-label leg pass only through `format.mjs`'s
  `fleetKey()` parent-basename rule: flatten the copy into a plain tempdir and
  the leg would pass on a basename lookup too, which is the bug the rule exists
  to prevent.
