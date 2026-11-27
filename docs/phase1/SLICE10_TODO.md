# Slice 10 — Run one worker attempt in Docker

**One image, one entrypoint, one submission tool, two different assignments.** Between the two Docker runs, vary only the attempt, the brief, the assigned skills and the initial workspace contents. Harness saves each artifact for operator review. [Slice 10 conversation](SLICE10.md)

Use the revised Slice 9 implementation baseline at `157346c`. Its tree differs from `5f07a8d` only by the addition of `PLAYBOOK.md`.

## Worker image and tools

- [x] **Build on `ghcr.io/icoretech/codex-docker:0.166.0`.** Pin `sha256:c0568397f66fb8cc22c541fbafe26948da5000d24770b0ac2e918517dfc02615` and add the `harness-worker` entrypoint in a thin Harness image. Record the base and worker image digests. Use that exact worker image for both acceptance cases. The upstream image packages the official Codex CLI and documents one-shot execution. [Upstream image package](https://github.com/icoretech/codex-docker/pkgs/container/codex-docker) · [Upstream usage](https://github.com/icoretech/codex-docker#readme)
- [x] **Run one Codex session per attempt.** `harness-worker run --attempt-id ID` runs `codex exec --json --sandbox workspace-write --skip-git-repo-check` in `/workspace`, including for an empty directory. The launcher supplies the worker MCP endpoint, attempt-bound credential and development Codex login at runtime. The shared instruction is “Read your assignment through worker MCP, carry it out in the workspace, and submit the requested deliverable.” The brief, filenames, skill IDs and project test command come from the assignment or checkout. [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- [ ] **Use Codex’s built-in file editing and shell tools.** Use those capabilities to create `cities.txt`, edit source, inspect `git diff` and run the project’s test in `/workspace`. The worker MCP endpoint handles the assignment and artifact handoff.
- [x] **Connect Codex directly to Harness worker MCP over Streamable HTTP.** Expose `get_work_brief()`, `list_skills()`, `read_skill(id, revision)` and `submit_work_result(relative_path)`. Derive the attempt from the authenticated session, check its authority on every call and audit the outcome. Scope skill listing and reads to the assigned revisions. Enforce authority and the bound revision in the public model operations. Keep the launcher and MCP adapter thin and target the same configured Harness workspace. [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

Use the Codex CLI directly to start one session and observe its exit. Harness MCP records what the session submitted. The entrypoint can later use the OpenAI TypeScript Codex SDK for programmatic session control or Vercel’s experimental `HarnessAgent` for choosing among coding agents. [Codex TypeScript SDK](https://github.com/openai/codex/blob/main/sdk/typescript/README.md) · [Vercel HarnessAgent](https://vercel.com/changelog/program-agent-harnesses-with-ai-sdk)

## Work items and attempts

- [x] Record an immutable work item with the goal ID and revision, brief, exact skill revisions and workspace input. Record each attempt separately with its ID, work item, process outcome and saved result.
- [x] Give the trusted launcher a lookup and launch path keyed by attempt ID. A repeated launch, including after a lost response or scratch cleanup, resolves to the same attempt and starts at most one container. Reject conflicting reuse of an ID. An intentional retry uses a fresh attempt ID under the same work item. A changed brief creates a new work item tied to the applicable goal revision. Preserve the earlier attempts and results.

## Workspace and result storage

- [x] Prepare a fresh host scratch directory for each attempt and bind-mount it writable at `/workspace` for the container’s non-root user. Start with either an empty directory or an isolated checkout of a recorded commit from a local test repository. The launcher prepares the checkout and keeps the source checkout separate. Use Docker’s `no` restart policy.
- [x] On `submit_work_result(relative_path)`, have the trusted host read the actual file from the authenticated attempt’s mount. Verify that the path resolves to a file inside that workspace. Save an independent copy outside scratch and link it to the attempt and goal revision before acknowledging success or cleaning scratch. Retain the worker’s attribution. An identical report retry returns the saved result, and a conflicting report leaves it intact. For checkout work, retain the base SHA, changes and test result.
- [x] The first successful save is authoritative. An authorized retry for the same attempt and relative path returns the original artifact ID without rereading scratch, including after scratch cleanup. A different path conflicts. Editing the scratch file after the first save cannot change the recorded artifact.
- [x] Record the container exit code separately from the submitted result. Leave the goal open for an operator to review the artifact and make a separate, audited completion decision.

Nomad integration, seeding a new attempt from saved changes, and remote Git credentials and review-branch publishing follow this slice.

## Acceptance

Run both briefs with plain Docker and the same built worker image digest in an isolated Harness workspace. Inspect the real Codex worker’s MCP calls and saved results.

| Target | What it proves |
| --- | --- |
| `make test-live` | **City handoff only.** Run one signed-in worker session and zero operator sessions. Start with an empty workspace and give the worker the five expected Danish city names in the brief for `cities.txt`. After scratch cleanup, a fresh owner process retrieves `cities.txt` by goal ID and verifies the five lines and worker attribution. |
| `make test-live-extended` | **Checkout handoff plus the existing signed-in scenarios.** Record a local fixture base SHA at which a specific test fails. Ask the worker to fix the implementation, run that test and submit its changes as an ordinary patch file through `submit_work_result(relative_path)`. After scratch cleanup, apply the saved patch to a clean checkout of that base and verify the same, unchanged test passes. Verify the original checkout remains intact. |

- [ ] Verify each container exits with code `0`, its MCP trace shows the brief and assigned skill reads and result submission, and the associated goals remain open at their original revisions.
- [x] Exercise duplicate launch after a lost response, a fresh retry with the same brief, and a changed brief. Verify container counts and work-item and attempt links. Exercise missing or invalid credentials, cross-attempt requests, direct invocation outside the worker’s authority, escaping artifact paths, and failed or repeated saves. Verify denied requests and failed saves leave prior results intact.
- [ ] Update [CATALOG.md](../../CATALOG.md), [TERMINOLOGY.md](../../TERMINOLOGY.md) and the [README](../../README.md) for the worker contract and live targets. Run `make check`, `make test`, `make test-live` and `make test-live-extended`. Create and run `SLICE10_EVIDENCE.sh` and capture the Docker acceptance output in `SLICE10_EVIDENCE.md`, including both image digests. Report signed-in and offline results separately. [Engineering guidelines](../../AGENTS.md#tests-and-verification)
