# Slice 7 acceptance evidence

From the repository root, run the evidence script with the workspace dependencies installed and Codex signed in. [Evidence script](SLICE7_EVIDENCE.sh)

```bash
bash docs/SLICE7_EVIDENCE.sh
```

The signed-in test creates **Build a chess game in Go** through the CLI and asks a fresh advisory session for subgoals and a king-safety test. The owner’s question names the goal and leaves skill selection to the operator. The test matches each structured MCP skill read to its saved HTTP revision, then follows the revision back to the run and call that returned it. It also checks the goal’s revision and descendants after the reply. [Slice 7 acceptance](SLICE7_TODO.md#acceptance)

The offline test imports two revision-1 skills from a temporary Git repository and reads only the chess instructions in its first run. A commit containing a valid Go update and a conflicting chess edit tests atomic rollback. After a valid revision bump and removal of the chess skill, the test reopens the workspace without the checkout or Git executable and compares the original manifest, Markdown, source path, commit SHA and content hash with the saved HTTP response. The two tests use separate workspaces and source histories.

## Captured output

Both tests passed on 25 November 2026 with warnings treated as errors. In advisory run 1, call 2 listed both skills. Calls 4 and 5 returned their revision-1 instructions. The operator proposed four subgoals in its reply. The saved goal stayed at revision 1 with zero children.

````text

Owner's question
For my ‘Build a chess game in Go’ goal, what subgoals would you propose, and how would you verify that a move cannot leave your own king in check?

Signed-in operator's reply
**Build a chess game in Go** (goal #1) — Active, revision 1, with no saved subgoals or target date.

I’d propose four subgoals:

1. **Represent a position.** Store the board, side to move, castling rights, and en passant state. Verify that a test position loads with the expected pieces and turn.
2. **Generate legal moves.** Implement piece movement and attack detection, then filter candidate moves for king safety. Verify pins, moves that escape check, castling through attacked squares, and en passant captures that expose the king.
3. **Finish the game rules.** Handle promotion, checkmate, stalemate, and draws. Verify each outcome with a small position and an explicit expected result.
4. **Make it playable.** Start with a two-player terminal interface. Verify that players can enter moves, see the board and result, and retry after an illegal move without losing their turn.

**King-safety check.** Apply each candidate move to a copy of the position, including any capture or special-move effects. Then check whether the opponent attacks the moving side’s king in the resulting position. Reject the move if the king is attacked. Use a dedicated attack check so that squares attacked by pinned enemy pieces still count. For castling, also check the king’s starting and transit squares.

**Small next step.** Write a table-driven Go test using `k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1`. White’s rook on e2 shields its king on e1 from Black’s rook on e8.

| Candidate | Expected | Why |
|---|---|---|
| `e2f2` | Illegal | Moving off the e-file exposes White’s king. |
| `e2e3` | Legal | The rook still blocks the e-file. |

Exercise the public move API and assert that rejecting `e2f2` preserves the board and leaves White to move. The legal case also catches an implementation that rejects every move by a pinned piece. Run the suite with `go test ./...`.

Verified HTTP response excerpts
{
  "/runs/1": {
    "mode": "advisory",
    "outcome": "succeeded",
    "calls": [
      {
        "sequence": 2,
        "tool": "list_skills",
        "outcome": "returned",
        "returned_skills": [
          {
            "id": "chess-rules",
            "revision": 1
          },
          {
            "id": "go-testing",
            "revision": 1
          }
        ]
      },
      {
        "sequence": 4,
        "tool": "read_skill",
        "outcome": "returned",
        "returned_skills": [
          {
            "id": "chess-rules",
            "revision": 1
          }
        ]
      },
      {
        "sequence": 5,
        "tool": "read_skill",
        "outcome": "returned",
        "returned_skills": [
          {
            "id": "go-testing",
            "revision": 1
          }
        ]
      }
    ]
  },
  "/skills/chess-rules/revisions/1": {
    "source_path": "skills/chess-rules",
    "commit_sha": "8e54912f9d99e09f24d1b7b0ef5fc1ecbc74eb42",
    "content_hash": "fdf0371dcd5609343e69b6c78202dfd56769cdb55489a7f93254f33a9752ad05",
    "instructions_excerpt": "# Verify king safety\n\nA sliding piece can move along an open rank or file, yet a move that exposes its own king to attack is illegal. When planning move generation, separate the piece’s movement rules from the king-safety check. Apply a candidate move to a copy of the position, then test whether the opponent attacks the moving side’s king."
  },
  "/skills/chess-rules/revisions/1/reads": [
    {
      "run_id": 1,
      "sequence": 4
    }
  ],
  "/skills/go-testing/revisions/1": {
    "source_path": "skills/go-testing",
    "commit_sha": "8e54912f9d99e09f24d1b7b0ef5fc1ecbc74eb42",
    "content_hash": "b0d10b00b48eebb76c9733dfbc05c8798d236502c836f9a1af89d0c5be0003a3",
    "instructions_excerpt": "# Test a move rule in Go\n\nGive each test case a position, side to move, candidate move and expected result. Pair a move that violates the rule with a nearby legal move from the same position. A legality check that always returns false should fail the second case."
  },
  "/skills/go-testing/revisions/1/reads": [
    {
      "run_id": 1,
      "sequence": 5
    }
  ]
}
Goal 1 after the run: revision 1, 0 descendants.
.Processing request of type CallToolRequest
Processing request of type ListToolsRequest
Processing request of type CallToolRequest
Processing request of type CallToolRequest
Processing request of type CallToolRequest
Processing request of type CallToolRequest
Processing request of type ListToolsRequest
Processing request of type CallToolRequest

Offline catalog import rejected: Skill 'chess-rules' revision 1 changed. Bump its revision.
Discovery after rollback: [('chess-rules', 1), ('go-testing', 1)]
Exact lookup of go-testing revision 2 raised SkillNotFoundError.
Discovery after removal: [('go-testing', 2)]
Historical HTTP read without Git: /skills/chess-rules/revisions/1
  Instructions: Instructions for chess-rules
  Source: skills/b-chess at e8d99bf7e81df552ab6c651fc9b3089c7d174b14
  Content hash: d30249dfce58f99a64a0b7ae1bae31948cd72f845cdf689ce869293fca7a3bd4
  Full reads of chess-rules revision 1: [{'run_id': 1, 'sequence': 2}, {'run_id': 2, 'sequence': 2}]
  Full reads of go-testing revision 1 (only listed): []
.
2 passed in 25.79s
````
