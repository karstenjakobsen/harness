# Code review and quality

## Purpose

Review code or a worker's technical deliverable against the agreed behavior. Give the owner or operator enough evidence to decide what to accept or investigate.

## How to review

1. Read the goal revision or brief, the relevant project conventions and the changed files. Start at the public behavior that callers depend on.
2. Check correctness, including defaults, invalid input, retries, concurrency and failure paths where they apply. Look for tests that exercise the rule and its boundaries.
3. Check readability and architecture. Follow the call across adapters and domain operations. Identify duplicated rules, avoidable dependencies and names that obscure the contract.
4. Check how the change handles authority, untrusted input and sensitive data. Assess performance when the change affects an observable workload.
5. Report the most consequential findings first. Give the affected location, the triggering conditions, the consequence and the smallest fix that addresses it. Distinguish checks you ran from facts you inferred from the code.

## Example

If a grant is checked only when a session starts, verify what a session can do after that grant is withdrawn. Cite the write path and suggest a regression test that exercises the old session after withdrawal.

Adapted from Addy Osmani's Code Review and Quality. [Source and MIT attribution](../../../../../ATTRIBUTION.md)
