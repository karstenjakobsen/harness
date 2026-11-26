## Slice 7 — Let an operator discover and read versioned skills

Given a goal such as “Build a chess game in Go,” the operator can discover relevant skills, choose which ones to read, and use them to propose subgoals. After the run, the owner can see exactly which skill revisions the operator received and open the instructions as they existed at the time.

### 1. Ship two skills in the Harness repository

Start with `skills/chess-rules/` and `skills/go-testing/`. Each folder contains an `operator.yaml` manifest and a `SKILL.md` with the instructions. For example, `skills/chess-rules/operator.yaml` could contain:

```yaml
kind: skill
id: chess-rules
name: Chess rules
description: Plan and verify legal moves, check, and king safety.
author: Harness
revision: 1
```

The canonical ID stays stable if the folder moves. Give each skill enough substance to guide a real decision. For example, the chess skill can explain how to construct a position where moving a pinned piece exposes its king. The Go skill can show how to turn that position into a table-driven test with an explicit expected result.

### 2. Load the catalog into the workspace database at startup

Read the committed `skills/` tree from the Harness source revision, even when the caller starts in an empty workspace. Store the manifest, Markdown, source path, Git commit SHA, and content hash. The public model owns three rules:

- Importing the same skill revision with identical content is a no-op, including after an unrelated repository commit.
- Changing the manifest or instructions under an existing `(id, revision)` fails with a message identifying the skill and asking the author to bump its revision.
- A higher revision becomes available for discovery. Earlier revisions remain readable by their exact ID and revision.

### 3. Give the operator two audited MCP reads

| Tool | What it returns | What the run records |
|---|---|---|
| `list_skills()` | Current skill IDs, revisions, names, and descriptions | The skill versions listed |
| `read_skill(id, revision)` | The exact manifest, instructions, and source provenance | The skill version whose instructions were returned |

Use the existing MCP call recorder and expose the same version lookup through the public API and owner-scoped HTTP. From a run, the owner or future web UI can follow a read to the exact text. From a skill revision, the owner can find the runs that read it. A listing and a full read remain distinguishable. Neither establishes that the operator followed the advice.

**The operator chooses the skills and proposes the plan.** Harness handles import, lookup, and attribution. The proposed subgoals can stay in the reply for this slice.

### 4. Prove it through one offline test and one live scenario

**Offline:** Use a temporary Git repository and workspace database. Import twice, reject changed text under revision 1, then import revision 2. Reopen the workspace and verify that a run which read revision 1 still resolves to the original text and SHA.

**Signed in:** Create the chess goal through the CLI in an empty workspace. Ask the operator, *“What subgoals would you propose for this game, and how would you verify that a move cannot leave your own king in check?”* Keep skill IDs and tool names out of the prompt. Verify that the run read both seeded skills, that the answer gives a concrete chess position and a Go test with the correct expected result, and that the owner can follow both reads through HTTP.

I’d end Slice 7 there. It delivers a complete, inspectable planning run. The next slice can give the operator a parent-scoped grant to **save** its proposed subgoals, with this run already showing which guidance it consulted.