# Test-driven development

## Purpose

Use a focused test to verify a bug fix or a change in behavior. Apply this skill when the task calls for a regression test or when existing tests leave an important gap.

## How to work

1. Find the repository's test commands and its closest behavioral test. Start at the smallest public entry point that owns the rule.
2. Write a case with explicit inputs and an expected result. Run it on the current implementation and check that the failure reproduces the behavior gap.
3. Make the smallest change that satisfies the behavior. Rerun the focused test. Refactor when it makes the code clearer, then run the checks affected by the change.
4. Report the commands and outcomes. When the brief calls for a fixture or the implementation is unavailable, provide the cases and expected outcomes and mark the execution as pending.

## Example

For a stale revision check, save revision 2 and attempt a write using revision 1. Expect a conflict and verify that revision 2 remains the latest saved definition. Record the outcome separately from the case definition.

Adapted from Addy Osmani's Test-Driven Development. [Source and MIT attribution](../../../../../ATTRIBUTION.md)
