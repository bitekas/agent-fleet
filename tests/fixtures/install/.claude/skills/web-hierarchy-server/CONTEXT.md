# Web hierarchy server - fixture install

FIXTURE. A synthetic install context for the fleet's tests; every value is
invented. A real install's `CONTEXT.md` answers the same questions with its own
values.

- **Which agent this instance serves:** `ada`, config dir
  `~/agents/ada/.claude`, port 8091, unit `web-hierarchy-1.service`.
- **The fleet label key:** every agent keeps its config dir at
  `<agents-root>/<name>/.claude`, so `fleet.by_config_dir` is keyed by the agent
  name, the parent directory's basename.
- **Where the log goes:** the agent's own home, outside every repository.
- **Who the page is for:** Grace, from another device; `labels.root_owner`
  is the name her prompts carry.
- **The durable form:** the unit needs root, which is Grace's step.
