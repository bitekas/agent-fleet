> EXAMPLE lesson - shows the format and the kind of knowledge a store holds. Not part of any install's store.

---
title: A control that fires is not a control that discriminates
topic: evidence
---

A check is evidence only once it has been shown to fail. That rule is necessary
and not sufficient, because it never asks the next question: **the control
fires - but on WHAT?**

## The control must trip every assertion family

A check that asserts two independent things carries two families - say,
**exact equality** between two variants, and a **tolerance** of 1.5 units
against a reference. A negative control that nudges one input can move the
measured value by 1 unit instead of the intended 10, because a `max()`, a clamp
or a bounding box absorbs most of the edit. The equality family fires on the
1-unit difference, the run goes red, and the control reads as working. The
tolerance family never fires - so the half of the check most likely to be
wrongly slack has never been shown to detect anything. **Nothing in the output
distinguishes this from a healthy control: a red is a red.**

1. **Enumerate the assertion families first**, then design one perturbation per
   family, or one large enough to trip all of them.
2. **Make the check refuse a verdict unless every family fires** under its
   control. That turns an invisible weakness into a loud one, and it is the only
   version that survives a later edit.
3. **"I perturbed the input" is not "the measurement moved."** Verify that the
   perturbation reaches the measured quantity by the intended magnitude.
4. **Size the perturbation against the loosest tolerance in the check.** A
   control smaller than a tolerance cannot test that tolerance.

This class survives review because it announces itself as a RED - the outcome
you were hoping for - while every other broken-instrument failure announces
itself as a suspicious green. Ask of every control: which assertion produced
that red, and which were along for the ride?

## Controls stop discriminating when the system moves under them

Adding a defence can silently disarm the control that guards a different one:
a new matcher that catches the casualties a scramble control relied on makes
the scramble free. The change is correct, both controls are correct, neither is
edited, and the relationship between them is gone. **Such a control does not go
red; it stops discriminating, which is quieter** - it still reports "no problem
found", and a control's premise is not in its own file, so no search finds it.

- **Write a mutation control to assert WHICH named checks must lose their
  answer**, never that "something fails". The specific form sees the difference
  between "this fired" and "this can still fire".
- **After adding any defence, re-run every existing control** and confirm each
  still discriminates. Green is what you see whether they work or not.

## An absence-only suite cannot fail in the interesting direction

Where every expectation is an absence, the branch that sets the thing never
runs: a suite asserting for every case that a field is absent passes with the
line that sets it deleted. The fix is a control that drives a case where the
field must be PRESENT and asserts its value.
