# Harness engineering guidelines

- Read the [terminology and attribution rules](TERMINOLOGY.md) and the [command catalog](CATALOG.md).

## API and adapter boundaries

- Follow MVC in `harness_api`. Models own domain operations, business validation, state transitions, and persistence. Views define request and response schemas. Controllers translate HTTP requests into model calls and map results and domain errors to HTTP responses.
- Keep Click commands thin. Parse arguments, call the public API for the selected destination, format the result, and set the exit code. Put decisions such as whether a revision can be completed in the model.
- Keep MCP tools thin too. Expose only the operations the operator is authorized to use. Enforce permissions in callable code. Prompts guide behavior and are insufficient as access controls.
- Keep dependencies pointing inward. Domain operations should be callable in a plain Python test without starting FastAPI, Click, MCP, or Codex. CLI and MCP access Harness state through public `harness_api` exports. Keep SQL and database paths behind that interface. [Import boundary test](packages/harness_api/tests/test_architecture.py)
- Make the destination explicit and consistent across related reads and writes. A failed remote request must never silently fall back to the local workspace.

Use `OperatorAPI.unregister_operator(operator_id)` as the reference operation. Click parses the ID and prints the returned record. The HTTP controller passes the ID to the same method and returns 204. The model soft-deletes the operator and releases its open assignments in one transaction. The rollback test shows that a failed release leaves the operator registered. [Click command](packages/harness_operator/src/harness_operator/commands/unregister.py) · [HTTP controller](packages/harness_api/src/harness_api/controllers/accounts.py) · [Model](packages/harness_api/src/harness_api/models/accounts.py) · [Account tests](packages/harness_api/tests/test_accounts.py)

## Definitions and state

- Give each domain concept one meaning across Python, HTTP, CLI, and MCP. Reuse shared types where practical. When transport schemas differ, test that they preserve the same field meanings, defaults, and validation rules.
- Keep goal identity stable across revisions. A revision records the requirements in force at that point. Tie decisions to the revision they assessed and retain the evidence source. Completing a child changes the parent only when an explicit domain rule says so.
- Source adapters report what they observed and when. The model owns every assessment Harness promises to calculate. Adapters expose that result and the assistant explains it. Prove the rule through the public model operation in a plain Python test.
- For evidence writes, derive the submitter from caller context the application can establish. Preserve the requester and observer separately when known and mark unknown attribution explicitly. [Identity and attribution](TERMINOLOGY.md#identity-and-attribution)
- Make related writes atomic. Where a caller acts on a specific revision, check it inside the write transaction. Define what happens on retry.
- Update TERMINOLOGY.md when appropriate

## Schema changes

Keep the complete fresh-workspace schema in [001_initial.sql](packages/harness_api/src/harness_api/migrations/001_initial.sql). When stored data or tables need transformation, implement the version-aware upgrade in [WorkspaceDatabase](packages/harness_api/src/harness_api/database.py). Test a fresh workspace and a populated prior version, including reopening the upgraded database and checking that records and relationships survive. Resume numbered migration files only when the project explicitly adopts them.

## Tests and verification

- Test observable behavior through the smallest public entry point that owns it. For a bug, first write a test that fails for the reported behavior, then make the smallest change that fixes it.
- Prefer a temporary SQLite database, real files, and small fixtures. If a test needs a chain of mocks or knowledge of private calls, simplify the production code. Introduce a narrow seam only for the dependency that needs control, such as a clock or an external service.
- Test domain rules once in the model. Use focused adapter tests for argument mapping, response shapes, error handling, and destination selection. Add an end-to-end test when the risk lies in how components connect.
- For operator acceptance tests, populate an isolated workspace through the CLI. Check the tool call and structured result when retrieval matters. Check the facts in the final answer while allowing natural variations in wording.
- Run `make check` and `make test` for code changes. Run the signed-in `make test-live` when the slice affects live operator behavior. Report live results separately and identify any check that could not run.

## Scope and handoff

Ask in review, “If we add another caller for this operation tomorrow, which existing function gives it the same decision, attribution, and state change?”

- Implement the agreed slice through its normal entry points. Keep future capabilities in the design notes until a current use case needs them.
- When a public contract changes, update its callers, tests, and user-facing documentation together. In the handoff, state what changed, what was verified, and any remaining limitation.
