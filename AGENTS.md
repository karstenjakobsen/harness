# Harness engineering guidelines

- Read TERMINOLOGY.md
- Read CATALOG.md

## API and adapter boundaries

- Follow MVC in `harness_api`. Models own domain operations, business validation, state transitions, and persistence. Views define request and response schemas. Controllers translate HTTP requests into model calls and map results and domain errors to HTTP responses.
- Keep Click commands thin. Parse arguments, call the public API for the selected destination, format the result, and set the exit code. Put decisions such as whether a revision can be completed in the model.
- Keep MCP tools thin too. Expose only the operations the operator is authorized to use. Enforce permissions in callable code. Prompts guide behavior and are insufficient as access controls.
- Keep dependencies pointing inward. Domain operations should be callable in a plain Python test without starting FastAPI, Click, MCP, or Codex. Keep SQL and database paths behind the model's public interface.
- Make the destination explicit and consistent across related reads and writes. A failed remote request must never silently fall back to the local workspace.
- Keep the complete SQLite schema in `packages/harness_api/src/harness_api/migrations/001_initial.sql`. Make schema changes in that snapshot until the user explicitly asks to resume incremental migrations.

## Definitions and state

- Give each domain concept one meaning across Python, HTTP, CLI, and MCP. Reuse shared types where practical. When transport schemas differ, test that they preserve the same field meanings, defaults, and validation rules.
- Keep goal identity stable across revisions. A revision records the requirements in force at that point. Tie decisions to the revision they assessed and retain the evidence source. Completing a child changes the parent only when an explicit domain rule says so.
- Distinguish an observation, an assessment against requirements, and an audit record of an action. For example, recording an owner's link establishes who supplied it. Independent verification requires a separate observation.
- Make related writes atomic. Where a caller acts on a specific revision, check it inside the write transaction. Define what happens on retry. Preserve existing data through versioned migrations and test upgrades when stored meaning or structure changes.
- Update TERMINOLOGY.md when appropriate

## Tests and verification

- Test observable behavior through the smallest public entry point that owns it. For a bug, first write a test that fails for the reported behavior, then make the smallest change that fixes it.
- Prefer a temporary SQLite database, real files, and small fixtures. If a test needs a chain of mocks or knowledge of private calls, simplify the production code. Introduce a narrow seam only for the dependency that needs control, such as a clock or an external service.
- Test domain rules once in the model. Use focused adapter tests for argument mapping, response shapes, error handling, and destination selection. Add an end-to-end test when the risk lies in how components connect.
- For operator acceptance tests, populate an isolated workspace through the CLI. Check the tool call and structured result when retrieval matters. Check the facts in the final answer while allowing natural variations in wording.
- Run `make check` and `make test` for code changes. Run the signed-in `make test-live` when the slice affects live operator behavior. Report live results separately and identify any check that could not run.

## Scope and handoff

- Implement the agreed slice through its normal entry points. Keep future capabilities in the design notes until a current use case needs them.
- When a public contract changes, update its callers, tests, and user-facing documentation together. In the handoff, state what changed, what was verified, and any remaining limitation.
