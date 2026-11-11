# rate-graphic - fixture install

FIXTURE. A synthetic install context for the fleet's tests; every value is
invented. A real install's `CONTEXT.md` answers the same questions with its own
values.

- **Where the real ratings log lives:** `ratings-log/ratings.jsonl` in this
  directory, outside the skill tree. It never exists: it is the log
  `rate.test.mjs` proves no test case writes to.
- **Credentials:** the secret `EXAMPLE_API_KEY` in `example-project`, read under
  the service-account key the config's glob names, kept outside every checkout.
- **The calibration evidence:** none is held by this install; the finding is in
  `SKILL.md` section 1.
