# Harness engineering guidelines

- Read the [terminology and attribution rules](TERMINOLOGY.md) and the [command catalog](CATALOG.md).

## API and adapter boundaries

- Follow MVC in `harness_api`. Models own domain operations, business validation, state transitions, and persistence. Views define request and response schemas. Controllers translate HTTP requests into model calls and map results and domain errors to HTTP responses.
- Keep Click commands thin. Parse arguments, call the public API for the selected destination, format the result, and set the exit code. The model checks whether a requested transition is authorized and valid for the current revision.
- Keep MCP tools thin too. Expose only the operations the operator is authorized to use. Enforce permissions in callable code. Prompts guide behavior and are insufficient as access controls.
- Keep dependencies pointing inward. Domain operations should be callable in a plain Python test without starting FastAPI, Click, MCP, or Codex. Production CLI and MCP modules import Harness API dependencies with `from harness_api import Name`, where each name is in `harness_api.__all__`. Keep SQL and database paths behind that interface. [Import boundary test](packages/harness_api/tests/test_architecture.py)
- Make the destination explicit and consistent across related reads and writes. A failed remote request must never silently fall back to the local workspace.

Use `OperatorAPI.unregister_operator(operator_id)` as the reference operation. Click parses the ID and prints the returned record. The HTTP controller passes the ID to the same method and returns 204. The model soft-deletes the operator and releases its open assignments in one transaction. The rollback test shows that a failed release leaves the operator registered. [Click command](packages/harness_operator/src/harness_operator/commands/unregister.py) · [HTTP controller](packages/harness_api/src/harness_api/controllers/accounts.py) · [Model](packages/harness_api/src/harness_api/models/accounts.py) · [Account tests](packages/harness_api/tests/test_accounts.py)

## Definitions and state

- Give each domain concept one meaning across Python, HTTP, CLI, and MCP. Reuse shared types where practical. When transport schemas differ, test that they preserve the same field meanings, defaults, and validation rules.
- Keep goal identity stable across revisions. A revision records the requirements in force at that point. Tie decisions to the revision they assessed and retain the evidence source. Completing a child changes the parent only when an explicit domain rule says so.
- Source adapters report what they observed and when. Harness preserves those facts and owns the exact calculations it promises, such as counting distinct owner-confirmed dates. Add a calculation when a concrete goal needs a reproducible result.
- Leave interpretation of open-ended criteria to the owner or delegated operator. A day-pass receipt can prompt the question “Did you join?” Recording the receipt preserves evidence. Completing the goal requires a separate decision. Keep goal-specific judgment out of event handlers, prompts that mandate a transition, and model branches keyed to goal content.
- For evidence writes, derive the submitter from caller context the application can establish. Preserve the requester and observer separately when known and mark unknown attribution explicitly. [Identity and attribution](TERMINOLOGY.md#identity-and-attribution)
- Make related writes atomic. Where a caller acts on a specific revision, check it inside the write transaction. Define what happens on retry.
- For delegated writes, derive the registered operator and grant from the trusted session. Require an explicit grant for the requested action. An assignment records responsibility on its own. Recheck the exact grant, target and revision inside the public model operation, including on retry. For completion, validate the cited observations and save the decision maker, rationale, citations and status change together. Preserve each observation’s original attribution.
- Update TERMINOLOGY.md when appropriate

## Schema changes

Keep the complete fresh-workspace schema in [001_initial.sql](packages/harness_api/src/harness_api/migrations/001_initial.sql). Schema version 7 requires a fresh database. Reject pre-v7 and populated unversioned workspaces without altering their contents. For subsequent versions, when stored data or tables need transformation, implement the version-aware upgrade in [WorkspaceDatabase](packages/harness_api/src/harness_api/database.py). Test a fresh workspace and a populated prior version, including reopening the upgraded database and checking that records and relationships survive. Resume numbered migration files only when the project explicitly adopts them.

## Tests and verification

- Test observable behavior through the smallest public entry point that owns it. For a bug, first write a test that fails for the reported behavior, then make the smallest change that fixes it.
- Prefer a temporary SQLite database, real files, and small fixtures. If a test needs a chain of mocks or knowledge of private calls, simplify the production code. Introduce a narrow seam only for the dependency that needs control, such as a clock or an external service.
- Test domain rules once in the model. Use focused adapter tests for argument mapping, response shapes, error handling, and destination selection. Add an end-to-end test when the risk lies in how components connect.
- For operator acceptance tests, populate an isolated workspace through the CLI. Check the tool call and structured result when retrieval matters. Check the facts in the final answer while allowing natural variations in wording.
- For a new delegated action, test the authority boundary directly. Cover a valid grant, an out-of-scope target, a pre-delegation assignment after upgrade, and a grant withdrawn after session start. Regrant the action and verify the old session is still denied. Verify denied writes and failed transactions leave history intact. At MCP, check both tool discovery and direct invocation from an advisory session.
- Test discretion with the same open-ended request before and after stronger evidence arrives. Inspect the live trace and saved state for both outcomes. The first turn may seek clarification while the goal stays open. The second can exercise the delegated action. [Slice 3 acceptance](docs/SLICE3_TODO.md#acceptance)
- Run `make check` and `make test` for code changes. Run the signed-in `make test-live` when the slice affects live operator behavior. Report live results separately and identify any check that could not run.

## Scope and handoff

Ask in review, “If we add another caller tomorrow, which model operation enforces the same authority, attribution and state change? If the goal changes from joining a gym to joining a library, can the operator use the same tools and exercise its own judgment?”

- Implement the agreed slice through its normal entry points. Keep future capabilities in the design notes until a current use case needs them.
- When a public contract changes, update its callers, tests, and user-facing documentation together. In the handoff, state what changed, what was verified, and any remaining limitation.
