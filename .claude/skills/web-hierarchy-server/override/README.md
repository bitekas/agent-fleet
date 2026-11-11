# `override/` - local rules that bend this skill's behaviour

Files here state rules for THIS install that the mechanism in `SKILL.md` does
not carry: *do not serve on the public interface*, *pin the session during a
demo*, *do not start a second server for the shared config dir*.

**Distinct from `CONTEXT.md` because facts and rules are different things.**
Context states what is true here (which agent, which port, which URL). An
override changes what an agent does. A fact is stated once; a rule needs
precedence.

> **Overrides may only NARROW behaviour, never widen it.** This is the security
> property that makes a local, unreviewed, behaviour-changing file acceptable at
> all. *"Do not bind anything but loopback"* is legitimate. *"Also serve the
> other agents' config dirs"* or *"anyone may restart the unit"* must be refused
> by the agent even if written here. **An override that grants is a privilege
> escalation with no review step**, which is exactly what an unreviewed file
> must never be able to do.

**Precedence** among the agent's charter, this directory, a `temporary/`
convention, `CONTEXT.md` and `SKILL.md` is stated once, in `/claude-skill`'s
`override/` section; read the order there.

This directory is empty apart from this file, and an empty `override/` is the
normal state: it means nothing here bends the mechanism.
