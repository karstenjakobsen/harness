# Harness boundaries before Slice 3

- [x] Use `OperatorAPI.unregister_operator` as the example of one public operation serving two callers. Follow the links from the Click and HTTP entry points to the transaction and its rollback test. [Engineering guidelines](../AGENTS.md#api-and-adapter-boundaries)
- [x] Document which account, target, and owner each entry point selects. For future writes, derive the submitter from established caller context, preserve the requester and observer separately when known, and make unknown attribution explicit. [Identity and attribution](../TERMINOLOGY.md#identity-and-attribution) · [Command catalog](../CATALOG.md#workspace-users-and-operators)
- [x] Put assessment rules in the model. Source adapters report observations, transport adapters return the model’s result, and the assistant explains it. [Definitions and state](../AGENTS.md#definitions-and-state)
- [x] Keep the proposed evidence operations, the Monday example, and the open historical-read decision together in the Slice 3 notes. [Proposed operations](SLICE3.md#proposed-operations)
- [x] Consolidate the fresh schema and existing-workspace upgrade policy. [Schema changes](../AGENTS.md#schema-changes)
- [x] Check static imports in the model, database, CLI and MCP production modules. The CLI and MCP import individual names from the public `harness_api` exports. The regression examples cover package aliases, wildcard imports and direct submodule imports. Each rejected example asserts the file, line, and dependency. [Architecture test](../packages/harness_api/tests/test_architecture.py)
- [x] Run `make check` and `make test`. Lint, formatting and the offline tests passed.
